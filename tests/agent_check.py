#!/usr/bin/env python3
"""Live configuration + answer check for every benchmarked agent (real SAIA).

For each harness, exactly as in a benchmark run (fresh mars-base container,
toolbox, gateway token, the agent's ~ installer + bench overlay):
  1. inspect the agent's generated config: points at the gateway, pinned
     model, per-run token (never a real SAIA key), no direct SAIA URL;
  2. give it a trivial task: write answer.txt with a random token, commit it,
     reply AGENT-CHECK-DONE;
  3. verify file, commit, final answer (from the gateway transcript, so the
     check is agent-agnostic), exit code, and what the gateway saw (requests,
     failures, requested model, effective request params).

    python3 tests/agent_check.py [harness ...]      # ~2-6 SAIA requests each

Writes runs/_agent-check-<ts>/<agent>/ and report.json there.
"""

import gzip
import json
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402
import executors  # noqa: E402
from agents import RunCtx, make_adapter  # noqa: E402

HARNESSES = {"opencode": "oc-planbuild-ds", "aider": "aider-ds", "mini": "mini-ds",
             "openhands": "openhands-ds", "omp": "omp-ds", "pi": "pi-ds", "mcode": "mcode-ds"}
CONFIG_FILES = {
    "opencode": ["/root/.config/opencode/opencode.json"],
    "aider": ["/root/.aider.conf.yml", "/agent/model-metadata.json"],
    "mini": ["/root/.config/mini-swe-agent/bench.yaml", "/root/.config/mini-swe-agent/.env",
             "/root/.config/mini-swe-agent/mini.yaml"],
    "openhands": ["/root/.openhands/agent_settings.json"],
    "omp": ["/root/.omp/agent/models.yml", "/root/.omp/agent/config.yml",
            "/agent/omp-bench.yml"],
    "pi": ["/root/.pi/agent/models.json", "/root/.pi/agent/settings.json"],
    "mcode": ["/root/.minimax/config.yaml"],
}
DONE = "AGENT-CHECK-DONE"
PROMPT = """This is a short configuration check, not a benchmark task.

1. Create a file named `answer.txt` in the current working directory. It must contain exactly one line with this text: {token}
2. Commit the file with git (commit message: "agent check").
3. Then reply with exactly: {done}
"""
# Without the final literal reply (aider answers in file listings; a trailing
# "reply exactly X" instruction makes the model skip the listing).
PROMPT_FILE_ONLY = """Create a file named `answer.txt` containing exactly one line with this text: {token}
"""
lock = threading.Lock()


def real_keys():
    keys = []
    try:
        keys.append(json.loads(bench.Path.home().joinpath(
            ".local/share/opencode/auth.json").read_text())["saia-gwdg"]["key"])
    except (OSError, ValueError, KeyError):
        pass
    try:
        keys += json.loads(bench.KEYS_FILE.read_text()).get("keys", [])
    except (OSError, ValueError):
        pass
    return [k for k in keys if k]


def say(msg):
    with lock:
        print(f"[check {datetime.now():%H:%M:%S}] {msg}", flush=True)


