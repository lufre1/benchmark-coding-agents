"""Unit tests for bench.py / agents.py / executors.py (no SAIA, no docker).

    python3 -m pytest tests/ -q
"""

import io
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agents  # noqa: E402
import bench  # noqa: E402
import deepswe  # noqa: E402
import executors  # noqa: E402


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class EvaluateHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.task_dir = self.tmp / "task"
        (self.task_dir / "hidden_tests").mkdir(parents=True)
        (self.task_dir / "hidden_tests/test_mod.py").write_text(
            "import mod, helper\n\ndef test_answer():\n    assert mod.answer() == 42\n")
        (self.task_dir / "hidden_tests/helper.py").write_text("X = 1\n")
        # a leaked solution next to the hidden tests must never be imported
        (self.task_dir / "hidden_tests/mod.py").write_text("def answer():\n    return 42\n")
        self.task = {"dir": self.task_dir, "expects": ["mod.py"]}
        self.ws = self.tmp / "ws"
        self.ws.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def score(self):
        ev = bench.evaluate(self.task, self.ws, self.out, 120)
        return ev["passed"], ev["tests_total"], ev

    def test_leaked_hidden_solution_is_not_used(self):
        passed, total, ev = self.score()
        self.assertEqual(passed, 0)
        self.assertEqual(ev["expected_missing"], ["mod.py"])

    def test_agent_solution_counts(self):
        (self.ws / "mod.py").write_text("def answer():\n    return 42\n")
        self.assertEqual(self.score()[:2], (1, 1))

    def test_conftest_and_ini_hijack_stripped(self):
        (self.ws / "mod.py").write_text("def answer():\n    return 0\n")
        (self.ws / "conftest.py").write_text(
            "import pytest\n@pytest.hookimpl(hookwrapper=True)\n"
            "def pytest_runtest_makereport(item, call):\n"
            "    o = yield\n    o.get_result().outcome = 'passed'\n")
        (self.ws / "pytest.ini").write_text("[pytest]\naddopts = -p no:junitxml\n")
        passed, total, ev = self.score()
        self.assertEqual((passed, total), (0, 1))
        self.assertEqual(sorted(ev["eval_stripped"]), ["conftest.py", "pytest.ini"])

    def test_workspace_cannot_shadow_hidden_helper(self):
        (self.ws / "mod.py").write_text("import helper\ndef answer():\n    return 42 * helper.X\n")
        (self.ws / "helper.py").write_text("X = 0\n")
        self.assertEqual(self.score()[:2], (1, 1))


class BudgetMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (bench.BUDGET_FILE, bench.GATEWAY_BUDGET_FILE, bench.KEYS_FILE,
                      bench.AUTH_FILE)
        bench.BUDGET_FILE = self.tmp / "plugin.json"
        bench.GATEWAY_BUDGET_FILE = self.tmp / "gateway.json"
        bench.KEYS_FILE = self.tmp / "keys.json"
        bench.AUTH_FILE = self.tmp / "auth.json"
        bench.AUTH_FILE.write_text(json.dumps({"saia-gwdg": {"key": "z"}}))
        bench.KEYS_FILE.write_text(json.dumps({"keys": ["a", "b"]}))  # 3 keys in rotation

    def tearDown(self):
        bench.BUDGET_FILE, bench.GATEWAY_BUDGET_FILE, bench.KEYS_FILE, bench.AUTH_FILE = self.saved
        shutil.rmtree(self.tmp)

    def test_freshest_entry_wins_and_dead_keys_count_zero(self):
        now = datetime.now(timezone.utc)
        old, new = iso(now - timedelta(minutes=30)), iso(now - timedelta(minutes=1))
        rem = lambda h: {"minute": 20, "hour": h, "day": 500, "month": 2000}  # noqa: E731
        bench.BUDGET_FILE.write_text(json.dumps({"updatedAt": old, "keys": [
            {"label": "key1(…aaaa)", "updatedAt": old, "remaining": rem(150)},
            {"label": "key2(…bbbb)", "updatedAt": old, "remaining": rem(150)}]}))
        bench.GATEWAY_BUDGET_FILE.write_text(json.dumps({"updatedAt": new, "keys": [
            {"label": "key1(…aaaa)", "updatedAt": new, "remaining": rem(10), "dead": True},
            {"label": "key2(…bbbb)", "updatedAt": new, "remaining": rem(90)}]}))
        view = bench.budget_view(bench.read_budget())
        # key1 dead (0) + key2 freshest (90) + unlisted third key full (200)
        self.assertEqual(view["hour"], 90 + 200)
        self.assertEqual(view["dead_keys"], 1)

    def test_exhausted_bucket_counts_empty_until_ttl(self):
        now = datetime.now(timezone.utc)
        stamp = int(now.timestamp() * 1000) - 60_000
        bench.GATEWAY_BUDGET_FILE.write_text(json.dumps({"updatedAt": iso(now), "keys": [
            {"label": "k1", "updatedAt": iso(now), "remaining": {"hour": None},
             "exhausted": {"hour": stamp, "day": 0, "month": 0}}]}))
        bench.KEYS_FILE.write_text(json.dumps({"keys": []}))
        self.assertEqual(bench.budget_view(bench.read_budget())["hour"], 0)

    def test_same_key_under_different_labels_counts_once(self):
        now = iso(datetime.now(timezone.utc))
        rem = {"minute": 20, "hour": 100, "day": 400, "month": 1500}
        bench.BUDGET_FILE.write_text(json.dumps({"updatedAt": now, "keys": [  # plugin numbering
            {"label": "key1(…bbbb)", "updatedAt": now, "remaining": rem},
            {"label": "key2(…aaaa)", "updatedAt": None, "remaining": {}}]}))
        bench.GATEWAY_BUDGET_FILE.write_text(json.dumps({"updatedAt": now, "keys": [
            {"label": "key1(…aaaa)", "updatedAt": now, "remaining": rem},
            {"label": "key2(…bbbb)", "updatedAt": now, "remaining": rem}]}))
        bench.KEYS_FILE.write_text(json.dumps({"keys": ["b"]}))  # 2 keys in rotation
        view = bench.budget_view(bench.read_budget())
        self.assertEqual((view["key_count"], view["month"]), (2, 3000))

    def test_auth_key_listed_as_extra_counts_once(self):
        bench.KEYS_FILE.write_text(json.dumps({"keys": ["z", "a"]}))  # z is the auth key
        self.assertEqual(bench.keyring_size(), 2)

    def test_counts_hold_until_their_utc_window_resets(self):
        now = datetime.now(timezone.utc)
        bench.KEYS_FILE.write_text(json.dumps({"keys": []}))

        def view(updated):
            bench.GATEWAY_BUDGET_FILE.write_text(json.dumps({"updatedAt": iso(updated), "keys": [
                {"label": "k1", "updatedAt": iso(updated),
                 "remaining": {"hour": 5, "day": 50, "month": 100}}]}))
            v = bench.budget_view(bench.read_budget())
            return v["hour"], v["day"], v["month"]

        self.assertEqual(view(now), (5, 50, 100))
        self.assertEqual(view(now - timedelta(days=40)), (200, 1000, 3000))
        old = now - timedelta(hours=3)  # another hour; same day/month unless it crossed one
        self.assertEqual(view(old), (200, 50 if old.date() == now.date() else 1000,
                                     100 if old.month == now.month else 3000))

    def test_gate_waits_for_day_and_month(self):
        now = datetime.now(timezone.utc)
        bench.KEYS_FILE.write_text(json.dumps({"keys": []}))

        def sleep(_):
            raise Waited

        saved, bench.time.sleep = bench.time.sleep, sleep
        try:
            for day, month in ((50, 2000), (500, 100)):  # empty day, then empty month
                bench.GATEWAY_BUDGET_FILE.write_text(json.dumps({"updatedAt": iso(now), "keys": [
                    {"label": "k1", "updatedAt": iso(now),
                     "remaining": {"hour": 150, "day": day, "month": month}}]}))
                with self.assertRaises(Waited):  # waits for the reset, never aborts
                    bench.budget_gate(25, wait=True, run_floor=200)
                with self.assertRaises(SystemExit):  # unless told not to wait
                    bench.budget_gate(25, wait=False, run_floor=200)
        finally:
            bench.time.sleep = saved


class Waited(Exception):
    pass


