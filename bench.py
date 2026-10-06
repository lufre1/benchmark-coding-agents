#!/usr/bin/env python3
"""Coding-agent testbench (opencode + 6 other agent CLIs) on GWDG SAIA.

Runs coding tasks against combos (agent harness, phases, model), scores each
run with a hidden test suite, records token/request metrics, and generates a
comparison report.

Commands:
    bench.py list                       show tasks and combos
    bench.py status                     show SAIA budget and run counts
    bench.py run [options]              run tasks x combos (sequential)
    bench.py report                     write results.csv and report.md
    bench.py import-deepswe             import the DeepSWE v1.1 subset into tasks/
    bench.py pull-deepswe               pre-pull the DeepSWE task images
    bench.py validate-deepswe           oracle/null gate for imported DeepSWE tasks
    bench.py gc                         remove orphaned bench containers

Two run paths:
  * legacy combos (no "agent" key): headless `opencode run` on the host with
    the global opencode config + SAIA plugin, as since 2026-07-14.
  * agent combos ("agent": opencode|aider|mini|openhands|omp|pi|mcode): the
    agent runs in a docker container (or a host scratch dir with
    --executor host) and reaches SAIA only via saia_gateway.py.

Stdlib only, Python 3.11+.
"""

import argparse
import csv
import json
import os
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import executors
from agents import (FALLBACK_RE, PhaseCmd, RunCtx, add_tokens, db_usage, empty_tokens,
                    make_adapter, parse_events)

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
RUNS_DIR = Path(os.environ.get("BENCH_RUNS_DIR", ROOT / "runs"))
MATRIX_FILE = ROOT / "matrix.json"
BUDGET_FILE = Path.home() / ".cache/opencode/saia-gwdg-budget.json"
GATEWAY_BUDGET_FILE = Path.home() / ".cache/saia-gateway/budget.json"
DB_FILE = Path.home() / ".local/share/opencode/opencode.db"
OPENCODE = shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")
TOOLBOX_MANIFEST = executors.TOOLBOX / "manifest.json"

# Provider-side failures (SAIA outages, plugin abort on 5xx bursts): the agent
# was cut off through no fault of its own, so such runs are excluded from
# aggregate scores.
PROVIDER_ERROR_RE = re.compile(r"(?i)5xx|server error|service looks down|overloaded|too many requests")

# Budget exhaustion (pacer floor aborts, "All N SAIA key(s) nearly exhausted"):
# a pacing failure, not an agent failure — the run is invalid and worth
# retrying after a cooldown, same as provider trouble.
BUDGET_ERROR_RE = re.compile(r"(?i)nearly exhausted|budget LOW")

# Gateway causes that mean SAIA (not the agent) failed the request.
UPSTREAM_FAILURE_CAUSES = {"headers_timeout", "upstream_unreachable", "rate_limited",
                           "no_first_byte", "stream_idle_timeout", "stream_upstream_error",
                           "stream_too_slow"}

# Retro-classification of runs recorded before the integrity fixes.
HIDDEN_READ_RE = re.compile(r"/tasks/[^/\"'\s]+/(hidden_tests|reference)\b")
MINILANG2_LEAK_SINCE = "2026-07-20"   # tasks/minilang2/hidden_tests/interp.py shadowed agents

# Agent-written files that could hijack pytest collection or reporting.
EVAL_STRIP = ("conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml",
              "sitecustomize.py", "usercustomize.py")


