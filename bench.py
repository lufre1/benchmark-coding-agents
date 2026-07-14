#!/usr/bin/env python3
"""opencode model/agent testbench.

Runs coding tasks against (agent, model) combos via headless `opencode run`,
scores each run with a hidden pytest suite, records token/cost metrics, and
generates a comparison report.

Commands:
    bench.py list                       show tasks and combos
    bench.py status                     show SAIA budget and run counts
    bench.py run [options]              run tasks x combos (sequential)
    bench.py report                     write results.csv and report.md

Stdlib only, Python 3.10+.
"""

import argparse
import csv
import json
import os
import re
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
RUNS_DIR = ROOT / "runs"
MATRIX_FILE = ROOT / "matrix.json"
BUDGET_FILE = Path.home() / ".cache/opencode/saia-gwdg-budget.json"
DB_FILE = Path.home() / ".local/share/opencode/opencode.db"
OPENCODE = shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")

FALLBACK_RE = re.compile(r"(?i)agent\b.*\b(not found|unknown|does not exist|falling back|invalid)")

# Provider-side failures (SAIA outages, plugin abort on 5xx bursts): the agent
# was cut off through no fault of its own, so such runs are excluded from
# aggregate scores.
PROVIDER_ERROR_RE = re.compile(r"(?i)5xx|server error|service looks down|overloaded|too many requests")

# Budget exhaustion (pacer floor aborts, "All N SAIA key(s) nearly exhausted"):
# a pacing failure, not an agent failure — the run is invalid and worth
# retrying after a cooldown, same as provider trouble.
BUDGET_ERROR_RE = re.compile(r"(?i)nearly exhausted|budget LOW")

TOKEN_KEYS = ("input", "output", "reasoning", "cache_read", "cache_write")


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
        tasks[task["name"]] = task
    return tasks


def empty_tokens():
    return {k: 0 for k in TOKEN_KEYS}


def add_tokens(total, part):
    for k in TOKEN_KEYS:
        total[k] += part.get(k, 0)


# ---------------------------------------------------------------- budget

def read_budget():
    try:
        return read_json(BUDGET_FILE)
    except (OSError, ValueError):
        return None