class CellTries(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved, bench.RUNS_DIR = bench.RUNS_DIR, self.tmp / "runs"

    def tearDown(self):
        bench.RUNS_DIR = self.saved
        shutil.rmtree(self.tmp)

    def result(self, rel, rep, flags=(), invalid=True):
        d = bench.RUNS_DIR / rel
        d.mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({
            "run_id": f"{d.name}_t_c_r{rep}", "task": "t", "combo": "c",
            "invalid": invalid, "flags": list(flags), "gateway": {"requests": 3}}))

    def test_caps_and_archives(self):
        self.result("a", 1, invalid=False)
        for i in range(5):
            self.result(f"b{i}", 2, ["provider_error"])
        self.result("c", 3, ["provider_outage_p1"])
        self.result("d", 3, ["harness_error"])
        self.result("f", 3, ["budget_exhausted", "provider_error"])  # our gateway refused: free
        self.result("_archive/e", 4, invalid=False)  # nested: doesn't count
        plan = [({"name": "t"}, "c", {}, rep) for rep in (1, 2, 3, 4)]
        self.assertEqual([item[3] for item in bench.pending(plan, {"saia_max_tries": 5})], [3, 4])
        self.assertEqual(bench.cell_tries()[("t", "c", 3)], {"valid": False, "saia": 1, "other": 1})

    def test_outage_report(self):
        log = self.tmp / "requests.jsonl"
        ok = {"key": "key2(…aaaa)", "status": 200, "ttfb_ms": 900}
        to = {"key": "key2(…aaaa)", "err": "TimeoutError", "upstream_ms": 45000, "kong": None}
        rows = [{"ts": "2026-10-05T22:10:00Z", "run_id": "x", "attempts": [to, to, ok]}] * 3 + [
            {"ts": "2026-10-05T23:10:00Z", "run_id": "x", "attempts": [ok], "cause":
             "stream_too_slow", "latency_ms": 900000}] * 3 + [
            {"ts": "2026-10-06T09:00:00Z", "run_id": "y", "attempts": [ok]}] * 6
        log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.result("b0", 2, ["provider_error"])
        saved, bench.GATEWAY_REQUESTS_LOG = bench.GATEWAY_REQUESTS_LOG, log
        try:
            bench.outage_report({"health_gate": {"min_ok_ratio": 0.7}, "model": "m"})
        finally:
            bench.GATEWAY_REQUESTS_LOG = saved
        md = (self.tmp / "outages.md").read_text()
        self.assertIn("| 2026-10-05 22:00 | 2026-10-06 00:00 | 15 | 40% |", md)  # 22+23 merged
        self.assertIn("(1/3 measured hours ≥ 70%)", md)
        self.assertIn("b0_t_c_r2", md)
        self.assertEqual(len((self.tmp / "outages.csv").read_text().splitlines()), 1 + 6 + 3)


class RetroFlags(unittest.TestCase):
    def run_dir(self, events=""):
        d = Path(tempfile.mkdtemp())
        (d / "events_p1.jsonl").write_text(events)
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_minilang2_leak_window(self):
        r = {"task": "minilang2", "started_at": "2026-07-21T07:00:00", "flags": [],
             "invalid": False}
        bench.retro_flags(r, self.run_dir())
        self.assertIn("contaminated_hidden_tests", r["flags"])
        self.assertTrue(r["invalid"])
        fresh = {"task": "minilang2", "started_at": "2026-10-06T07:00:00", "flags": [],
                 "invalid": False, "hardened": True}
        bench.retro_flags(fresh, self.run_dir())
        self.assertEqual(fresh["flags"], [])

    def test_read_hidden(self):
        ev = json.dumps({"part": {"tool": "read", "state": {"input": {
            "filePath": "/home/x/bench/tasks/csv-bugfix/hidden_tests/test_x.py"}}}})
        r = {"task": "csv-bugfix", "started_at": "2026-07-14", "flags": [], "invalid": False}
        bench.retro_flags(r, self.run_dir(ev))
        self.assertEqual(r["flags"], ["read_hidden"])

    def test_model_substituted(self):
        r = {"task": "t", "started_at": "2026-07-21", "flags": [], "invalid": False,
             "models_config": {"solo": "saia-gwdg/deepseek-v4-flash"},
             "db_usage": {"by_agent_model": {"solo/qwen3-coder-next": {"messages": 30},
                                             "debugger/qwen3-coder-next": {"messages": 5}}}}
        bench.retro_flags(r, self.run_dir())
        self.assertIn("model_substituted", r["flags"])