def log(msg):
    print(f"[bench {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def load_matrix():
    return read_json(MATRIX_FILE)


def load_tasks():
    tasks = {}
    for task_file in sorted(TASKS_DIR.glob("*/task.json")):
        task = read_json(task_file)
        task_dir = task_file.parent
        task["dir"] = task_dir
        task["prompt"] = (task_dir / "prompt.md").read_text()
        task.setdefault("kind", "host")
        tasks[task["name"]] = task
    return tasks


# ---------------------------------------------------------------- budget

BUCKET_LIMITS = {"hour": 200, "day": 1000, "month": 3000}
KEYS_FILE = Path.home() / ".local/share/opencode/saia-gwdg-keys.json"


def _read_snapshot(path):
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _stamp(entry):
    try:
        return datetime.fromisoformat(entry["updatedAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def read_budget():
    """Merged budget snapshot from the opencode plugin and the SAIA gateway
    (both key-labelled the same way): per key the freshest counts win, a key
    either writer saw rejected stays dead, exhaustion stamps are OR-ed."""
    snaps = [s for s in (_read_snapshot(BUDGET_FILE), _read_snapshot(GATEWAY_BUDGET_FILE)) if s]
    if not snaps:
        return None
    if len(snaps) == 1:
        return snaps[0]
    merged = {}
    for snap in snaps:
        for entry in snap.get("keys") or []:
            label = entry.get("label")
            cur = merged.get(label)
            if cur is None or _stamp(entry) > _stamp(cur):
                new = dict(entry)
                if cur:
                    new["dead"] = bool(cur.get("dead")) or bool(entry.get("dead"))
                    new["exhausted"] = {b: max((cur.get("exhausted") or {}).get(b) or 0,
                                               (entry.get("exhausted") or {}).get(b) or 0)
                                        for b in ("hour", "day", "month")}
                merged[label] = new
            else:
                cur["dead"] = bool(cur.get("dead")) or bool(entry.get("dead"))
    newest = max(snaps, key=lambda s: s.get("updatedAt") or "")
    return {"updatedAt": newest.get("updatedAt"), "remaining": newest.get("remaining"),
            "keys": list(merged.values()), "merged_from": len(snaps)}


def keyring_size():
    """Number of SAIA keys in rotation (auth.json key + extras). Reads only
    the count, never the key material."""
    try:
        extras = read_json(KEYS_FILE).get("keys", [])
        return 1 + sum(1 for k in extras if isinstance(k, str) and k)
    except (OSError, ValueError, AttributeError):
        return 1


def budget_view(snap):
    """Aggregate remaining counts across keys. Handles both the multi-key
    snapshot format ({keys: [{label, updatedAt, remaining}], ...}) and the
    old single-key one. Mirroring the plugin's freshBudget(): a key without
    fresh (<65 min) data counts as full — its buckets have likely reset.
    Dead (401/403) keys count as empty, exhausted buckets as empty until
    their reset TTL has passed."""
    entries = snap.get("keys")
    if not isinstance(entries, list) or not entries:
        entries = [{"updatedAt": snap.get("updatedAt"),
                    "remaining": snap.get("remaining")}]
    view = {"hour": 0, "day": 0, "month": 0}
    ttl = {"hour": 3600, "day": 86400, "month": 30 * 86400}
    any_fresh = False
    dead = 0
    now = datetime.now(timezone.utc)
    for entry in entries:
        if entry.get("dead"):
            dead += 1
            continue
        try:
            updated = datetime.fromisoformat(entry["updatedAt"].replace("Z", "+00:00"))
            fresh = timedelta(0) <= now - updated <= timedelta(minutes=65)
        except (KeyError, TypeError, ValueError, AttributeError):
            fresh = False  # never-used keys have updatedAt: null
        any_fresh = any_fresh or fresh
        remaining = entry.get("remaining") or {}
        exhausted = entry.get("exhausted") or {}
        for bucket in view:
            stamp = exhausted.get(bucket) or 0
            if stamp and now.timestamp() * 1000 - stamp < ttl[bucket] * 1000:
                continue
            value = remaining.get(bucket)
            view[bucket] += (value if fresh and isinstance(value, (int, float))
                             else BUCKET_LIMITS[bucket])
    # Keys in rotation but missing from the snapshot (never used yet, e.g.
    # freshly added extras) count as full.
    unlisted = max(0, keyring_size() - len(entries))
    for bucket in BUCKET_LIMITS:
        view[bucket] += unlisted * BUCKET_LIMITS[bucket]
    view["fresh"] = any_fresh
    view["key_count"] = len(entries) + unlisted
    view["dead_keys"] = dead
    return view


def budget_gate(floor, wait):
    """Block until the aggregated SAIA hourly request budget (across all
    keys) is above `floor`. Returns the full budget snapshot (or None if
    the budget file is unreadable). Entirely stale data counts as
    replenished."""
    max_wait = 90 * 60  # 90 minutes — abort if the budget hasn't reset by then
    waited = 0
    while True:
        snap = read_budget()
        if snap is None:
            log("WARNING: no budget file readable, proceeding blind")
            return None
        view = budget_view(snap)
        if not view["fresh"] or view["hour"] >= floor:
            return snap
        if view["day"] < floor:
            sys.exit(f"ABORT: daily SAIA budget nearly exhausted (~{view['day']} requests left)")
        if not wait:
            sys.exit(f"ABORT: hourly SAIA budget too low (~{view['hour']} < floor {floor}); "
                     "rerun without --no-wait to wait")
        waited += 120
        eta = max(0, max_wait - waited)
        log(f"hourly budget ~{view['hour']} across {view['key_count']} key(s) "
            f"< floor {floor}, waited {waited//60}m, will wait up to {eta//60}m more")
        if waited >= max_wait:
            sys.exit(f"ABORT: waited {waited//60}m for SAIA hourly budget to reset "
                     f"(still ~{view['hour']} < floor {floor}), giving up")
        time.sleep(120)


# ---------------------------------------------------------------- gateway client

class GatewayClient:
    """Admin side of saia_gateway.py (loopback only)."""

    def __init__(self, defaults):
        gw = defaults.get("gateway") or {}
        override = os.environ.get("BENCH_GATEWAY")  # tests: a gateway on another port
        self.admin = (override or gw.get("admin_url", "http://127.0.0.1:8787")).rstrip("/")
        self.host_url = (override.rstrip("/") + "/v1" if override
                         else gw.get("host_url", "http://127.0.0.1:8787/v1"))
        self.container_url = gw.get("container_url", "http://saia-gw:8787/v1")

    def call(self, method, path, payload=None, timeout=30):
        req = urllib.request.Request(
            self.admin + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def health(self):
        try:
            return self.call("GET", "/_bench/health", timeout=5)
        except (OSError, ValueError):
            return None

    def register(self, run_id, run_dir, cap, faults=None, canaries=(), store="delta",
                 params=None):
        return self.call("POST", "/_bench/runs", {
            "run_id": run_id, "log_dir": str(run_dir), "cap": cap, "faults": faults,
            "canaries": list(canaries), "store": store, "params": params or {}})

    def status(self, run_id):
        try:
            return self.call("GET", f"/_bench/runs/{run_id}", timeout=5)
        except (OSError, ValueError):
            return None

    def finish(self, run_id):
        try:
            return self.call("DELETE", f"/_bench/runs/{run_id}")
        except (OSError, ValueError):
            return None


def health_probe(gw):
    """One tiny request through the gateway (feeds its recent-health window)."""
    run_id = f"health-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    try:
        token = gw.call("POST", "/_bench/runs", {"run_id": run_id, "cap": 1,
                                                 "store": "none"})["token"]
        req = urllib.request.Request(
            gw.host_url + "/chat/completions", method="POST",
            data=json.dumps({"model": "probe", "max_tokens": 5, "messages": [
                {"role": "user", "content": "Reply with OK."}]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            urllib.request.urlopen(req, timeout=300).read()
        except (OSError, urllib.error.HTTPError):
            pass
    finally:
        gw.finish(run_id)


def health_gate(gw, defaults, wait):
    """Block while SAIA is degraded: fewer than `min_ok_ratio` of the
    gateway's upstream attempts in the last `window_s` succeeded. Failed
    attempts are charged, and runs started into an outage only measure the
    outage. Without recent traffic a probe request supplies the data."""
    cfg = {"window_s": 900, "min_ok_ratio": 0.5, "min_attempts": 6, "poll_s": 600,
           "max_wait_s": 6 * 3600, **(defaults.get("health_gate") or {})}
    if not cfg.get("enabled", True):
        return None
    key, waited = str(cfg["window_s"]), 0
    while True:
        st = ((gw.health() or {}).get("recent") or {}).get(key) or {}
        if (st.get("attempts") or 0) < cfg["min_attempts"]:
            health_probe(gw)
            st = ((gw.health() or {}).get("recent") or {}).get(key) or {}
        ratio = st.get("ok_ratio")
        if not st.get("attempts") or ratio >= cfg["min_ok_ratio"]:
            return st
        if not wait:
            sys.exit(f"ABORT: SAIA degraded ({ratio:.0%} of {st['attempts']} attempts ok in "
                     f"the last {cfg['window_s'] // 60} min); rerun without --no-wait to wait")
        if waited >= cfg["max_wait_s"]:
            sys.exit(f"ABORT: SAIA degraded for {waited // 3600}h ({ratio:.0%} ok) — giving up")
        log(f"SAIA degraded: {ratio:.0%} of {st['attempts']} attempts ok in the last "
            f"{cfg['window_s'] // 60} min — waiting {cfg['poll_s'] // 60} min "
            f"(waited {waited // 60} min so far)")
        time.sleep(cfg["poll_s"])
        waited += cfg["poll_s"]
        health_probe(gw)


def outage_check(gw, defaults):
    """Reason string if SAIA is in a sustained outage (gateway-wide window),
    else None. Used to abort a running agent early."""
    cfg = {"window_s": 900, "max_ok_ratio": 0.2, "min_attempts": 10,
           **(defaults.get("outage_abort") or {})}
    if not cfg.get("enabled", True):
        return None
    st = ((gw.health() or {}).get("recent") or {}).get(str(cfg["window_s"])) or {}
    ratio = st.get("ok_ratio")
    if (st.get("attempts") or 0) >= cfg["min_attempts"] and ratio is not None \
            and ratio < cfg["max_ok_ratio"]:
        return (f"SAIA outage: {ratio:.0%} of {st['attempts']} attempts ok in the last "
                f"{cfg['window_s'] // 60} min")
    return None


# ---------------------------------------------------------------- agent process

def run_phase(cmd, timeout, events_path, stderr_path, stall_timeout=300, env=None, cwd=None,
              stdin_path=None, activity=None, on_kill=None, abort=None):
    """Run one agent invocation.

    Kills the process on overall timeout OR when it makes no progress for
    `stall_timeout` seconds — neither stdout growth nor (if `activity` is
    given) gateway traffic (SAIA sometimes leaves a streaming request hanging
    forever without an error). `on_kill` runs after the kill (the docker
    executor uses it to stop the process inside the container). `abort`, polled
    every 60 s, returns a reason to give up early (e.g. a SAIA outage).
    Returns (exit_code, timed_out, stalled, wall_s, aborted_reason).
    """
    t0 = time.monotonic()
    timed_out = stalled = False
    aborted = None
    last_abort_check = t0
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    try:
        with open(events_path, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen(
                cmd, stdout=out, stderr=err, stdin=stdin, env=env, cwd=cwd,
                start_new_session=True,
            )
            last_size = -1
            last_progress = time.monotonic()
            while True:
                try:
                    code = proc.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                try:
                    size = os.path.getsize(events_path)
                except OSError:
                    size = 0
                if size != last_size:
                    last_size = size
                    last_progress = now
                elif activity is not None and now - last_progress >= 30 and activity():
                    last_progress = now
                if abort is not None and now - last_abort_check >= 60:
                    last_abort_check = now
                    aborted = abort()
                if now - t0 >= timeout:
                    timed_out = True
                elif now - last_progress >= stall_timeout:
                    stalled = True
                elif not aborted:
                    continue
                code = None
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    code = proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                if on_kill:
                    on_kill()
                break
    finally:
        if stdin_path:
            stdin.close()
    return code, timed_out, stalled, round(time.monotonic() - t0, 1), aborted


# ---------------------------------------------------------------- evaluation

# Injected next to the hidden tests so one infinite-looping implementation
# fails individual tests instead of zeroing the whole suite.
EVAL_CONFTEST = '''\
import signal

import pytest


@pytest.fixture(autouse=True)
def _per_test_timeout():
    def handler(signum, frame):
        raise TimeoutError("test exceeded 5s (per-test watchdog)")

    old = signal.signal(signal.SIGALRM, handler)
    signal.alarm(5)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)
'''


def evaluate(task, workspace, run_dir, eval_timeout):
    """Score a workspace with the task's hidden tests, in a clean copy.

    Hardening (the agent controls the workspace):
      * agent-written pytest config/hooks are dropped (EVAL_STRIP, *.pth),
        and pytest runs with a bench-owned ini and explicit rootdir;
      * deliverables can only come from the agent: a hidden-test file named
        like a deliverable is never copied, and a workspace file named like a
        hidden-test helper is removed, so neither side can shadow the other.
    """
    workspace = Path(workspace).resolve()
    run_dir = Path(run_dir).resolve()
    expects = task.get("expects", [])
    result = {
        "expected_missing": [f for f in expects if not (workspace / f).exists()],
        "ran": False, "eval_timed_out": False,
        "tests_total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
    }
    hidden_src = task["dir"] / "hidden_tests"
    hidden_names = ({p.name for p in hidden_src.iterdir()} if hidden_src.is_dir() else set()
                    ) - set(expects)
    with tempfile.TemporaryDirectory(prefix="bench-eval-") as tmp:
        evalws = Path(tmp) / "ws"
        shutil.copytree(workspace, evalws, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache",
                                                      "hidden_tests"))
        stripped = []
        for path in sorted(evalws.rglob("*")):
            rel = path.relative_to(evalws)
            if (path.name in EVAL_STRIP or path.suffix == ".pth"
                    or (len(rel.parts) == 1 and path.name in hidden_names)):
                stripped.append(str(rel))
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        if stripped:
            result["eval_stripped"] = stripped
        hidden_dst = evalws / "hidden_tests"
        shutil.copytree(hidden_src, hidden_dst, ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", *expects))
        (hidden_dst / "conftest.py").write_text(EVAL_CONFTEST)
        ini = Path(tmp) / "bench-pytest.ini"
        ini.write_text("[pytest]\n")
        junit = run_dir / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", "hidden_tests", "-q", "-c", str(ini),
               "--rootdir", str(evalws), "-p", "no:cacheprovider", f"--junitxml={junit}"]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp,
               "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        try:
            proc = subprocess.run(cmd, cwd=evalws, timeout=eval_timeout, env=env,
                                  capture_output=True, text=True)
            (run_dir / "eval_output.log").write_text(proc.stdout + "\n" + proc.stderr)
        except subprocess.TimeoutExpired:
            result["eval_timed_out"] = True
            return result
    if not junit.exists():
        return result
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return result
    for suite in root.iter("testsuite"):
        tests = int(suite.get("tests", 0))
        failures = int(suite.get("failures", 0))
        errors = int(suite.get("errors", 0))
        skipped = int(suite.get("skipped", 0))
        result["tests_total"] += tests
        result["failed"] += failures
        result["errors"] += errors
        result["skipped"] += skipped
        result["passed"] += tests - failures - errors - skipped
    result["ran"] = True
    return result


# ---------------------------------------------------------------- single run

def qualify_model(model, provider):
    return model if "/" in model else f"{provider}/{model}"


def new_run_dir(task, combo_name, repeat):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_combo = re.sub(r"[^A-Za-z0-9._@-]", "-", combo_name)
    run_id = f"{timestamp}_{task['name']}_{safe_combo}_r{repeat}"
    run_dir = RUNS_DIR / run_id
    suffix = 2
    while run_dir.exists():  # concurrent runs can share a start second
        run_dir = RUNS_DIR / f"{run_id}_{suffix}"
        suffix += 1
    return run_dir.name, run_dir


def agent_env():
    """Minimal environment for legacy host opencode runs: never forward the
    bench's own environment (~/.bashrc exports SAIA_API_KEY)."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "USER", "LOGNAME", "SHELL", "TMPDIR",
            "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
    return {k: os.environ[k] for k in keep if k in os.environ}


def do_run(task, combo_name, combo, defaults, repeat, args):
    if combo.get("agent"):
        return do_agent_run(task, combo_name, combo, defaults, repeat, args)
    if task.get("kind") != "host":
        log(f"SKIP {task['name']} x {combo_name}: legacy host combos only run in-house tasks")
        return None
    return do_legacy_run(task, combo_name, combo, defaults, repeat, args)


def do_legacy_run(task, combo_name, combo, defaults, repeat, args):
    """opencode with the global config + SAIA plugin, on the host. The
    workspace lives outside the repo (agents used to read hidden tests via
    ../../tasks) and is archived into the run dir afterwards."""
    run_id, run_dir = new_run_dir(task, combo_name, repeat)
    work_root = Path(os.environ.get("BENCH_WORK_ROOT") or defaults.get(
        "workspace_root", executors.WORK_ROOT)) / run_id
    workspace = work_root / "workspace"
    timeout = task.get("timeout_s", defaults["timeout_s"])
    phases = combo["phases"]

    if args.dry_run:
        log(f"DRY RUN {run_id}")
        for i, phase in enumerate(phases, 1):
            msg = "<task prompt>" if not phase.get("prompt") else phase["prompt"][:60] + "..."
            log(f"  phase {i}: opencode run --dir {workspace} --agent {phase['agent']} "
                f"--format json {'--auto ' if defaults.get('auto_approve') else ''}"
                f"{'-s <session> ' if i > 1 else ''}'{msg}'  (timeout {timeout}s)")
        if combo.get("models"):
            log(f"  workspace opencode.json agent models: {combo['models']}")
        return None

    budget_before = budget_gate(defaults["budget_floor_hour"], wait=not args.no_wait)
    run_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    starter = task["dir"] / "starter"
    if starter.is_dir():
        shutil.copytree(starter, workspace, dirs_exist_ok=True)
    # A repo of its own, so opencode treats the workspace (not an enclosing
    # repo) as the project root.
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=False)
    overrides = {agent: {"model": qualify_model(model, defaults["provider"])}
                 for agent, model in combo.get("models", {}).items()}
    # Arbitrary per-agent config for this combo (e.g. locking the plan phase
    # to read-only — under --auto the native plan agent otherwise delegates
    # implementation via the task tool).
    for agent, cfg in (combo.get("agent_config") or {}).items():
        overrides.setdefault(agent, {}).update(cfg)
    if overrides:
        (workspace / "opencode.json").write_text(json.dumps(
            {"$schema": "https://opencode.ai/config.json", "agent": overrides}, indent=2))

    log(f"RUN {run_id} ({len(phases)} phase(s), timeout {timeout}s/phase)")
    result = {
        "schema": 1, "hardened": True, "run_id": run_id, "task": task["name"],
        "combo": combo_name, "agent": "opencode-legacy",
        "models_config": combo.get("models", {}),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "phases": [], "flags": [], "invalid": False,
        "budget_before": budget_before,
        # Overlapping runs share the budget counters, so per-run deltas are
        # meaningless; the report then falls back to DB request counts.
        "budget_overlap": getattr(args, "parallel", 1) > 1,
    }

    session_id = None
    totals = {"steps": 0, "tool_calls": 0, "cost": 0.0, "tokens": empty_tokens()}
    all_sessions = []
    for i, phase in enumerate(phases, 1):
        message = phase.get("prompt") or task["prompt"]
        cmd = [OPENCODE, "run", "--dir", str(workspace),
               "--agent", phase["agent"], "--format", "json"]
        if defaults.get("auto_approve"):
            cmd.append("--auto")
        if session_id and i > 1:
            cmd += ["-s", session_id]
        cmd.append(message)
        events_path = run_dir / f"events_p{i}.jsonl"
        stderr_path = run_dir / f"stderr_p{i}.log"
        code, timed_out, stalled, wall_s, _ = run_phase(
            cmd, timeout, events_path, stderr_path,
            defaults.get("stall_timeout_s", 300), env=agent_env(), cwd=workspace)
        parsed = parse_events(events_path)
        if parsed["session_ids"]:
            session_id = session_id or parsed["session_ids"][0]
            all_sessions.extend(parsed["session_ids"])
        stderr_text = stderr_path.read_text(errors="replace")
        fallback = bool(FALLBACK_RE.search(stderr_text))
        phase_result = {
            "phase": i, "agent": phase["agent"], "exit_code": code,
            "timed_out": timed_out, "stalled": stalled, "wall_s": wall_s,
            "steps": parsed["steps"], "tool_calls": parsed["tool_calls"],
            "cost": parsed["cost"], "tokens": parsed["tokens"],
            "errors": parsed["errors"], "agent_fallback": fallback,
        }
        result["phases"].append(phase_result)
        totals["steps"] += parsed["steps"]
        totals["tool_calls"] += parsed["tool_calls"]
        totals["cost"] = round(totals["cost"] + parsed["cost"], 6)
        add_tokens(totals["tokens"], parsed["tokens"])
        if fallback:
            result["flags"].append(f"agent_fallback_p{i}")
            result["invalid"] = True
        if any(PROVIDER_ERROR_RE.search(e) for e in parsed["errors"]):
            result["flags"].append(f"provider_error_p{i}")
            result["invalid"] = True
        elif any(BUDGET_ERROR_RE.search(e) for e in parsed["errors"]):
            result["flags"].append(f"budget_exhausted_p{i}")
            result["invalid"] = True
        if stalled:
            result["flags"].append(f"stalled_p{i}")
            result["invalid"] = True
            break
        if timed_out:
            result["flags"].append(f"timeout_p{i}")
            break
        if code != 0:
            result["flags"].append(f"exit_{code}_p{i}")
            break
        if parsed["steps"] == 0:
            result["flags"].append(f"no_steps_p{i}")
            result["invalid"] = True
            break

    usage = db_usage(all_sessions, DB_FILE, log)
    if usage:
        result["db_usage"] = usage
        agents_used = {key.split("/", 1)[0] for key in usage["by_agent_model"]}
        expected = {p["agent"] for p in result["phases"]}
        if not expected & agents_used:
            result["flags"].append("expected_agent_missing_in_db")
            result["invalid"] = True

    result["totals"] = totals
    result["session_ids"] = list(dict.fromkeys(all_sessions))
    archived = run_dir / "workspace"
    shutil.copytree(workspace, archived, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "node_modules"))
    shutil.rmtree(work_root, ignore_errors=True)
    result["eval"] = evaluate(task, archived, run_dir, defaults["eval_timeout_s"])
    if result["eval"]["eval_timed_out"]:
        result["flags"].append("eval_timeout")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["wall_s"] = round(sum(p["wall_s"] for p in result["phases"]), 1)
    result["budget_after"] = read_budget()
    return finish_result(run_dir, result, totals)


def finish_result(run_dir, result, totals):
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    ev = result["eval"]
    reward = f", reward {ev['reward']}" if "reward" in ev else ""
    log(f"DONE {result['run_id']}: {ev['passed']}/{ev['tests_total']} hidden tests{reward}, "
        f"{result['wall_s']}s, {totals['steps']} steps, "
        f"{sum(totals['tokens'].values())} tokens"
        f"{' FLAGS: ' + ','.join(result['flags']) if result['flags'] else ''}")
    return result


def make_executor(task, run_id, defaults, args):
    kind = getattr(args, "executor", None) or defaults.get("executor", "docker")
    if task.get("kind") == "deepswe":
        import deepswe
        return deepswe.agent_executor(task, run_id, defaults)
    if kind == "host":
        root = os.environ.get("BENCH_WORK_ROOT") or defaults.get("workspace_root",
                                                                   executors.WORK_ROOT)
        return executors.HostExecutor(run_id, root)
    d = defaults.get("deepswe", {})
    return executors.DockerExecutor(run_id, defaults.get("inhouse_image", "python:3.12"),
                                    workdir="/app", memory=d.get("memory", "5g"),
                                    cpus=d.get("cpus", 2))


def seed_workspace(task, ex):
    """In-house tasks: starter files into the workdir, as a fresh git repo
    (aider needs one; it also keeps agents from adopting an enclosing repo).
    In containers, pytest comes from the toolbox wheels (offline)."""
    starter = task["dir"] / "starter"
    files = {}
    if starter.is_dir():
        for p in starter.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                files[f"{ex.workdir}/{p.relative_to(starter)}"] = (p.read_bytes(), 0o644)
    if files:
        ex.put_files(files)
    script = "git init -q && git add -A && git commit -q --allow-empty -m 'task starter'"
    if ex.kind == "docker":
        script = ("pip install -q --no-index --find-links /opt/agents/wheels pytest "
                  ">/dev/null 2>&1 || true; mkdir -p /app && cd /app && " + script)
    res = ex.sh(script, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"seeding workspace failed: {res.stderr.strip()[:300]}")


def plant_canary(ex, canary):
    """A decoy 'solution' outside the workdir. Its marker string showing up in
    any LLM request means the agent went looking outside the repo."""
    path = "/opt/solution.patch" if ex.kind == "docker" else str(Path(ex.workdir).parent /
                                                                  "solution.patch")
    body = (f"# reference solution — {canary}\n"
            f"diff --git a/SOLUTION b/SOLUTION\n+{canary}\n")
    ex.put_files({path: (body, 0o644)})
    return path


def classify_gateway(summary, phases, result):
    """Generic validity rules from gateway data (agent-independent)."""
    flags = result["flags"]
    if summary is None:
        flags.append("gateway_summary_missing")
        result["invalid"] = True
        return
    if summary.get("requests", 0) == 0:
        flags.append("no_requests")
        result["invalid"] = True
    causes = summary.get("causes") or {}
    upstream_failures = sum(v for k, v in causes.items()
                            if k in UPSTREAM_FAILURE_CAUSES or k.startswith("upstream_5"))
    if causes.get("budget_exhausted"):
        flags.append("budget_exhausted")
        result["invalid"] = True
    last = summary.get("last_cause") or ""
    if (last in UPSTREAM_FAILURE_CAUSES or last.startswith("upstream_5")
            or upstream_failures > 0.2 * max(1, summary.get("requests", 0))):
        flags.append("provider_error")
        result["invalid"] = True
    if any(p.get("stalled") for p in phases):
        if summary.get("inflight", 0) > 0 or last in UPSTREAM_FAILURE_CAUSES:
            flags.append("stalled")
            result["invalid"] = True
        else:
            flags.append("idle_kill")  # the agent itself hung: a valid failure
    if summary.get("cap_hit"):
        flags.append("request_cap")
    requested = set((summary.get("requested_models") or {}).keys()) - {
        result.get("model"), f"openai/{result.get('model')}", "None"}
    if requested:
        flags.append("model_rewritten")
    if summary.get("canary_hits"):
        flags.append("canary_read")
    if summary.get("faults_injected"):
        flags.append("fault_injected")


def do_agent_run(task, combo_name, combo, defaults, repeat, args):
    """One run of an agent harness against the gateway, in an executor."""
    adapter = make_adapter(combo)
    run_id, run_dir = new_run_dir(task, combo_name, repeat)
    timeout = task.get("timeout_s", defaults["timeout_s"])
    cap = combo.get("request_cap", defaults.get("request_cap", 150))
    gw = GatewayClient(defaults)
    ex = make_executor(task, run_id, defaults, args)
    gw_url = gw.container_url if ex.kind == "docker" else gw.host_url
    model = combo.get("model", defaults.get("model", "deepseek-v4-flash-0731"))

    ctx = RunCtx(run_id=run_id, run_dir=run_dir, task=task, combo=combo, defaults=defaults,
                 ex=ex, token="<run token>", gw_url=gw_url, prompt=task["prompt"],
                 request_cap=cap, timeout=timeout, kind=task.get("kind", "host"), model=model,
                 context_window=defaults.get("context_window", 131072),
                 max_output=defaults.get("max_output_tokens", 16384))
    phases = adapter.phases(ctx)
    if args.dry_run:
        log(f"DRY RUN {run_id} [{adapter.name} in {ex.describe()}], cap {cap}, timeout {timeout}s")
        prev = {"session_id": "<session>"}
        for i, phase in enumerate(phases, 1):
            argv, kw = ex.phase_command(adapter.build_cmd(ctx, i, phase, prev))
            shown = [re.sub(r"(?s)^(.{100}).+", r"\1…", a) for a in argv]
            log(f"  phase {i}: {' '.join(shown)}")
        return None

    if task.get("kind") == "deepswe":
        import deepswe
        if not deepswe.is_validated(task) and not args.allow_unvalidated:
            log(f"SKIP {task['name']}: not validated (bench.py validate-deepswe) — "
                "--allow-unvalidated to override")
            return None
    if gw.health() is None:
        sys.exit("ABORT: SAIA gateway not reachable at "
                 f"{gw.admin} — start it: systemctl --user start saia-gateway")
    budget_before = budget_gate(defaults["budget_floor_hour"], wait=not args.no_wait)
    health_before = health_gate(gw, defaults, wait=not args.no_wait)
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.md").write_text(task["prompt"])
    (run_dir / "agent").mkdir()
    canary = f"BENCH-CANARY-{secrets.token_hex(8)}"
    params = {**defaults.get("gateway_params", {}), **combo.get("gateway_params", {})}
    reg = gw.register(run_id, run_dir, cap, faults=combo.get("fault_profile"),
                      canaries=[canary], store=defaults.get("gateway_store", "delta"),
                      params=params)
    ctx.token = reg["token"]

    log(f"RUN {run_id} [{adapter.name} in {ex.describe()}] cap {cap}, timeout {timeout}s")
    result = {
        "schema": 2, "run_id": run_id, "task": task["name"], "task_kind": ctx.kind,
        "combo": combo_name, "agent": adapter.name, "model": model,
        "executor": ex.kind, "request_cap": cap, "gateway_params": params,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "phases": [], "flags": [], "invalid": False, "budget_before": budget_before,
        "saia_health_before": health_before,
        "budget_overlap": False,  # gateway accounting is per run
    }
    try:
        result["toolbox"] = read_json(TOOLBOX_MANIFEST) if ex.kind == "docker" else None
    except (OSError, ValueError):
        result["toolbox"] = None
    totals = {"steps": 0, "tool_calls": 0, "cost": 0.0, "tokens": empty_tokens()}
    summary = None
    try:
        ex.start()
        if ctx.kind != "deepswe":
            seed_workspace(task, ex)
        ex.put_files({ctx.prompt_file: (task["prompt"], 0o644)})
        result["canary_path"] = plant_canary(ex, canary)
        adapter.prepare(ctx)
        prev = {}
        session_ids = []
        for i, phase in enumerate(phases, 1):
            cmd = adapter.build_cmd(ctx, i, phase, prev)
            argv, kw = ex.phase_command(cmd)
            events_path = run_dir / f"events_p{i}.jsonl"
            stderr_path = run_dir / f"stderr_p{i}.log"
            code, timed_out, stalled, wall_s, aborted = run_phase(
                argv, timeout, events_path, stderr_path, defaults.get("stall_timeout_s", 300),
                env=kw["env"], cwd=kw["cwd"], stdin_path=kw["stdin_path"],
                activity=lambda: (lambda s: bool(s) and (s.get("inflight", 0) > 0 or
                                                         s.get("idle_s", 1e9) < 30))(
                    gw.status(run_id)),
                on_kill=ex.on_kill, abort=lambda: outage_check(gw, defaults))
            for src, name in adapter.artifacts(ctx):
                ex.copy_out(src, run_dir / "agent" / name)
            parsed = adapter.parse(ctx, i, events_path, stderr_path)
            session_ids += [s for s in parsed.get("session_ids", []) if s not in session_ids]
            if session_ids:
                prev["session_id"] = session_ids[0]
            phase_result = {
                "phase": i, "agent": phase.get("agent", adapter.name), "exit_code": code,
                "timed_out": timed_out, "stalled": stalled, "wall_s": wall_s,
                "steps": parsed["steps"], "tool_calls": parsed["tool_calls"],
                "cost": parsed.get("cost", 0), "tokens": parsed["tokens"],
                "errors": parsed["errors"][:20], "exit_status": parsed.get("exit_status"),
            }
            result["phases"].append(phase_result)
            totals["steps"] += parsed["steps"]
            totals["tool_calls"] += parsed["tool_calls"]
            add_tokens(totals["tokens"], parsed["tokens"])
            if aborted:
                # SAIA outage: the run only measures the outage — stop paying for
                # failed attempts; invalid, retried after the health gate opens.
                result["flags"].append(f"provider_outage_p{i}")
                result["invalid"] = True
                result["abort_reason"] = aborted
                break
            if timed_out:
                result["flags"].append(f"timeout_p{i}")
                break
            if stalled:
                break
            if code != 0:
                result["flags"].append(f"exit_{code}_p{i}")
                break
        summary = gw.finish(run_id)
        result["gateway"] = summary
        if adapter.name == "opencode":
            usage = adapter.usage(ctx, session_ids)
            if usage:
                result["db_usage"] = usage
        result["session_ids"] = session_ids
        result["flags"] += adapter.flags(ctx, result["phases"])

        if ctx.kind == "deepswe":
            import deepswe
            col = deepswe.collect(ex, task, run_dir)
            result["collect"] = col
            ex.remove()
            ev = deepswe.grade(task, run_dir / "model.patch", run_dir, "verifier", defaults)
            wt = run_dir / "worktree.patch"
            mp = run_dir / "model.patch"
            if wt.exists() and wt.stat().st_size and wt.read_bytes() != mp.read_bytes():
                ev["reward_worktree"] = deepswe.grade(task, wt, run_dir, "verifier_worktree",
                                                      defaults).get("reward")
            else:
                ev["reward_worktree"] = ev.get("reward")
            if col.get("collect_exit") not in (0, None):
                result["flags"].append("collect_failed")
            if (col.get("diagnostics") or {}).get("uncommitted"):
                result["flags"].append("uncommitted_changes")
            if (col.get("diagnostics") or {}).get("commits_not_on_head"):
                result["flags"].append("commits_not_on_head")
            if ev.get("verifier_crash"):
                result["flags"].append("verifier_crash")
                result["invalid"] = True
        else:
            archived = run_dir / "workspace"
            ex.copy_out(ex.workdir + ("/." if ex.kind == "docker" else ""), archived)
            shutil.rmtree(archived / ".git", ignore_errors=True)
            ex.remove()
            ev = evaluate(task, archived, run_dir, defaults["eval_timeout_s"])
        result["eval"] = ev
        if ev.get("eval_timed_out"):
            result["flags"].append("eval_timeout")
    except Exception as exc:
        result["flags"].append("harness_error")
        result["invalid"] = True
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        log(f"ERROR {run_id}: {result['error']}")
        result.setdefault("eval", {"passed": 0, "tests_total": 0, "ran": False,
                                   "eval_timed_out": False})
    finally:
        if summary is None:
            summary = gw.finish(run_id)
            result["gateway"] = summary
        ex.remove(keep=getattr(args, "keep_workspace", False))
    classify_gateway(summary, result["phases"], result)
    result["totals"] = totals
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["wall_s"] = round(sum(p["wall_s"] for p in result["phases"]), 1)
    result["budget_after"] = read_budget()
    return finish_result(run_dir, result, totals)


# ---------------------------------------------------------------- commands

def resolve_combos(args, matrix):
    defaults = matrix["defaults"]
    if getattr(args, "harness", None):
        name = f"{args.harness}-adhoc"
        return {name: {"agent": args.harness, "model": args.model or defaults.get("model")}}
    if args.agent:
        if not args.model:
            sys.exit("--agent requires --model (or use --combo)")
        model = qualify_model(args.model, defaults["provider"])
        models = {args.agent: model}
        if args.agent == "solo":
            models["debugger"] = defaults["solo_validator_model"]
        name = f"{args.agent}@{args.model}"
        return {name: {"phases": [{"agent": args.agent}], "models": models}}
    combos = matrix["combos"]
    if args.combo:
        unknown = [c for c in args.combo if c not in combos]
        if unknown:
            sys.exit(f"unknown combo(s): {unknown}; available: {list(combos)}")
        return {c: combos[c] for c in args.combo}
    return {name: c for name, c in combos.items() if not c.get("retired")}


def select_tasks(args, tasks):
    if args.task:
        unknown = [t for t in args.task if t not in tasks]
        if unknown:
            sys.exit(f"unknown task(s): {unknown}; available: {list(tasks)}")
        return [tasks[t] for t in args.task]
    if getattr(args, "subset", None):
        return [t for t in tasks.values() if set(t.get("subsets", [])) & set(args.subset)]
    return [t for t in tasks.values() if not t.get("retired")]


def cmd_run(args):
    matrix = load_matrix()
    defaults = matrix["defaults"]
    tasks = load_tasks()
    selected_tasks = select_tasks(args, tasks)
    combos = resolve_combos(args, matrix)

    plan = [(task, name, combo, rep)
            for task in selected_tasks
            for name, combo in combos.items()
            for rep in range(1, args.repeats + 1)]
    log(f"{len(plan)} run(s) planned: tasks={[t['name'] for t in selected_tasks]} "
        f"combos={list(combos)} repeats={args.repeats}")
    RUNS_DIR.mkdir(exist_ok=True)

    needs_docker = any(c.get("agent") and (t["kind"] == "deepswe" or (
        (getattr(args, "executor", None) or defaults.get("executor", "docker")) == "docker"))
        for t, _, c, _ in plan)
    if needs_docker and not args.dry_run:
        if not executors.docker_available():
            sys.exit("ABORT: docker not usable by this user (add it to the docker group: "
                     "sudo usermod -aG docker $USER, then log in again) — or use "
                     "--executor host for in-house tasks")
        removed = executors.gc_containers()
        if removed:
            log(f"removed {len(removed)} orphaned container(s)")
        free = shutil.disk_usage("/var/lib/docker" if Path("/var/lib/docker").exists()
                                 else "/").free / 1e9
        if free < defaults.get("deepswe", {}).get("min_free_gb", 8):
            sys.exit(f"ABORT: only {free:.1f} GB free disk")
        gw_port = int(GatewayClient(defaults).admin.rsplit(":", 1)[1])
        executors.ensure_agent_network(defaults.get("relay_image", "python:3.12"),
                                       ROOT / "saia_gateway.py", host_port=gw_port)

    def cooldown_if_provider_trouble(res):
        """SAIA 5xx bursts and hangs come in waves; pause before the next run
        instead of burning budget on more doomed attempts."""
        seconds = defaults.get("provider_cooldown_s", 600)
        if res and any(f.startswith(("provider_error", "provider_outage", "stalled",
                                     "budget_exhausted"))
                       for f in res["flags"]):
            log(f"provider trouble — cooling down {seconds}s before next run")
            time.sleep(seconds)

    # With multiple SAIA keys runs can each drain their own key. Capped at 4;
    # useful parallelism ≈ number of live keys. DeepSWE containers are capped at
    # 5 GB but use ~0.5-1 GB in practice; deepswe.max_parallel bounds them.
    parallel = max(1, min(getattr(args, "parallel", 1) or 1, 4))
    cap = defaults.get("deepswe", {}).get("max_parallel", 1)
    if parallel > cap and any(t["kind"] == "deepswe" for t in selected_tasks):
        log(f"DeepSWE tasks selected — limiting --parallel to {cap} (memory)")
        parallel = cap
    dispatch_lock = threading.Lock()
    outcomes = []

    def execute(item):
        task, name, combo, rep = item
        with dispatch_lock:
            time.sleep(1.5)  # distinct run-dir timestamps + staggered starts
        try:
            result = do_run(task, name, combo, defaults, rep, args)
            outcomes.append((task, name, combo, rep, result))
            cooldown_if_provider_trouble(result)
        except KeyboardInterrupt:
            raise
        except SystemExit as exc:
            if parallel == 1:
                raise
            log(f"ABORT in run {task['name']}/{name}: {exc}")
        except Exception as exc:
            log(f"ERROR in run {task['name']}/{name}: {exc!r} — continuing")

    if parallel == 1:
        for item in plan:
            execute(item)
    else:
        log(f"running up to {parallel} cells concurrently")
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(execute, plan))
    # Retry loop for runs invalidated by provider trouble (stalls, 5xx).
    # Uses exponential backoff (10min → 30min → 60min) with up to 3
    # attempts, so transient SAIA outages don't permanently crater a run.
    retries = [(t, n, c, rep) for t, n, c, rep, res in outcomes
               if res and res.get("invalid") and "harness_error" not in res["flags"]]
    if retries and not args.dry_run and not args.no_retry:
        max_retries = 3
        backoff = [600, 1800, 3600]  # 10min, 30min, 60min
        for attempt in range(1, max_retries + 1):
            still_invalid = []
            for task, name, combo, rep in retries:
                try:
                    res = do_run(task, name, combo, defaults, rep, args)
                    if res and res.get("invalid"):
                        still_invalid.append((task, name, combo, rep))
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    log(f"ERROR in retry {task['name']}/{name}: {exc!r} — continuing")
                    still_invalid.append((task, name, combo, rep))
            retries = still_invalid
            if not retries:
                break
            if attempt < max_retries:
                cooldown = backoff[attempt - 1]
                log(f"{len(retries)} run(s) still invalid after retry {attempt} — "
                    f"cooling down {cooldown}s before retry {attempt + 1}")
                time.sleep(cooldown)
        if retries:
            labels = [f'{t["name"]}/{n}_r{rep}' for t, n, _, rep in retries]
            log(f"GIVING UP on {len(retries)} run(s) after {max_retries} retries: "
                f"{' | '.join(labels)}")
    if not args.dry_run:
        cmd_report(args)


def expected_models(result):
    return {agent: (model.split("/", 1)[1] if "/" in model else model)
            for agent, model in (result.get("models_config") or {}).items()}


def retro_flags(result, run_dir):
    """Flags for runs recorded before the integrity fixes (2026-10-05)."""
    flags, add = result["flags"], []
    old = result.get("schema", 1) == 1 and not result.get("hardened")
    if result["task"] == "minilang2" and result.get("started_at", "") >= MINILANG2_LEAK_SINCE and old:
        add.append("contaminated_hidden_tests")
    if old:
        for events in sorted(run_dir.glob("events_p*.jsonl")):
            try:
                if HIDDEN_READ_RE.search(events.read_text(errors="replace")):
                    add.append("read_hidden")
                    break
            except OSError:
                pass
    # The SAIA plugin's config hook re-pins agents to its own model list, so
    # combo model overrides silently did not apply (observed all-or-nothing).
    want = expected_models(result)
    by = (result.get("db_usage") or {}).get("by_agent_model") or {}
    for agent, model in want.items():
        msgs = {k.partition("/")[2]: v["messages"] for k, v in by.items()
                if k.partition("/")[0] == agent}
        total = sum(msgs.values())
        if total and (total - msgs.get(model, 0)) / total >= 0.1:
            add.append("model_substituted")
            break
    for f in add:
        if f not in flags:
            flags.append(f)
            result["invalid"] = True


def load_results():
    results = []
    for result_file in sorted(RUNS_DIR.glob("*/result.json")):
        try:
            result = read_json(result_file)
        except ValueError:
            log(f"WARNING: unreadable {result_file}")
            continue
        # Retro-classify runs recorded before provider/budget-error detection.
        for phase in result.get("phases", []):
            for regex, kind in ((PROVIDER_ERROR_RE, "provider_error"),
                                (BUDGET_ERROR_RE, "budget_exhausted")):
                marker = f"{kind}_p{phase['phase']}"
                if (result.get("schema", 1) == 1 and marker not in result["flags"]
                        and any(regex.search(e) for e in phase.get("errors", []))):
                    result["flags"].append(marker)
                    result["invalid"] = True
        retro_flags(result, result_file.parent)
        result.setdefault("agent", "opencode-legacy")
        results.append(result)
    return results


def median(values):
    return round(statistics.median(values), 1) if values else 0


def run_tokens(r):
    """Total tokens: gateway accounting first (all agents, all subagents),
    then the opencode.db aggregate, then the event stream."""
    gw = (r.get("gateway") or {}).get("tokens")
    if gw and any(gw.values()):
        return gw["prompt"] + gw["completion"]
    usage = (r.get("db_usage") or {}).get("by_agent_model")
    if usage:
        return sum(sum(v["tokens"].values()) for v in usage.values())
    return sum(r["totals"]["tokens"].values())


def run_requests(r):
    """LLM requests the agent made (gateway count, else assistant messages
    in opencode.db, else steps)."""
    gw = r.get("gateway")
    if gw and "requests" in gw:
        return gw["requests"]
    usage = (r.get("db_usage") or {}).get("by_agent_model")
    if usage:
        return sum(v["messages"] for v in usage.values())
    return r["totals"]["steps"]


def run_budget_spent(r):
    """Actual SAIA requests charged for this run. Gateway runs: upstream
    attempts (incl. retries and failed requests). Legacy runs: day-bucket
    delta between the budget snapshots taken before and after, summed per key.
    None when unknown."""
    gw = r.get("gateway")
    if gw and "upstream_attempts" in gw:
        return gw["upstream_attempts"]
    if r.get("budget_overlap"):
        return None

    def day_by_key(snapshot):
        if not isinstance(snapshot, dict):
            return {}
        entries = snapshot.get("keys")
        if isinstance(entries, list) and entries:
            return {entry.get("label", i): (entry.get("remaining") or {}).get("day")
                    for i, entry in enumerate(entries)}
        # Full old-format snapshot, or the bare `remaining` dict stored by
        # earlier bench versions.
        remaining = snapshot.get("remaining", snapshot)
        return {"_": remaining.get("day") if isinstance(remaining, dict) else None}

    before, after = day_by_key(r.get("budget_before")), day_by_key(r.get("budget_after"))
    deltas = [b - a for key, b in before.items()
              for a in [after.get(key)]
              if isinstance(b, (int, float)) and isinstance(a, (int, float))
              and 0 <= b - a < 500]
    return int(sum(deltas)) if deltas else None


def select_cell(all_runs):
    """Pick the runs that represent a (task, combo) cell.

    Valid runs → their median. If every run was interrupted (provider outage,
    stall), the best attempt is a LOWER BOUND on capability — the poor ones
    only measured the outage. Returns (runs, lower_bound_flag)."""
    valid = [r for r in all_runs if not r["invalid"]]
    if valid:
        return valid, False
    best = max(all_runs, key=lambda r: r["eval"]["passed"])
    return [best], True


def task_baseline(task, eval_timeout):
    """Hidden-test score of the untouched starter (0 for greenfield tasks):
    any combo scoring at or below this made no useful change."""
    if not (task["dir"] / "starter").is_dir():
        return 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        workspace = tmp / "workspace"
        shutil.copytree(task["dir"] / "starter", workspace)
        run_dir = tmp / "out"
        run_dir.mkdir()
        result = evaluate(task, workspace, run_dir, eval_timeout)
        return result["passed"], result["tests_total"]


def f2p_rate(r):
    ev = r["eval"]
    return (ev.get("f2p_passed") or 0) / ev["f2p_total"] if ev.get("f2p_total") else None


CSV_COLUMNS = ["run_id", "task", "combo", "agent", "model", "executor", "passed",
               "tests_total", "pass_rate", "wall_s", "requests", "budget_spent",
               "upstream_attempts", "tool_calls", "tokens_input", "tokens_output",
               "tokens_reasoning", "tokens_total", "tokens_prompt_gw", "tokens_completion_gw",
               "tokens_cached_gw", "max_prompt_tokens", "ttft_p50_ms", "provider_errors",
               "request_cap_hit", "requested_models", "reward", "reward_worktree", "f2p_passed",
               "f2p_total", "p2p_failed", "partial", "patch_bytes", "patch_files",
               "patch_test_files", "patch_outside_reference", "cost", "invalid", "flags"]


def csv_row(r):
    ev, tot = r["eval"], r["totals"]
    gw = r.get("gateway") or {}
    gwt = gw.get("tokens") or {}
    patch = (r.get("collect") or {}).get("patch") or {}
    tokens = tot["tokens"]
    rate = ev["passed"] / ev["tests_total"] if ev["tests_total"] else 0.0
    spent = run_budget_spent(r)
    causes = gw.get("causes") or {}
    model = r.get("model") or ";".join(sorted(set(expected_models(r).values())))
    return {
        "run_id": r["run_id"], "task": r["task"], "combo": r["combo"],
        "agent": r.get("agent", "opencode-legacy"), "model": model,
        "executor": r.get("executor", "host"), "passed": ev["passed"],
        "tests_total": ev["tests_total"], "pass_rate": round(rate, 3),
        "wall_s": r.get("wall_s", 0), "requests": run_requests(r),
        "budget_spent": "" if spent is None else spent,
        "upstream_attempts": gw.get("upstream_attempts", ""),
        "tool_calls": gw.get("tool_calls", tot["tool_calls"]),
        "tokens_input": tokens["input"], "tokens_output": tokens["output"],
        "tokens_reasoning": tokens["reasoning"], "tokens_total": run_tokens(r),
        "tokens_prompt_gw": gwt.get("prompt", ""), "tokens_completion_gw": gwt.get("completion", ""),
        "tokens_cached_gw": gwt.get("cached", ""), "max_prompt_tokens": gw.get("max_prompt_tokens", ""),
        "ttft_p50_ms": gw.get("ttft_p50_ms") or "",
        "provider_errors": sum(v for k, v in causes.items()
                               if k in UPSTREAM_FAILURE_CAUSES or k.startswith("upstream_5")) if gw else "",
        "request_cap_hit": gw.get("cap_hit", ""),
        "requested_models": ";".join(sorted((gw.get("requested_models") or {}).keys())),
        "reward": ev.get("reward", ""), "reward_worktree": ev.get("reward_worktree", ""),
        "f2p_passed": ev.get("f2p_passed", ""), "f2p_total": ev.get("f2p_total", ""),
        "p2p_failed": ev.get("p2p_failed", ""), "partial": ev.get("partial", ""),
        "patch_bytes": patch.get("bytes", ""), "patch_files": patch.get("files", ""),
        "patch_test_files": patch.get("test_files", ""),
        "patch_outside_reference": patch.get("outside_reference", ""),
        "cost": tot["cost"], "invalid": r["invalid"], "flags": ";".join(r["flags"]),
    }


def cmd_report(args):
    results = load_results()
    if not results:
        log("no results yet")
        return
    csv_path = ROOT / "results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(csv_row(r))

    groups = {}
    for r in results:
        groups.setdefault((r["task"], r["combo"]), []).append(r)

    lines = ["# Testbench report", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
             f"from {len(results)} run(s). Raw data: `results.csv`, `runs/*/result.json`.", "",
             "`*` = every run of this cell was interrupted (provider outage/stall); "
             "the best attempt is shown as a lower bound.", ""]
    tasks_seen = sorted({t for t, _ in groups})
    combos_seen = sorted({c for _, c in groups})
    task_defs = load_tasks()
    defaults = load_matrix()["defaults"]
    lines += agent_section(results, task_defs)

    lines += ["## API requests per task × combo", "",
              "Median SAIA requests actually charged per run (gateway upstream attempts, or "
              "the budget-counter delta for legacy runs; includes failed/5xx requests). "
              "`~N` = LLM-response count fallback when no budget snapshot bracketed the run; "
              "`(i)` = interrupted lower-bound cell.", "",
              "| task | " + " | ".join(combos_seen) + " |",
              "|" + "---|" * (len(combos_seen) + 1)]
    for task in tasks_seen:
        cells = []
        for combo in combos_seen:
            all_runs = groups.get((task, combo))
            if not all_runs:
                cells.append("—")
                continue
            runs, lower_bound = select_cell(all_runs)
            spent = [v for v in (run_budget_spent(r) for r in runs) if v is not None]
            value = (str(int(median(spent))) if spent
                     else f"~{int(median([run_requests(r) for r in runs]))}")
            cells.append(value + (" (i)" if lower_bound else ""))
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    lines.append("")

    for task in tasks_seen:
        lines += [f"## Task: {task}", ""]
        tdef = task_defs.get(task)
        if tdef and tdef["kind"] == "host" and (tdef["dir"] / "starter").is_dir():
            base_passed, base_total = task_baseline(tdef, defaults["eval_timeout_s"])
            lines += [f"Starter baseline (no changes made): {base_passed}/{base_total} — "
                      "combos at or below this accomplished nothing.", ""]
        elif tdef and tdef["kind"] == "deepswe":
            try:
                v = read_json(tdef["dir"] / "validation.json")
                lines += [f"Validation: oracle reward {v['oracle']['reward']}, untouched repo "
                          f"F2P {v['null']['f2p_passed']}/{v['null']['f2p_total']} "
                          f"(P2P {v['null']['p2p_passed']}/{v['null']['p2p_total']}).", ""]
            except (OSError, ValueError, KeyError):
                lines += ["Validation: not run.", ""]
        lines += [
                  "| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |",
                  "|---|---|---|---|---|---|---|---|"]
        rows = []
        for combo in combos_seen:
            all_runs = groups.get((task, combo))
            if not all_runs:
                continue
            runs, lower_bound = select_cell(all_runs)
            passed = median([r["eval"]["passed"] for r in runs])
            total = max(r["eval"]["tests_total"] for r in runs)
            rate = passed / total if total else 0.0
            flags = sorted({f for r in all_runs for f in r["flags"]})
            rows.append((rate, combo, lower_bound, runs, len(all_runs),
                         passed, total, flags))
        for rate, combo, lb, runs, n_all, passed, total, flags in sorted(rows, reverse=True):
            lines.append(
                f"| {combo}{'*' if lb else ''} | {len(runs)}/{n_all} "
                f"| {passed}/{total} | {rate:.0%} "
                f"| {median([r.get('wall_s', 0) for r in runs])} "
                f"| {median([run_requests(r) for r in runs])} "
                f"| {int(median([run_tokens(r) for r in runs]))} "
                f"| {', '.join(flags) or '—'} |")
        lines.append("")

    lines += ["## Overall ranking", "",
              "Mean of per-task median pass rates (only over tasks the combo ran).", "",
              "| rank | combo | mean pass rate | tasks covered |", "|---|---|---|---|"]
    ranking = []
    for combo in combos_seen:
        rates = []
        for task in tasks_seen:
            runs = groups.get((task, combo))
            if not runs:
                continue
            runs, _ = select_cell(runs)
            total = max(r["eval"]["tests_total"] for r in runs)
            rates.append((median([r["eval"]["passed"] for r in runs]) / total)
                         if total else 0.0)
        if rates:
            ranking.append((sum(rates) / len(rates), combo, len(rates)))
    for rank, (rate, combo, covered) in enumerate(sorted(ranking, reverse=True), 1):
        lines.append(f"| {rank} | {combo} | {rate:.0%} | {covered}/{len(tasks_seen)} |")
    lines.append("")

    report_path = ROOT / "report.md"
    report_path.write_text("\n".join(lines))
    log(f"wrote {csv_path} and {report_path}")


def agent_section(results, task_defs):
    """Agent comparison (schema-2 runs through the gateway, one model)."""
    runs = [r for r in results if r.get("schema", 1) >= 2]
    if not runs:
        return []
    out = ["## Agent comparison (gateway runs)", "",
           "All agents run the same pinned model through saia_gateway.py. DeepSWE cells: "
           "reward (median of valid runs) / mean F2P pass fraction / median requests. "
           "In-house cells: hidden-test pass rate / — / median requests. "
           "`inv` = only invalid runs.", ""]
    combos = sorted({r["combo"] for r in runs})
    tasks = sorted({r["task"] for r in runs})
    out += ["| task | " + " | ".join(combos) + " |", "|" + "---|" * (len(combos) + 1)]
    by = {}
    for r in runs:
        by.setdefault((r["task"], r["combo"]), []).append(r)
    for task in tasks:
        cells = []
        for combo in combos:
            cell = by.get((task, combo))
            if not cell:
                cells.append("—")
                continue
            valid = [r for r in cell if not r["invalid"]]
            if not valid:
                cells.append("inv")
                continue
            rate = median([r["eval"]["passed"] / r["eval"]["tests_total"]
                           if r["eval"]["tests_total"] else 0 for r in valid])
            f2p = [x for x in (f2p_rate(r) for r in valid) if x is not None]
            f2p_s = f"{statistics.mean(f2p):.0%}" if f2p else "—"
            cells.append(f"{rate:.0%} / {f2p_s} / {int(median([run_requests(r) for r in valid]))}")
        out.append(f"| {task} | " + " | ".join(cells) + " |")
    out += ["", "| combo | agent | valid/all | mean reward | mean F2P | solves per 1k requests "
                "| median wall s | median prompt tok/request | flags seen |",
            "|---|---|---|---|---|---|---|---|---|"]
    for combo in combos:
        cell = [r for r in runs if r["combo"] == combo]
        valid = [r for r in cell if not r["invalid"]]
        rates = [r["eval"]["passed"] / r["eval"]["tests_total"] if r["eval"]["tests_total"]
                 else 0 for r in valid]
        f2p = [x for x in (f2p_rate(r) for r in valid) if x is not None]
        reqs = sum(run_requests(r) for r in valid)
        ppr = [((r.get("gateway") or {}).get("tokens") or {}).get("prompt", 0) /
               max(1, run_requests(r)) for r in valid]
        flags = sorted({f for r in cell for f in r["flags"]})
        out.append(f"| {combo} | {cell[0].get('agent')} | {len(valid)}/{len(cell)} "
                   f"| {statistics.mean(rates) if rates else 0:.0%} "
                   f"| {statistics.mean(f2p) if f2p else 0:.0%} "
                   f"| {1000 * sum(rates) / reqs if reqs else 0:.1f} "
                   f"| {median([r.get('wall_s', 0) for r in valid])} "
                   f"| {int(median(ppr)) if ppr else 0} | {', '.join(flags) or '—'} |")
    calib = []
    for r in runs:
        tdef = task_defs.get(r["task"]) or {}
        ref = tdef.get("reference_runs") or {}
        if r.get("agent") == "mini" and ref.get("ds_flash_solved_of_4") is not None \
                and not r["invalid"]:
            calib.append(f"| {r['task']} | {r['eval'].get('reward')} | "
                         f"{ref['ds_flash_solved_of_4']}/4 | {run_requests(r)} | "
                         f"{ref.get('ds_flash_median_steps')} |")
    if calib:
        out += ["", "### Calibration: mini-ds vs. published mini-swe-agent + DeepSeek-V4-flash",
                "", "| task | our reward | published solved | our requests | published median steps |",
                "|---|---|---|---|---|"] + sorted(calib)
    return out + [""]


def cmd_list(args):
    tasks = load_tasks()
    matrix = load_matrix()
    print("Tasks:")
    for name, task in tasks.items():
        tag = f"[{task['kind']}{' ' + ','.join(task.get('subsets', [])) if task.get('subsets') else ''}]"
        print(f"  {name:48} {tag:22} {task['description'][:70]}")
    print("\nCombos:")
    for name, combo in matrix["combos"].items():
        if combo.get("agent"):
            what = f"{combo['agent']} @ {combo.get('model', matrix['defaults'].get('model'))}"
        else:
            what = " -> ".join(p["agent"] for p in combo["phases"]) + " (legacy opencode)"
        print(f"  {name:30} [{what}]{' RETIRED' if combo.get('retired') else ''}  "
              f"{combo.get('description', '')[:60]}")
    print(f"\nModels ({len(matrix['models'])}): {', '.join(matrix['models'])}")
    print("\nAd-hoc: bench.py run --agent solo --model <model> [--task <task>]   (legacy opencode)")
    print("        bench.py run --harness aider [--model <model>] [--task <task>]")


def cmd_status(args):
    budget = read_budget()
    if budget:
        view = budget_view(budget)
        print(f"SAIA budget (as of {budget.get('updatedAt')}): ~{view['hour']}/hour "
              f"~{view['day']}/day ~{view['month']}/month across {view['key_count']} key(s)"
              f" ({view['dead_keys']} dead)")
    else:
        print("SAIA budget: unavailable")
    health = GatewayClient(load_matrix()["defaults"]).health()
    print(f"SAIA gateway: {'up, ' + str(len(health['keys'])) + ' key(s), model ' + health['model'] if health else 'DOWN'}")
    results = load_results()
    print(f"Completed runs: {len(results)}")
    counts = {}
    for r in results:
        counts[(r["task"], r["combo"])] = counts.get((r["task"], r["combo"]), 0) + 1
    for (task, combo), n in sorted(counts.items()):
        print(f"  {task:40} x {combo:28} : {n}")


def cmd_import_deepswe(args):
    import deepswe
    subsets = args.subset if args.subset is not None else [] if args.n_tasks else ["smoke", "core"]
    names = deepswe.import_tasks(subsets, args.id or (), args.src,
                                 pin_digest=not args.no_digest,
                                 n_tasks=args.n_tasks, sample_seed=args.sample_seed)
    log(f"imported {len(names)} DeepSWE task(s) into {TASKS_DIR}")


def deepswe_tasks(args):
    tasks = [t for t in load_tasks().values() if t["kind"] == "deepswe"]
    if args.task:
        tasks = [t for t in tasks if t["name"] in args.task or t.get("upstream_task_id") in args.task]
    if not tasks:
        sys.exit("no DeepSWE tasks imported — run bench.py import-deepswe first")
    if not executors.docker_available():
        sys.exit("ABORT: docker not usable by this user (sudo usermod -aG docker $USER)")
    return tasks


def cmd_pull_deepswe(args):
    import deepswe
    for task in deepswe_tasks(args):
        log(f"pulled {deepswe.pull(task)}")


def cmd_validate_deepswe(args):
    import deepswe
    defaults = load_matrix()["defaults"]
    bad = []
    for task in deepswe_tasks(args):
        if deepswe.is_validated(task) and not args.force:
            log(f"{task['name']}: already validated")
            continue
        rec = deepswe.validate(task, defaults)
        log(f"{task['name']}: {'OK' if rec['ok'] else 'FAILED'} oracle={rec['oracle']} "
            f"null={rec['null']}")
        if not rec["ok"]:
            bad.append(task["name"])
    if bad:
        sys.exit(f"validation FAILED for: {', '.join(bad)} — swap in a reserve task")


def cmd_gc(args):
    removed = executors.gc_containers()
    log(f"removed {len(removed)} container(s): {', '.join(removed) or '—'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("gc").set_defaults(func=cmd_gc)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--task", nargs="*", help="task name(s); default all")
    run_parser.add_argument("--subset", nargs="*",
                            help="task subset(s): smoke, core, reserve (DeepSWE), inhouse")
    run_parser.add_argument("--combo", nargs="*", help="combo preset name(s) from matrix.json; default all")
    run_parser.add_argument("--agent", help="ad-hoc legacy opencode: primary agent to run")
    run_parser.add_argument("--model", help="ad-hoc: model for --agent / --harness")
    run_parser.add_argument("--harness", help="ad-hoc agent harness: opencode|aider|mini|"
                                              "openhands|omp|pi|mcode")
    run_parser.add_argument("--executor", choices=["docker", "host"],
                            help="where agent combos run (default from matrix.json; DeepSWE "
                                 "always docker)")
    run_parser.add_argument("--repeats", type=int, default=1)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--no-wait", action="store_true",
                            help="abort instead of waiting when budget is low")
    run_parser.add_argument("--no-retry", action="store_true",
                            help="skip the automatic retry round for invalid runs")
    run_parser.add_argument("--allow-unvalidated", action="store_true",
                            help="run DeepSWE tasks that failed/skipped validate-deepswe")
    run_parser.add_argument("--keep-workspace", action="store_true",
                            help="keep the container / host scratch dir after the run")
    run_parser.add_argument("--parallel", type=int, default=1,
                            help="run up to N cells concurrently (useful N ≈ number of "
                                 "live SAIA keys; DeepSWE always 1)")
    run_parser.set_defaults(func=cmd_run)
    imp = sub.add_parser("import-deepswe")
    imp.add_argument("--subset", nargs="*",
                     help="curated tiers (default: smoke core, or none with --n-tasks)")
    imp.add_argument("--id", nargs="*", help="extra upstream task ids (e.g. reserves)")
    imp.add_argument("--n-tasks", type=int, help="random sample of the full corpus, like "
                     "pier's --n-tasks; tagged subset seed<S>")
    imp.add_argument("--sample-seed", type=int, default=0)
    imp.add_argument("--src", help="local deep-swe clone/extract instead of downloading")
    imp.add_argument("--no-digest", action="store_true", help="don't pin image digests")
    imp.set_defaults(func=cmd_import_deepswe)
    for name, func in (("pull-deepswe", cmd_pull_deepswe),
                       ("validate-deepswe", cmd_validate_deepswe)):
        p = sub.add_parser(name)
        p.add_argument("--task", nargs="*")
        p.add_argument("--force", action="store_true")
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
