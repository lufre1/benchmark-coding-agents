"""Tests for saia_gateway.py against a scripted fake upstream (no SAIA cost).

    python3 -m pytest tests/test_gateway.py -q
"""

import calendar
import gzip
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import saia_gateway as gw  # noqa: E402

KEYS = ["sk-first-key-AAAA", "sk-second-key-BBBB", "sk-third-key-CCCC"]


def sse(obj):
    return ("data: " + json.dumps(obj) + "\n\n").encode()


def chunk(delta=None, finish=None, usage=None, choices=True):
    obj = {"id": "c1", "object": "chat.completion.chunk", "model": "deepseek-v4-flash-0731",
           "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices
           else []}
    if usage:
        obj["usage"] = usage
    return sse(obj)


class FakeUpstream:
    """Each POST pops one scripted behaviour (default: stream_ok)."""

    def __init__(self):
        self.script = []
        self.calls = []
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def send_body(self, code, body, headers=None, ctype="application/json"):
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def stream(self, parts, headers=None, stall_after=None):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                for i, p in enumerate(parts):
                    if stall_after is not None and i == stall_after:
                        time.sleep(3)
                        return
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(p), p))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fake.lock:
                    fake.calls.append({"auth": self.headers.get("Authorization"), "body": body,
                                       "path": self.path})
                    action = fake.script.pop(0) if fake.script else "stream_ok"
                rl = {"x-ratelimit-remaining-minute": "29", "x-ratelimit-remaining-hour": "150",
                      "x-ratelimit-remaining-day": "900", "x-ratelimit-remaining-month": "2500",
                      "x-kong-request-id": "kong-1"}
                usage = {"prompt_tokens": 100, "completion_tokens": 7,
                         "prompt_tokens_details": {"cached_tokens": 40}}
                if action == "stream_ok":
                    parts = [chunk({"role": "assistant", "content": "Hel"}),
                             chunk({"content": "lo"}),
                             chunk({"tool_calls": [{"index": 0, "id": "t1", "function": {
                                 "name": "bash", "arguments": "{\"cmd\": \"pytest\"}"}}]}),
                             chunk({}, "tool_calls")]
                    if (body.get("stream_options") or {}).get("include_usage"):
                        parts.append(chunk(usage=usage, choices=False))
                    parts.append(b"data: [DONE]\n\n")
                    return self.stream(parts, rl)
                if action == "json_ok":
                    return self.send_body(200, {"choices": [{"message": {
                        "role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
                        "usage": usage}, rl)
                if action == "401":
                    return self.send_body(401, {"error": "invalid key"})
                if action == "429":
                    return self.send_body(429, {"error": "rate"}, {"ratelimit-reset": "0"})
                if action == "503":
                    return self.send_body(503, {"error": "down"})
                if action == "no_first_byte":
                    return self.stream([chunk({"content": "x"})], rl, stall_after=0)
                if action == "stall_mid":
                    return self.stream([chunk({"content": "x"}), chunk({"content": "y"})], rl,
                                       stall_after=1)
                if action == "trickle":  # alive but ~1 token/s
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        for _ in range(40):
                            p = chunk({"content": "x"})
                            self.wfile.write(b"%x\r\n%s\r\n" % (len(p), p))
                            self.wfile.flush()
                            time.sleep(0.1)
                    except OSError:
                        pass
                    return
                if action == "reject_stream_options":
                    if body.get("stream_options"):
                        return self.send_body(400, {"error": "unknown field stream_options"})
                    return self.stream([chunk({"content": "ok"}), chunk({}, "stop"),
                                        b"data: [DONE]\n\n"], rl)
                raise AssertionError(action)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "auth.json").write_text(json.dumps({"saia-gwdg": {"key": KEYS[0]}}))
        (self.tmp / "keys.json").write_text(json.dumps({"keys": KEYS[1:]}))
        self.patches = {"AUTH_FILE": self.tmp / "auth.json", "KEYS_FILE": self.tmp / "keys.json",
                        "MODELS_CACHE": self.tmp / "models.json", "MIN_INTERVAL_S": 0.0,
                        "HEADERS_TIMEOUT_S": 1, "STREAM_IDLE_S": 1, "EMPTY_200_IDLE_S": 0.5,
                        "RETRY_BACKOFF_S": 0.01, "OUTAGE_PAUSE_S": 0.01}
        self.saved = {k: getattr(gw, k) for k in self.patches}
        for k, v in self.patches.items():
            setattr(gw, k, v)
        self.up = FakeUpstream()
        args = SimpleNamespace(upstream=self.up.url, model="deepseek-v4-flash-0731",
                               state_dir=str(self.tmp / "state"), inject_usage=True,
                               allow_no_keys=False, verbose=False)
        self.gateway = gw.Gateway(args)
        self.srv = gw.Server(("127.0.0.1", 0), gw.make_handler(self.gateway))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.up.srv.shutdown()
        for k, v in self.saved.items():
            setattr(gw, k, v)

    # -- helpers
    def call(self, method, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request(method, path, body=json.dumps(payload) if payload is not None else None,
                     headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def register(self, run_id="r1", **spec):
        resp, data = self.call("POST", "/_bench/runs",
                               {"run_id": run_id, "log_dir": str(self.tmp / run_id), **spec})
        self.assertEqual(resp.status, 200, data)
        return json.loads(data)["token"]

    def chat(self, token, stream=True, **extra):
        return self.call("POST", "/v1/chat/completions",
                         {"model": "gpt-whatever", "stream": stream,
                          "messages": [{"role": "user", "content": "hi"}], **extra}, token)

    def summary(self, run_id="r1"):
        # counters are recorded just after the response is sent: wait for idle
        for _ in range(100):
            s = json.loads(self.call("GET", f"/_bench/runs/{run_id}")[1])
            if not s.get("inflight"):
                return s
            time.sleep(0.02)
        return s

    # -- tests
    def test_stream_passthrough_pins_model_and_meters(self):
        token = self.register()
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.assertIsNone(resp.getheader("x-ratelimit-remaining-hour"))
        text = data.decode()
        self.assertIn('"Hel"', text)
        self.assertIn("[DONE]", text)
        self.assertNotIn('"usage"', text, "injected usage-only chunk must not reach the client")
        sent = self.up.calls[0]
        self.assertEqual(sent["body"]["model"], "deepseek-v4-flash-0731")
        self.assertIn(sent["auth"], [f"Bearer {k}" for k in KEYS])
        self.assertNotIn(token, sent["auth"])
        s = self.summary()
        self.assertEqual(s["requests"], 1)
        self.assertEqual(s["tokens"]["prompt"], 100)
        self.assertEqual(s["tokens"]["cached"], 40)
        self.assertEqual(s["tool_calls"], 1)
        self.assertEqual(s["requested_models"], {"gpt-whatever": 1})
        rec = json.loads((self.tmp / "r1/gateway.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["requested_model"], "gpt-whatever")
        self.assertEqual(rec["finish_reason"], "tool_calls")
        self.assertIsNotNone(rec["ttft_ms"])
        with gzip.open(self.tmp / "r1/gw_transcript.jsonl.gz", "rt") as f:
            entry = json.loads(f.readline())
        self.assertEqual(entry["response"]["tool_calls"][0]["name"], "bash")
        self.assertIn("pytest", entry["response"]["tool_calls"][0]["arguments"])

    def test_client_requested_usage_is_forwarded(self):
        token = self.register()
        _, data = self.chat(token, stream_options={"include_usage": True})
        self.assertIn('"usage"', data.decode())

    def test_nonstream_json(self):
        token = self.register()
        self.up.script = ["json_ok"]
        resp, data = self.chat(token, stream=False)
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["choices"][0]["message"]["content"], "hi")
        self.assertEqual(self.summary()["tokens"]["completion"], 7)

    def test_dead_key_fails_over_and_is_persisted(self):
        token = self.register()
        self.up.script = ["401", "stream_ok"]
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 200)
        dead_auth = self.up.calls[0]["auth"]
        self.assertNotEqual(self.up.calls[1]["auth"], dead_auth)
        budget = json.loads((self.tmp / "state/budget.json").read_text())
        self.assertEqual(sum(1 for k in budget["keys"] if k["dead"]), 1)
        self.assertNotIn(KEYS[0], json.dumps(budget))
        self.assertTrue(all("…" in k["label"] for k in budget["keys"]))
        # the dead key never comes back
        self.chat(token)
        self.assertNotEqual(self.up.calls[2]["auth"], dead_auth)

    def test_429_waits_then_retries_same_key(self):
        token = self.register()
        self.up.script = ["429", "stream_ok"]
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.up.calls[0]["auth"], self.up.calls[1]["auth"])

    def test_double_429_fails_over_then_gives_up(self):
        token = self.register()
        self.up.script = ["429", "429", "stream_ok"]
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.assertNotEqual(self.up.calls[1]["auth"], self.up.calls[2]["auth"])
        self.up.script = ["429", "429", "429"]
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 429)
        self.assertIn("rate_limited", data.decode())

    def test_5xx_retried_transparently_then_surfaced(self):
        token = self.register()
        self.up.script = ["503", "503", "stream_ok"]
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.up.script = ["503", "503", "503"]
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 503)
        self.assertEqual(self.summary()["upstream_attempts"], 6)

    def test_request_cap(self):
        token = self.register(cap=2)
        for _ in range(2):
            self.assertEqual(self.chat(token)[0].status, 200)
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 400)
        self.assertIn("request_cap", data.decode())
        self.assertEqual(len(self.up.calls), 2, "capped request must not reach SAIA")
        s = self.summary()
        self.assertTrue(s["cap_hit"])
        self.assertEqual(s["upstream_attempts"], 2)

    def test_unknown_token_rejected(self):
        self.assertEqual(self.chat("bench-nope")[0].status, 401)
        self.assertEqual(self.up.calls, [])

    def test_no_first_byte_is_retried_invisibly(self):
        token = self.register()
        self.up.script = ["no_first_byte", "stream_ok"]
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.assertIn('"Hel"', data.decode())
        self.assertEqual(len(self.up.calls), 2)

    def test_mid_stream_stall_ends_with_error_event(self):
        token = self.register()
        self.up.script = ["stall_mid"]
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 200)
        self.assertIn("stream_idle_timeout", data.decode())
        self.assertEqual(self.summary()["causes"], {"stream_idle_timeout": 1})

    def test_stream_options_rejection_disables_injection(self):
        token = self.register()
        self.up.script = ["reject_stream_options", "reject_stream_options"]
        resp, data = self.chat(token)
        self.assertEqual(resp.status, 200, data)
        self.assertFalse(self.gateway.inject_usage)
        self.assertNotIn("stream_options", self.up.calls[1]["body"])

    def test_fault_injection_never_touches_upstream(self):
        token = self.register(faults={"seed": 1, "p429": 1.0})
        resp, _ = self.chat(token)
        self.assertEqual(resp.status, 429)
        self.assertEqual(self.up.calls, [])
        self.assertEqual(self.summary()["faults_injected"], 1)

    def test_canary_detection(self):
        token = self.register(canaries=["CANARY-42"])
        self.call("POST", "/v1/chat/completions", {"model": "m", "stream": True, "messages": [
            {"role": "tool", "content": "cat /opt/solution.patch\nCANARY-42"}]}, token)
        self.assertEqual(self.summary()["canary_hits"], 1)

    def test_slow_trickle_stream_is_aborted(self):
        gw.SLOW_STREAM_AFTER_S, gw.SLOW_STREAM_MIN_BPS = 0.5, 100_000
        try:
            token = self.register()
            self.up.script = ["trickle"]
            resp, data = self.chat(token)
            self.assertIn("stream_too_slow", data.decode())
            self.assertEqual(self.summary()["causes"], {"stream_too_slow": 1})
        finally:
            gw.SLOW_STREAM_AFTER_S, gw.SLOW_STREAM_MIN_BPS = 120, 1000

    def test_counters_rebuilt_from_log_after_restart(self):
        token = self.register()
        self.up.script = ["stream_ok", "503", "stream_ok"]
        self.chat(token)
        self.chat(token)
        before = self.summary()
        again = gw.Registry(self.tmp / "state")   # what a restarted gateway loads
        after = again.by_token[token].summary()
        for k in ("requests", "upstream_attempts", "tokens", "status", "tool_calls",
                  "requested_models"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(again.by_token[token].seq, 2)

    def test_forced_params_override_and_strip(self):
        token = self.register(params={"reasoning_effort": "high", "temperature": None})
        self.chat(token, reasoning_effort="medium", temperature=0.7)
        sent = self.up.calls[0]["body"]
        self.assertEqual(sent["reasoning_effort"], "high")
        self.assertNotIn("temperature", sent)
        self.summary()  # the log line is written after the response is sent
        rec = json.loads((self.tmp / "r1/gateway.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["requested_params"], {"reasoning_effort": "medium",
                                                   "temperature": 0.7})
        self.assertEqual(rec["params"]["reasoning_effort"], "high")
        self.chat(token)  # agent sent no effort at all -> still forced
        self.assertEqual(self.up.calls[1]["body"]["reasoning_effort"], "high")

    def test_models_answered_locally(self):
        token = self.register()
        resp, data = self.call("GET", "/v1/models", token=token)
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["data"][0]["id"], "deepseek-v4-flash-0731")
        self.assertEqual(self.up.calls, [])

    def test_finish_writes_summary_and_revokes_token(self):
        token = self.register()
        self.chat(token)
        resp, data = self.call("DELETE", "/_bench/runs/r1")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads((self.tmp / "r1/gateway_summary.json").read_text())
                         ["requests"], 1)
        self.assertEqual(self.chat(token)[0].status, 401)

    def test_registry_survives_restart(self):
        token = self.register()
        again = gw.Registry(self.tmp / "state")
        self.assertIn(token, again.by_token)


class ResetWindows(unittest.TestCase):
    def test_buckets_reset_at_the_next_utc_window(self):
        def ms(s):
            return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M")) * 1000
        oct20 = ms("2026-10-20 12:00")
        self.assertFalse(gw.reset_passed("month", oct20, ms("2026-10-31 23:00") / 1000))
        self.assertTrue(gw.reset_passed("month", oct20, ms("2026-11-01 00:30") / 1000))
        self.assertFalse(gw.reset_passed("day", oct20, oct20 / 1000 + 3600))
        self.assertTrue(gw.reset_passed("day", ms("2026-10-06 23:50"), ms("2026-10-07 00:10") / 1000))
        self.assertFalse(gw.reset_passed("hour", oct20, ms("2026-10-20 12:59") / 1000))
        self.assertTrue(gw.reset_passed("hour", oct20, ms("2026-10-20 13:00") / 1000))


if __name__ == "__main__":
    unittest.main()