class AdapterInvariants(unittest.TestCase):
    """Every harness: gateway URL + pinned model + per-run token, never a key."""

    def ctx(self, kind="deepswe"):
        ex = executors.HostExecutor("t", tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ex.root.parent)
        return agents.RunCtx(run_id="r1", run_dir=Path(ex.root), task={"expects": ["mod.py"]},
                             combo={}, defaults={}, ex=ex, token="bench-TOKEN",
                             gw_url="http://saia-gw:8787/v1", prompt="do the task",
                             request_cap=150, timeout=900, kind=kind)

    def test_argv_and_env(self):
        for name, cls in agents.ADAPTERS.items():
            ctx = self.ctx()
            ad = cls({"phases": [{"agent": "plan"}, {"agent": "build", "prompt": "go"}]})
            for i, phase in enumerate(ad.phases(ctx), 1):
                cmd = ad.build_cmd(ctx, i, phase, {"session_id": "s1"})
                env = cmd.env
                self.assertEqual(env.get("SAIA_API_KEY"), "bench-TOKEN", name)
                blob = json.dumps(cmd.argv) + json.dumps(env)
                self.assertNotIn("academiccloud", blob, name)
                if name not in ("opencode", "omp", "pi", "mcode", "mini"):  # config-file based
                    self.assertIn("saia-gw:8787", blob, name)
                if name not in ("opencode", "mini"):
                    self.assertIn("deepseek-v4-flash-0731", blob, name)

    def test_aider_commits_only_for_deepswe(self):
        ad = agents.AiderAdapter({})
        self.assertIn("--auto-commits", ad.build_cmd(self.ctx("deepswe"), 1, {}, {}).argv)
        host = ad.build_cmd(self.ctx("host"), 1, {}, {}).argv
        self.assertIn("--no-auto-commits", host)
        self.assertIn("mod.py", host)

    def test_opencode_config_isolated(self):
        ctx = self.ctx()
        ad = agents.OpencodeAdapter({"phases": [{"agent": "plan"}, {"agent": "build"}],
                                     "agent_config": {"plan": {"permission": {"edit": "deny"}}}})
        ad.prepare(ctx)
        cfg = json.loads(Path(ad.config_path(ctx)).read_text())
        self.assertNotIn("instructions", cfg)
        self.assertNotIn("plugin", cfg)
        self.assertEqual(cfg["provider"]["saia-gwdg"]["options"]["baseURL"], ctx.gw_url)
        self.assertEqual(cfg["agent"]["plan"]["permission"], {"edit": "deny"})
        self.assertTrue(all(a["model"] == "saia-gwdg/deepseek-v4-flash-0731"
                            for a in cfg["agent"].values()))
        argv = ad.build_cmd(ctx, 2, {"agent": "build"}, {"session_id": "s1"}).argv
        self.assertIn("--pure", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "s1")


class Executors(unittest.TestCase):
    def test_tar_bytes_layout(self):
        raw = executors.tar_bytes({"/agent/prompt.md": ("hi", 0o644),
                                   "/root/.config/x/y.json": (b"{}", 0o600)})
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            names = {m.name: m for m in tar.getmembers()}
        self.assertIn("agent/prompt.md", names)
        self.assertEqual(names["root/.config/x/y.json"].mode, 0o600)
        self.assertTrue(names["root/.config"].isdir())

    def test_host_env_is_allowlisted(self):
        import os
        os.environ["SAIA_API_KEY"] = "sk-real-should-not-leak"
        try:
            env = executors.HostExecutor("t", "/tmp/x").env({"SAIA_API_KEY": "bench-tok"})
        finally:
            del os.environ["SAIA_API_KEY"]
        self.assertEqual(env["SAIA_API_KEY"], "bench-tok")
        self.assertNotIn("sk-real", json.dumps(env))

    def test_docker_exec_argv(self):
        ex = executors.DockerExecutor("r1", "img@sha256:abc")
        cmd = agents.PhaseCmd(["mcode", "exec"], {"SAIA_API_KEY": "bench-tok"},
                              stdin_path="/tmp/p")
        argv, kw = ex.phase_command(cmd)
        self.assertEqual(argv[:3], ["docker", "exec", "-i"])
        self.assertIn("SAIA_API_KEY=bench-tok", argv)
        self.assertTrue(any(a.startswith("PATH=/opt/agents/bin:") for a in argv))
        run = ex.run_argv()
        self.assertIn("--network", run)
        self.assertIn("type=bind,src=" + str(executors.TOOLBOX) + ",dst=/opt/agents,readonly", run)