BUCKET_LIMITS = {"hour": 200, "day": 1000, "month": 3000}
KEYS_FILE = Path.home() / ".local/share/opencode/saia-gwdg-keys.json"


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
    fresh (<65 min) data counts as full — its buckets have likely reset."""
    entries = snap.get("keys")
    if not isinstance(entries, list) or not entries:
        entries = [{"updatedAt": snap.get("updatedAt"),
                    "remaining": snap.get("remaining")}]
    view = {"hour": 0, "day": 0, "month": 0}
    any_fresh = False
    for entry in entries:
        try:
            updated = datetime.fromisoformat(entry["updatedAt"].replace("Z", "+00:00"))
            fresh = timedelta(0) <= datetime.now(timezone.utc) - updated <= timedelta(minutes=65)
        except (KeyError, TypeError, ValueError, AttributeError):
            fresh = False  # never-used keys have updatedAt: null
        any_fresh = any_fresh or fresh
        remaining = entry.get("remaining") or {}
        for bucket in view:
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
    return view


def budget_gate(floor, wait):
    """Block until the aggregated SAIA hourly request budget (across all
    keys) is above `floor`. Returns the full budget snapshot (or None if
    the budget file is unreadable). Entirely stale data counts as
    replenished."""
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
        log(f"hourly budget ~{view['hour']} across {view['key_count']} key(s) "
            f"< floor {floor}, waiting 2 min ...")
        time.sleep(120)


# ---------------------------------------------------------------- opencode run

def run_phase(cmd, timeout, events_path, stderr_path, stall_timeout=300):
    """Run one opencode invocation.

    Kills the process on overall timeout OR when the event stream makes no
    progress for `stall_timeout` seconds (SAIA sometimes leaves a streaming
    request hanging forever without an error).
    Returns (exit_code, timed_out, stalled, wall_s).
    """
    t0 = time.monotonic()
    timed_out = stalled = False
    with open(events_path, "wb") as out, open(stderr_path, "wb") as err:
        proc = subprocess.Popen(
            cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
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
            if now - t0 >= timeout:
                timed_out = True
            elif now - last_progress >= stall_timeout:
                stalled = True
            else:
                continue
            code = None
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                code = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            break
    return code, timed_out, stalled, round(time.monotonic() - t0, 1)


def parse_events(events_path):
    """Aggregate the NDJSON event stream of one opencode run."""
    agg = {
        "steps": 0,
        "tool_calls": 0,
        "cost": 0.0,
        "tokens": empty_tokens(),
        "session_ids": [],
        "errors": [],
    }
    try:
        lines = Path(events_path).read_text().splitlines()
    except OSError:
        return agg
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        sid = event.get("sessionID")
        if sid and sid not in agg["session_ids"]:
            agg["session_ids"].append(sid)
        etype = event.get("type")
        if etype == "step_finish":
            part = event.get("part") or {}
            agg["steps"] += 1
            agg["cost"] += part.get("cost") or 0
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            add_tokens(agg["tokens"], {
                "input": tokens.get("input") or 0,
                "output": tokens.get("output") or 0,
                "reasoning": tokens.get("reasoning") or 0,
                "cache_read": cache.get("read") or 0,
                "cache_write": cache.get("write") or 0,
            })
        elif etype == "tool_use":
            agg["tool_calls"] += 1
        elif etype == "error":
            agg["errors"].append(str(event.get("error"))[:500])
    agg["cost"] = round(agg["cost"], 6)
    return agg


def db_usage(root_session_ids):
    """Aggregate per-(agent, model) usage from opencode.db, including
    subagent child sessions (session.parent_id). Returns None on failure."""
    if not root_session_ids:
        return None
    try:
        db = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=5)
        try:
            ids = list(dict.fromkeys(root_session_ids))
            frontier = list(ids)
            while frontier:
                marks = ",".join("?" * len(frontier))
                children = [r[0] for r in db.execute(
                    f"SELECT id FROM session WHERE parent_id IN ({marks})", frontier)]
                frontier = [c for c in children if c not in ids]
                ids.extend(frontier)
            marks = ",".join("?" * len(ids))
            usage = {}
            for (data,) in db.execute(
                    f"SELECT data FROM message WHERE session_id IN ({marks})", ids):
                msg = json.loads(data)
                if msg.get("role") != "assistant":
                    continue
                key = f"{msg.get('agent')}/{msg.get('modelID')}"
                entry = usage.setdefault(key, {
                    "messages": 0, "cost": 0.0, "tokens": empty_tokens()})
                entry["messages"] += 1
                entry["cost"] = round(entry["cost"] + (msg.get("cost") or 0), 6)
                tokens = msg.get("tokens") or {}
                cache = tokens.get("cache") or {}
                add_tokens(entry["tokens"], {
                    "input": tokens.get("input") or 0,
                    "output": tokens.get("output") or 0,
                    "reasoning": tokens.get("reasoning") or 0,
                    "cache_read": cache.get("read") or 0,
                    "cache_write": cache.get("write") or 0,
                })
            return {"sessions": len(ids), "by_agent_model": usage}
        finally:
            db.close()
    except Exception as exc:  # locked db, schema drift, ...
        log(f"WARNING: db usage lookup failed: {exc}")
        return None


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
    workspace = Path(workspace).resolve()
    run_dir = Path(run_dir).resolve()
    result = {
        "expected_missing": [f for f in task.get("expects", [])
                             if not (workspace / f).exists()],
        "ran": False, "eval_timed_out": False,
        "tests_total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
    }
    hidden_src = task["dir"] / "hidden_tests"
    hidden_dst = workspace / "hidden_tests"
    shutil.copytree(hidden_src, hidden_dst, dirs_exist_ok=True)
    (hidden_dst / "conftest.py").write_text(EVAL_CONFTEST)
    junit = run_dir / "junit.xml"
    cmd = [sys.executable, "-m", "pytest", "hidden_tests", "-q",
           "-p", "no:cacheprovider", f"--junitxml={junit}"]
    try:
        proc = subprocess.run(cmd, cwd=workspace, timeout=eval_timeout,
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


def do_run(task, combo_name, combo, defaults, repeat, args):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_combo = re.sub(r"[^A-Za-z0-9._@-]", "-", combo_name)
    run_id = f"{timestamp}_{task['name']}_{safe_combo}_r{repeat}"
    run_dir = RUNS_DIR / run_id
    suffix = 2
    while run_dir.exists():  # concurrent runs can share a start second
        run_dir = RUNS_DIR / f"{run_id}_{suffix}"
        suffix += 1
    run_id = run_dir.name
    workspace = run_dir / "workspace"
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
    workspace.mkdir(parents=True)
    starter = task["dir"] / "starter"
    if starter.is_dir():
        shutil.copytree(starter, workspace, dirs_exist_ok=True)
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
        "schema": 1, "run_id": run_id, "task": task["name"],
        "combo": combo_name, "models_config": combo.get("models", {}),
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
        code, timed_out, stalled, wall_s = run_phase(
            cmd, timeout, events_path, stderr_path,
            defaults.get("stall_timeout_s", 300))
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

    usage = db_usage(all_sessions)
    if usage:
        result["db_usage"] = usage
        agents_used = {key.split("/", 1)[0] for key in usage["by_agent_model"]}
        expected = {p["agent"] for p in result["phases"]}
        if not expected & agents_used:
            result["flags"].append("expected_agent_missing_in_db")
            result["invalid"] = True

    result["totals"] = totals
    result["session_ids"] = list(dict.fromkeys(all_sessions))
    result["eval"] = evaluate(task, workspace, run_dir,
                              defaults["eval_timeout_s"])
    if result["eval"]["eval_timed_out"]:
        result["flags"].append("eval_timeout")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["wall_s"] = round(sum(p["wall_s"] for p in result["phases"]), 1)
    result["budget_after"] = read_budget()

    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    ev = result["eval"]
    log(f"DONE {run_id}: {ev['passed']}/{ev['tests_total']} hidden tests, "
        f"{result['wall_s']}s, {totals['steps']} steps, "
        f"{sum(totals['tokens'].values())} tokens"
        f"{' FLAGS: ' + ','.join(result['flags']) if result['flags'] else ''}")
    return result


# ---------------------------------------------------------------- commands

def resolve_combos(args, matrix):
    defaults = matrix["defaults"]
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
    return combos


def cmd_run(args):
    matrix = load_matrix()
    defaults = matrix["defaults"]
    tasks = load_tasks()
    if args.task:
        unknown = [t for t in args.task if t not in tasks]
        if unknown:
            sys.exit(f"unknown task(s): {unknown}; available: {list(tasks)}")
        selected_tasks = [tasks[t] for t in args.task]
    else:
        selected_tasks = list(tasks.values())
    combos = resolve_combos(args, matrix)

    plan = [(task, name, combo, rep)
            for task in selected_tasks
            for name, combo in combos.items()
            for rep in range(1, args.repeats + 1)]
    log(f"{len(plan)} run(s) planned: tasks={[t['name'] for t in selected_tasks]} "
        f"combos={list(combos)} repeats={args.repeats}")
    RUNS_DIR.mkdir(exist_ok=True)

    def cooldown_if_provider_trouble(res):
        """SAIA 5xx bursts and hangs come in waves; pause before the next run
        instead of burning budget on more doomed attempts."""
        seconds = defaults.get("provider_cooldown_s", 600)
        if res and any(f.startswith(("provider_error", "stalled", "budget_exhausted"))
                       for f in res["flags"]):
            log(f"provider trouble — cooling down {seconds}s before next run")
            time.sleep(seconds)

    # With multiple SAIA keys the pacer fails requests over between buckets,
    # so N concurrent runs can each drain their own key. Capped at 4; useful
    # parallelism ≈ number of keys (same-key processes contend on the
    # 30/min bucket and throttle each other via 429s).
    parallel = max(1, min(getattr(args, "parallel", 1) or 1, 4))
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
        log(f"running up to {parallel} cells concurrently "
            f"(per-run budget deltas disabled; request counts come from the DB)")
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(execute, plan))
    # One retry round for runs invalidated by provider trouble (stalls, 5xx).
    retries = [(t, n, c, rep) for t, n, c, rep, res in outcomes
               if res and res.get("invalid")]
    if retries and not args.dry_run and not args.no_retry:
        log(f"retrying {len(retries)} invalid run(s) once ...")
        for task, name, combo, rep in retries:
            try:
                cooldown_if_provider_trouble(
                    do_run(task, name, combo, defaults, rep, args))
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log(f"ERROR in retry {task['name']}/{name}: {exc!r} — continuing")
    if not args.dry_run:
        cmd_report(args)


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
                if (marker not in result["flags"]
                        and any(regex.search(e) for e in phase.get("errors", []))):
                    result["flags"].append(marker)
                    result["invalid"] = True
        results.append(result)
    return results


def median(values):
    return round(statistics.median(values), 1) if values else 0


def run_tokens(r):
    """Total tokens including subagent child sessions (event-stream totals
    only cover the primary session, so prefer the opencode.db aggregate)."""
    usage = (r.get("db_usage") or {}).get("by_agent_model")
    if usage:
        return sum(sum(v["tokens"].values()) for v in usage.values())
    return sum(r["totals"]["tokens"].values())


def run_requests(r):
    """LLM request count including subagents (assistant messages in db)."""
    usage = (r.get("db_usage") or {}).get("by_agent_model")
    if usage:
        return sum(v["messages"] for v in usage.values())
    return r["totals"]["steps"]


def run_budget_spent(r):
    """Actual SAIA requests charged for this run: day-bucket delta between the
    budget snapshots taken before and after, summed per key. Counts failed/5xx
    requests too (they consume budget but never become DB messages). None when
    snapshots are missing or a bucket reset crossed the run."""

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
    import tempfile
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


def cmd_report(args):
    results = load_results()
    if not results:
        log("no results yet")
        return
    csv_path = ROOT / "results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_id", "task", "combo", "passed", "tests_total",
                         "pass_rate", "wall_s", "requests", "budget_spent", "tool_calls",
                         "tokens_input", "tokens_output", "tokens_reasoning",
                         "tokens_total", "cost", "invalid", "flags"])
        for r in results:
            ev, tot = r["eval"], r["totals"]
            tokens = tot["tokens"]
            tokens_total = sum(tokens.values())
            rate = ev["passed"] / ev["tests_total"] if ev["tests_total"] else 0.0
            writer.writerow([
                r["run_id"], r["task"], r["combo"], ev["passed"],
                ev["tests_total"], round(rate, 3), r.get("wall_s", 0),
                run_requests(r), run_budget_spent(r) if run_budget_spent(r) is not None else "",
                tot["tool_calls"], tokens["input"],
                tokens["output"], tokens["reasoning"], run_tokens(r),
                tot["cost"], r["invalid"], ";".join(r["flags"])])

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

    lines += ["## API requests per task × combo", "",
              "Median SAIA requests actually charged per run (budget-counter delta, "
              "includes failed/5xx requests). `~N` = LLM-response count fallback when "
              "no budget snapshot bracketed the run; `(i)` = interrupted lower-bound cell.", "",
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
        if task in task_defs and (task_defs[task]["dir"] / "starter").is_dir():
            base_passed, base_total = task_baseline(task_defs[task],
                                                    defaults["eval_timeout_s"])
            lines += [f"Starter baseline (no changes made): {base_passed}/{base_total} — "
                      "combos at or below this accomplished nothing.", ""]
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


def cmd_list(args):
    tasks = load_tasks()
    matrix = load_matrix()
    print("Tasks:")
    for name, task in tasks.items():
        print(f"  {name:14} {task['description']}")
    print("\nCombos:")
    for name, combo in matrix["combos"].items():
        agents = " -> ".join(p["agent"] for p in combo["phases"])
        print(f"  {name:14} [{agents}]  {combo.get('description', '')}")
    print(f"\nModels ({len(matrix['models'])}): {', '.join(matrix['models'])}")
    print("\nAd-hoc: bench.py run --agent solo --model <model> [--task <task>]")


def cmd_status(args):
    budget = read_budget()
    if budget:
        print(f"SAIA budget (as of {budget.get('updatedAt')}): "
              f"{budget.get('remaining')}")
    else:
        print("SAIA budget: unavailable")
    results = load_results()
    print(f"Completed runs: {len(results)}")
    counts = {}
    for r in results:
        counts[(r["task"], r["combo"])] = counts.get((r["task"], r["combo"]), 0) + 1
    for (task, combo), n in sorted(counts.items()):
        print(f"  {task:14} x {combo:14} : {n}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("report").set_defaults(func=cmd_report)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--task", nargs="*", help="task name(s); default all")
    run_parser.add_argument("--combo", nargs="*", help="combo preset name(s) from matrix.json; default all")
    run_parser.add_argument("--agent", help="ad-hoc: primary agent to run")
    run_parser.add_argument("--model", help="ad-hoc: model for --agent")
    run_parser.add_argument("--repeats", type=int, default=1)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--no-wait", action="store_true",
                            help="abort instead of waiting when budget is low")
    run_parser.add_argument("--no-retry", action="store_true",
                            help="skip the automatic retry round for invalid runs")
    run_parser.add_argument("--parallel", type=int, default=1,
                            help="run up to N cells concurrently (useful N ≈ number of "
                                 "SAIA keys in rotation; disables per-run budget deltas)")
    run_parser.set_defaults(func=cmd_run)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