def check(name, out_root, defaults, matrix, keys):
    combo = matrix["combos"][HARNESSES[name]]
    run_id = f"agentcheck-{datetime.now():%Y%m%dT%H%M%S}-{name}"
    run_dir = out_root / name
    (run_dir / "agent").mkdir(parents=True)
    gw = bench.GatewayClient(defaults)
    token_text = f"BENCH-{secrets.token_hex(6)}"
    prompt = (PROMPT_FILE_ONLY if VARIANT == "file-only" else PROMPT).format(
        token=token_text, done=DONE)
    (run_dir / "prompt.md").write_text(prompt)
    ex = executors.DockerExecutor(run_id, defaults["inhouse_image"], workdir="/app")
    res = {"agent": name, "combo": HARNESSES[name], "checks": {}, "notes": []}
    c = res["checks"]
    params = {**defaults.get("gateway_params", {}), **combo.get("gateway_params", {}),
              **EXTRA_PARAMS}
    reg = gw.register(run_id, run_dir, 30, params=params)
    ctx = RunCtx(run_id=run_id, run_dir=run_dir, task={"expects": [], "prompt": prompt},
                 combo=combo, defaults=defaults, ex=ex, token=reg["token"],
                 gw_url=gw.container_url, prompt=prompt, request_cap=30, timeout=900,
                 kind="deepswe", model=defaults["model"],
                 context_window=defaults["context_window"],
                 max_output=defaults["max_output_tokens"])
    adapter = make_adapter(combo)
    summary = None
    t0 = time.monotonic()
    try:
        ex.start()
        ex.sh("cd /app && git init -q && git commit -q --allow-empty -m init", timeout=60)
        ex.put_files({ctx.prompt_file: (prompt, 0o644)})
        adapter.prepare(ctx)

        # 1. configuration as generated (installer + overlay)
        blob, shown = "", {}
        for path in CONFIG_FILES[name]:
            try:
                text = ex.read_text(path)
            except Exception:
                text = None
            if text is None:
                res["notes"].append(f"config file missing: {path}")
                continue
            blob += text
            shown[path] = text.replace(reg["token"], "<run-token>")
        (run_dir / "config_snapshot.json").write_text(json.dumps(shown, indent=1))
        env = adapter.run_env(ctx)
        c["config_points_at_gateway"] = "saia-gw:8787" in blob or "saia-gw:8787" in json.dumps(env)
        c["config_no_direct_saia"] = "academiccloud" not in blob
        c["config_pinned_model"] = defaults["model"] in blob or defaults["model"] in json.dumps(env)
        c["config_uses_run_token"] = reg["token"] in blob or "SAIA_API_KEY" in blob \
            or env.get("SAIA_API_KEY") == reg["token"]
        c["no_real_key_anywhere"] = not any(k in blob or k in json.dumps(env) for k in keys)
        envdump = ex.sh("env", env=env, timeout=30).stdout
        c["no_real_key_in_agent_env"] = not any(k in envdump for k in keys)

        # 2. the trivial task through real SAIA
        prev, codes = {}, []
        for i, phase in enumerate(adapter.phases(ctx), 1):
            argv, kw = ex.phase_command(adapter.build_cmd(ctx, i, phase, prev))
            code, timed_out, stalled, wall, aborted = bench.run_phase(
                argv, 900, run_dir / f"events_p{i}.jsonl", run_dir / f"stderr_p{i}.log", 300,
                env=kw["env"], cwd=kw["cwd"], stdin_path=kw["stdin_path"],
                activity=lambda: (lambda st: bool(st) and (st.get("inflight", 0) > 0))(
                    gw.status(run_id)),
                on_kill=ex.on_kill)
            parsed = adapter.parse(ctx, i, run_dir / f"events_p{i}.jsonl",
                                   run_dir / f"stderr_p{i}.log")
            if parsed.get("session_ids"):
                prev["session_id"] = parsed["session_ids"][0]
            codes.append(code)
            if timed_out or stalled or aborted:
                res["notes"].append(f"phase {i}: timed_out={timed_out} stalled={stalled} "
                                    f"aborted={aborted}")
                break
        for src, dst in adapter.artifacts(ctx):
            ex.copy_out(src, run_dir / "agent" / dst)
        c["exit_code_0"] = all(code == 0 for code in codes)
        content = ex.sh("cat /app/answer.txt", timeout=30).stdout.strip()
        c["file_correct"] = content == token_text
        if not c["file_correct"]:
            res["notes"].append(f"answer.txt = {content[:80]!r}")
        log = ex.sh("git -C /app log --format=%s", timeout=30).stdout
        status = ex.sh("git -C /app status --porcelain -- answer.txt", timeout=30).stdout
        c["committed"] = "agent check" in log.lower() or (log.count("\n") >= 2 and not status)
    except Exception as exc:
        res["notes"].append(f"harness error: {type(exc).__name__}: {exc}"[:500])
    finally:
        summary = gw.finish(run_id) or {}
        ex.remove()
    res["wall_s"] = round(time.monotonic() - t0)

    # 3. what the gateway saw
    recs = []
    try:
        recs = [json.loads(l) for l in (run_dir / "gateway.jsonl").read_text().splitlines()]
    except OSError:
        pass
    final = ""
    try:
        with gzip.open(run_dir / "gw_transcript.jsonl.gz", "rt") as f:
            entries = [json.loads(l) for l in f]
        final = " ".join((e.get("response") or {}).get("content") or "" for e in entries[-2:])
    except (OSError, EOFError):
        pass
    if VARIANT != "file-only":
        c["final_answer_done"] = DONE in final
    c["got_llm_answers"] = summary.get("ok", 0) > 0
    res["gateway"] = {k: summary.get(k) for k in (
        "requests", "upstream_attempts", "ok", "causes", "requested_models", "tool_calls",
        "max_prompt_tokens", "latency_p50_ms", "cap_hit")}
    res["effective_params"] = sorted({json.dumps(r.get("params"), sort_keys=True)
                                      for r in recs if r.get("params")})
    res["agent_requested_params"] = sorted({json.dumps(r.get("requested_params"), sort_keys=True)
                                           for r in recs if r.get("requested_params")})
    c["effort_and_limit_forced"] = bool(recs) and all(
        (r.get("params") or {}).get("reasoning_effort") == params.get("reasoning_effort")
        for r in recs if r.get("status") == 200)
    res["ok"] = all(v for k, v in c.items())
    say(f"{name:9} {'PASS' if res['ok'] else 'FAIL'} "
        f"({', '.join(k for k, v in c.items() if not v) or 'all checks'}"
        f"{'' if res['ok'] else ' failed'}) {res['wall_s']}s, "
        f"{res['gateway'].get('requests')} requests")
    return res


EXTRA_PARAMS = {}
VARIANT = "full"


def main():
    args = sys.argv[1:]
    # --param key=value forces an extra request param for this check
    # (value "strip" removes the param; JSON values are parsed).
    while "--param" in args:
        i = args.index("--param")
        k, _, v = args[i + 1].partition("=")
        try:
            EXTRA_PARAMS[k] = None if v == "strip" else json.loads(v)
        except ValueError:
            EXTRA_PARAMS[k] = v
        del args[i:i + 2]
    global VARIANT
    if "--file-only" in args:
        args.remove("--file-only")
        VARIANT = "file-only"
    names = args or list(HARNESSES)
    matrix = bench.load_matrix()
    defaults = matrix["defaults"]
    out_root = bench.ROOT / "runs" / f"_agent-check-{datetime.now():%Y%m%dT%H%M%S}"
    out_root.mkdir(parents=True)
    if not executors.docker_available():
        sys.exit("docker not usable")
    executors.ensure_agent_network(defaults["relay_image"], bench.ROOT / "saia_gateway.py")
    gw = bench.GatewayClient(defaults)
    if gw.health() is None:
        sys.exit("gateway down")
    say(f"SAIA health before: {bench.health_gate(gw, defaults, wait=True)}")
    keys = real_keys()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda n: check(n, out_root, defaults, matrix, keys), names))
    (out_root / "report.json").write_text(json.dumps(results, indent=2))
    print(f"\nreport: {out_root / 'report.json'}")


if __name__ == "__main__":
    main()
