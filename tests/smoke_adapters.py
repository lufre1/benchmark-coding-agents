#!/usr/bin/env python3
"""End-to-end adapter smoke test on the host executor: fake LLM <- gateway
<- every agent harness, on the `intervals` task. Zero SAIA requests: the
gateway runs key-less (HOME points at an empty dir) against tests/fake_llm.py.

    python3 tests/smoke_adapters.py [--executor docker] [--task T] [harness ...]

With --executor docker the agents run in containers on a separate test
network (bench-agents-test) whose relay points at the test gateway.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
EXECUTOR = TASK = None
if "--executor" in args:
    i = args.index("--executor"); EXECUTOR = args[i + 1]; del args[i:i + 2]
if "--task" in args:
    i = args.index("--task"); TASK = args[i + 1]; del args[i:i + 2]
EXECUTOR, TASK = EXECUTOR or "host", TASK or "intervals"
HARNESSES = args or ["opencode", "aider", "mini", "openhands", "omp", "pi", "mcode"]


def wait_port(proc):
    line = proc.stdout.readline().strip()
    if not line.isdigit():
        sys.exit(f"helper did not start: {line!r}")
    return int(line)


def main():
    scratch = Path(tempfile.mkdtemp(prefix="bench-smoke-"))
    gw_home = scratch / "gw-home"
    gw_home.mkdir()
    fake = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_llm.py")],
                            stdout=subprocess.PIPE, text=True,
                            env={**os.environ, "FAKE_LOG": str(scratch / "fake.jsonl")})
    fport = wait_port(fake)
    gport = 18787
    gw = subprocess.Popen([sys.executable, str(ROOT / "saia_gateway.py"), "serve",
                           "--listen", f"127.0.0.1:{gport}", "--listen", f"172.17.0.1:{gport}",
                           "--upstream", f"http://127.0.0.1:{fport}/v1",
                           "--state-dir", str(scratch / "gw-state"), "--allow-no-keys"],
                          env={"HOME": str(gw_home), "PATH": os.environ["PATH"]},
                          stderr=open(scratch / "gateway.log", "w"))
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{gport}/_bench/health", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    env = {**os.environ, "BENCH_RUNS_DIR": str(scratch / "runs"),
           "BENCH_GATEWAY": f"http://127.0.0.1:{gport}", "BENCH_WORK_ROOT": str(scratch / "ws"),
           "BENCH_AGENT_NETWORK": "bench-agents-test", "BENCH_RELAY_NAME": "saia-gw-test"}
    rows = []
    try:
        for h in HARNESSES:
            t0 = time.time()
            proc = subprocess.run([sys.executable, str(ROOT / "bench.py"), "run", "--harness", h,
                                   "--executor", EXECUTOR, "--task", TASK, "--no-retry",
                                   "--no-wait"], env=env, capture_output=True, text=True,
                                  timeout=1800)
            (scratch / f"bench-{h}.log").write_text(proc.stdout + proc.stderr)
            results = sorted((scratch / "runs").glob(f"*_{h}-adhoc_r1/result.json"))
            if not results:
                rows.append((h, "NO RESULT", "", "", round(time.time() - t0)))
                continue
            r = json.loads(results[-1].read_text())
            gws = r.get("gateway") or {}
            rows.append((h, "invalid" if r["invalid"] else "valid",
                         f"req={gws.get('requests')} models={gws.get('requested_models')}",
                         ",".join(r["flags"]) + (f" ERR {r.get('error')}" if r.get("error") else ""),
                         round(time.time() - t0)))
    finally:
        gw.terminate()
        fake.terminate()
        if EXECUTOR == "docker":
            subprocess.run(["docker", "rm", "-f", "saia-gw-test"], capture_output=True)
            subprocess.run(["docker", "network", "rm", "bench-agents-test"], capture_output=True)
    for row in rows:
        print(" | ".join(str(c) for c in row))
    print(f"artifacts: {scratch}")


if __name__ == "__main__":
    main()