if __name__ == "__main__":
    unittest.main()


class HealthGate(unittest.TestCase):
    class FakeGw:
        def __init__(self, seq):
            self.seq, self.probes = list(seq), 0

        def health(self):
            st = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
            return {"recent": {"900": st}}

    def run_gate(self, seq, wait=True):
        gw = self.FakeGw(seq)
        saved = (bench.health_probe, bench.time.sleep)
        bench.health_probe = lambda g: setattr(g, "probes", g.probes + 1)
        bench.time.sleep = lambda s: None
        try:
            return bench.health_gate(gw, {}, wait), gw
        finally:
            bench.health_probe, bench.time.sleep = saved

    def test_healthy_opens_without_probe(self):
        st, gw = self.run_gate([{"attempts": 20, "ok_ratio": 0.9}])
        self.assertEqual(gw.probes, 0)

    def test_one_good_probe_is_not_enough(self):
        # decides only on min_attempts (default 6): keeps probing until then
        st, gw = self.run_gate([{"attempts": 0}, {"attempts": 1, "ok_ratio": 1.0},
                                {"attempts": 6, "ok_ratio": 1.0}])
        self.assertEqual((st["attempts"], gw.probes), (6, 2))

    def test_degraded_waits_until_recovered(self):
        bad, good = {"attempts": 30, "ok_ratio": 0.3}, {"attempts": 30, "ok_ratio": 0.8}
        st, gw = self.run_gate([bad, bad, good])
        self.assertEqual(st, good)
        self.assertEqual(gw.probes, 2)

    def test_degraded_no_wait_aborts(self):
        with self.assertRaises(SystemExit):
            self.run_gate([{"attempts": 30, "ok_ratio": 0.2}], wait=False)


class OutageAbort(unittest.TestCase):
    class Gw:
        def __init__(self, st):
            self.st = st

        def health(self):
            return {"recent": {"900": self.st}}

    def test_outage_check(self):
        self.assertIsNone(bench.outage_check(self.Gw({"attempts": 5, "ok_ratio": 0.0}), {}))
        self.assertIsNone(bench.outage_check(self.Gw({"attempts": 30, "ok_ratio": 0.5}), {}))
        self.assertIn("outage", bench.outage_check(self.Gw({"attempts": 30, "ok_ratio": 0.1}), {}))

    def test_run_phase_aborts_and_kills(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        killed = []
        saved = bench.time.monotonic
        start = saved()
        # fast-forward the clock so the 60 s abort poll fires on the first loop
        bench.time.monotonic = lambda: saved() + (0 if saved() - start < 0.1 else 120)
        try:
            code, timed_out, stalled, wall, aborted = bench.run_phase(
                ["sleep", "30"], 600, tmp / "ev", tmp / "err",
                abort=lambda: "SAIA outage", on_kill=lambda: killed.append(1))
        finally:
            bench.time.monotonic = saved
        self.assertEqual(aborted, "SAIA outage")
        self.assertFalse(timed_out or stalled)
        self.assertEqual(killed, [1])


class DeepsweSample(unittest.TestCase):
    def test_sample_ignores_directory_order(self):
        names = [f"t{i:02}" for i in range(30)]
        picks = []
        for order in (names, names[::-1]):
            with tempfile.TemporaryDirectory() as tmp:
                for n in order:
                    (Path(tmp) / n).mkdir()
                    (Path(tmp) / n / "task.toml").write_text("")
                (Path(tmp) / "README.md").write_text("")
                picks.append(deepswe.sample_ids(Path(tmp), 5, 7))
        expected = list(names)
        deepswe.random.Random(7).shuffle(expected)  # pier's algorithm on sorted ids
        self.assertEqual(picks, [expected[:5]] * 2)
