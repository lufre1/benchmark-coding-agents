#!/usr/bin/env python3
"""SAIA gateway: one OpenAI-compatible front door for every agent under test.

Every benchmarked agent talks to this gateway instead of SAIA directly, so all
of them get the same transport (pacing, key rotation, 429/5xx handling), the
same pinned model, and identical per-run accounting. Agents only ever see a
per-run token; the real SAIA keys stay in this process.

    saia_gateway.py serve [--listen 127.0.0.1:8787 --listen 172.17.0.1:8787]
    saia_gateway.py relay --listen 0.0.0.0:8787 --to host.docker.internal:8787
    saia_gateway.py probe-context [--admin http://127.0.0.1:8787]

Agent API:   POST /v1/chat/completions (incl. SSE), GET /v1/models
Admin API (loopback clients only):
    POST   /_bench/runs            {run_id, log_dir, cap, faults, canaries, store}
    GET    /_bench/runs/<run_id>   live counters
    DELETE /_bench/runs/<run_id>   finish: writes <log_dir>/gateway_summary.json
    GET    /_bench/health

Pacing/rotation semantics mirror ~/.config/opencode/plugin/saia-gwdg-plugin.js
(>=2.1s between request starts per key, hour/day/month floors 5/10/30, 429 ->
wait ratelimit-reset once then fail over, 401/403 -> key dead). Deliberately
unlike the plugin: no model substitution and no resume-by-injection, so an
agent's own behaviour is what gets measured.

Stdlib only, Python 3.10+.
"""

import argparse
import collections
import gzip
import http.client
import ipaddress
import json
import os
import random
import re
import secrets
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOME = Path.home()
AUTH_FILE = HOME / ".local/share/opencode/auth.json"
KEYS_FILE = HOME / ".local/share/opencode/saia-gwdg-keys.json"
MODELS_CACHE = HOME / ".cache/opencode/saia-gwdg-models.json"
DEFAULT_STATE_DIR = HOME / ".cache/saia-gateway"
DEFAULT_UPSTREAM = "https://chat-ai.academiccloud.de/v1"
DEFAULT_MODEL = "deepseek-v4-flash-0731"

# --- constants mirrored from saia-gwdg-plugin.js
MIN_INTERVAL_S = 2.1
FLOORS = {"hour": 5, "day": 10, "month": 30}
RESET_TTL_S = {"hour": 3600, "day": 86400, "month": 30 * 86400}
BUCKETS = ("minute", "hour", "day", "month")
HEADERS_TIMEOUT_S = 45          # the plugin exempts deepseek from its 20s early-try deadline
MAX_CONNECT_TRIES = 3
RETRY_BACKOFF_S = 5
MAX_CONSECUTIVE_5XX = 3
OUTAGE_PAUSE_S = 30
STREAM_IDLE_S = 90              # SLOW_IDLE_TIMEOUT_MS for silent-paced models
# A replica can keep a stream alive at ~1 token/s (observed 2026-10-05: 210 B/s
# for 28 min), which no idle timer catches. Abort such streams so the agent's
# own retry kicks in — the same transport rule for every agent.
SLOW_STREAM_AFTER_S = 120       # judge throughput only after this long
SLOW_STREAM_MIN_BPS = 1000      # healthy streams run at ~6 KB/s and up
MAX_STREAM_S = 900              # hard cap on one streamed response
EMPTY_200_IDLE_S = 10           # 200 without kong headers = dead replica
MAX_429_WAIT_S = 65
# --- gateway-only
NONSTREAM_BODY_TIMEOUT_S = 600  # whole deepseek generations, not just /models
MAX_5XX_RETRIES = 2             # transparent retries before the first byte
DEFAULT_CAP = 150
TRANSCRIPT_TEXT_CAP = 64_000

STRIP_RESPONSE_HEADERS = {"connection", "keep-alive", "transfer-encoding", "content-length",
                          "content-encoding", "server", "date"}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(msg):
    print(f"[saia-gw {datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def openai_error(message, etype="invalid_request_error", code=None):
    return {"error": {"message": message, "type": etype, "code": code}}


# ---------------------------------------------------------------- keys

def load_keys():
    """auth.json key first, then saia-gwdg-keys.json extras, de-duplicated in
    order: exactly the plugin's rotation order, so labels line up."""
    keys = []
    try:
        key = json.loads(AUTH_FILE.read_text()).get("saia-gwdg", {}).get("key")
        if key:
            keys.append(key)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        extra = json.loads(KEYS_FILE.read_text()).get("keys", [])
        keys += [k for k in extra if isinstance(k, str) and k]
    except (OSError, ValueError, AttributeError):
        pass
    return list(dict.fromkeys(keys))


def reset_passed(bucket, stamp_ms, now):
    """Whether a bucket exhausted at `stamp_ms` has refilled by `now`. The
    month bucket is a calendar month (Kong fixed window, UTC): a key spent on
    the 20th is usable again on the 1st, not 30 days later."""
    if bucket == "month":
        return time.gmtime(stamp_ms / 1000)[:2] != time.gmtime(now)[:2]
    return now * 1000 - stamp_ms >= RESET_TTL_S[bucket] * 1000


class KeyState:
    def __init__(self, key, index):
        self.key = key
        self.label = f"key{index + 1}(…{key[-4:]})"
        self.remaining = {b: None for b in BUCKETS}
        self.exhausted = {"hour": 0, "day": 0, "month": 0}  # epoch ms, like the plugin
        self.updated_at = None
        self.dead = False
        self.next_start = 0.0
        self.last_used = 0.0

    def usable(self, now):
        if self.dead:
            return False
        ok = True
        for b in ("hour", "day", "month"):
            rem = self.remaining.get(b)
            if rem is not None and rem <= FLOORS[b]:
                self.mark_exhausted(b)
            stamp = self.exhausted[b]
            if stamp:
                if not reset_passed(b, stamp, now):
                    ok = False
                else:
                    self.exhausted[b] = 0
        return ok

    def mark_exhausted(self, bucket):
        self.exhausted[bucket] = int(time.time() * 1000)
        self.remaining[bucket] = None

    def snapshot(self):
        return {"label": self.label, "updatedAt": self.updated_at,
                "remaining": dict(self.remaining), "exhausted": dict(self.exhausted),
                "dead": self.dead}


class KeyRing:
    """Least-recently-used key choice (parallel runs spread over keys), with a
    per-key start spacing so the 30/min bucket can never trip."""

    def __init__(self, keys, state_dir):
        self.lock = threading.Lock()
        self.keys = [KeyState(k, i) for i, k in enumerate(keys)]
        self.state_file = Path(state_dir) / "keys_state.json"
        self.budget_file = Path(state_dir) / "budget.json"
        self.consecutive_5xx = 0
        self.outage_until = 0.0
        self._restore()

    def _restore(self):
        try:
            saved = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return
        for ks in self.keys:
            entry = saved.get(ks.label)
            if not entry:
                continue
            ks.dead = bool(entry.get("dead"))
            ks.exhausted.update(entry.get("exhausted") or {})
            ks.remaining.update(entry.get("remaining") or {})
            ks.updated_at = entry.get("updatedAt")

    def persist(self):
        with self.lock:
            snaps = [k.snapshot() for k in self.keys]
        write_json_atomic(self.state_file, {s["label"]: s for s in snaps})
        active = max(self.keys, key=lambda k: k.last_used, default=None)
        write_json_atomic(self.budget_file, {
            "updatedAt": utcnow(), "source": "saia-gateway",
            "activeIndex": self.keys.index(active) if active else 0,
            "remaining": dict(active.remaining) if active else {},
            "keys": snaps})

    def acquire(self, exclude=()):
        """Reserve the next start slot on the best usable key. Returns
        (KeyState, wait_seconds) or (None, 0) when every key is out."""
        with self.lock:
            now = time.time()
            usable = [k for k in self.keys if k not in exclude and k.usable(now)]
            if not usable:
                return None, 0
            ks = min(usable, key=lambda k: (max(k.next_start, now), k.last_used))
            start = max(ks.next_start, now, self.outage_until)
            ks.next_start = start + MIN_INTERVAL_S
            ks.last_used = start
            return ks, start - now

    def observe(self, ks, headers):
        with self.lock:
            seen = False
            for b in BUCKETS:
                v = headers.get(f"x-ratelimit-remaining-{b}")
                if v is not None:
                    try:
                        ks.remaining[b] = int(float(v))
                        seen = True
                    except ValueError:
                        pass
            if seen:
                ks.updated_at = utcnow()

    def mark_dead(self, ks):
        with self.lock:
            ks.dead = True
        log(f"{ks.label} rejected (401/403) — dropped from rotation")

    def mark_exhausted(self, ks, bucket):
        with self.lock:
            ks.mark_exhausted(bucket)
        log(f"{ks.label} exhausted ({bucket} bucket)")

    def record_status(self, status):
        """Global outage detector: 3 consecutive 5xx pause everybody 30s."""
        with self.lock:
            if 500 <= status < 600:
                self.consecutive_5xx += 1
                if self.consecutive_5xx >= MAX_CONSECUTIVE_5XX:
                    self.outage_until = time.time() + OUTAGE_PAUSE_S
                    self.consecutive_5xx = 0
                    log(f"{MAX_CONSECUTIVE_5XX} consecutive 5xx — pausing {OUTAGE_PAUSE_S}s")
            else:
                self.consecutive_5xx = 0

    def describe(self):
        now = time.time()
        with self.lock:
            return [{"label": k.label, "usable": k.usable(now), "dead": k.dead,
                     "remaining": dict(k.remaining), "updatedAt": k.updated_at}
                    for k in self.keys]


# ---------------------------------------------------------------- runs

class Run:
    def __init__(self, run_id, log_dir, cap, faults, canaries, store, params=None):
        self.run_id = run_id
        # Request params forced for every request of this run (same model
        # settings for every agent); a None value strips the param.
        self.params = params or {}
        self.token = "bench-" + secrets.token_urlsafe(24)
        self.log_dir = Path(log_dir) if log_dir else None
        self.cap = cap
        self.faults = faults or {}
        self.canaries = [c for c in (canaries or []) if c]
        self.store = store  # none | delta
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.seq = 0
        self.inflight = 0
        self.created = time.time()
        self.last_activity = time.time()
        self.counters = {
            "requests": 0, "upstream_attempts": 0, "ok": 0, "cap_rejected": 0,
            "status": {}, "causes": {}, "requested_models": {},
            "tokens": {"prompt": 0, "completion": 0, "reasoning": 0, "cached": 0},
            "max_prompt_tokens": 0, "tool_calls": 0, "canary_hits": 0,
            "faults_injected": 0, "ttft_ms": [], "latency_ms": [],
            "last_status": None, "last_cause": None,
        }
        self._prev_messages = []

    def to_state(self):
        return {"run_id": self.run_id, "token": self.token,
                "log_dir": str(self.log_dir) if self.log_dir else None,
                "cap": self.cap, "faults": self.faults, "canaries": self.canaries,
                "store": self.store, "params": self.params, "seq": self.seq,
                "created": self.created,
                "counters": self.counters}

    @classmethod
    def from_state(cls, st):
        run = cls(st["run_id"], st.get("log_dir"), st.get("cap"), st.get("faults"),
                  st.get("canaries"), st.get("store", "delta"), st.get("params"))
        run.token = st["token"]
        run.seq = st.get("seq", 0)
        run.created = st.get("created", time.time())
        run.counters.update(st.get("counters") or {})
        run.replay_log()
        return run

    def record(self, rec):
        """Account one finished request. Used live and when replaying the
        per-run log after a gateway restart (the log is the source of truth)."""
        c = self.counters
        status, cause = rec.get("status"), rec.get("cause")
        c["status"][str(status)] = c["status"].get(str(status), 0) + 1
        if cause:
            c["causes"][cause] = c["causes"].get(cause, 0) + 1
        if status == 200 and not cause:
            c["ok"] += 1
        if cause == "request_cap":
            c["cap_rejected"] += 1
        if rec.get("fault") or cause == "fault_cut":
            c["faults_injected"] += 1
        if "requested_model" in rec:
            key = str(rec.get("requested_model"))
            c["requested_models"][key] = c["requested_models"].get(key, 0) + 1
        if rec.get("canary_hit"):
            c["canary_hits"] += 1
        tok = rec.get("usage") or {}
        for k in c["tokens"]:
            c["tokens"][k] += tok.get(k) or 0
        c["max_prompt_tokens"] = max(c["max_prompt_tokens"], tok.get("prompt") or 0)
        c["tool_calls"] += rec.get("n_tool_calls") or 0
        if rec.get("ttft_ms") is not None:
            c["ttft_ms"].append(rec["ttft_ms"])
        if rec.get("latency_ms") is not None:
            c["latency_ms"].append(rec["latency_ms"])
        c["last_status"], c["last_cause"] = status, cause

    def replay_log(self):
        try:
            lines = (self.log_dir / "gateway.jsonl").read_text().splitlines() \
                if self.log_dir else []
        except OSError:
            return
        recs = []
        for line in lines:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
        recs = [r for r in recs if "seq" in r]
        if not recs:
            return
        self.counters.update({
            "requests": len(recs), "ok": 0, "cap_rejected": 0, "status": {}, "causes": {},
            "requested_models": {}, "tokens": {"prompt": 0, "completion": 0, "reasoning": 0,
                                               "cached": 0},
            "max_prompt_tokens": 0, "tool_calls": 0, "canary_hits": 0, "faults_injected": 0,
            "ttft_ms": [], "latency_ms": [],
            "upstream_attempts": sum(len(r.get("attempts") or []) for r in recs)})
        for r in recs:
            self.record(r)
        self.seq = max(self.seq, max(r["seq"] for r in recs))

    def summary(self):
        with self.lock:
            c = json.loads(json.dumps(self.counters))
            inflight, last = self.inflight, self.last_activity
        ttft, lat = sorted(c.pop("ttft_ms")), sorted(c.pop("latency_ms"))
        c["ttft_p50_ms"] = ttft[len(ttft) // 2] if ttft else None
        c["latency_p50_ms"] = lat[len(lat) // 2] if lat else None
        c.update(run_id=self.run_id, cap=self.cap, params=self.params, inflight=inflight,
                 idle_s=round(time.time() - last, 1), cap_hit=c["cap_rejected"] > 0)
        return c

    def append_log(self, record):
        if not self.log_dir:
            return
        with self.lock, open(self.log_dir / "gateway.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")

    def append_transcript(self, seq, messages, response):
        """Store only messages not already sent in the previous request (the
        common prefix), so a full agent transcript costs ~one copy of it."""
        if self.store == "none" or not self.log_dir:
            return
        with self.lock:
            prev = self._prev_messages
            keep = 0
            while keep < min(len(prev), len(messages)) and prev[keep] == messages[keep]:
                keep += 1
            self._prev_messages = messages
            entry = {"seq": seq, "prefix_kept": keep, "new_messages": messages[keep:],
                     "response": response}
            with gzip.open(self.log_dir / "gw_transcript.jsonl.gz", "at") as f:
                f.write(json.dumps(entry) + "\n")


class Registry:
    def __init__(self, state_dir):
        self.lock = threading.Lock()
        self.path = Path(state_dir) / "runs.json"
        self.by_token, self.by_id = {}, {}
        try:
            for st in json.loads(self.path.read_text()):
                run = Run.from_state(st)
                self.by_token[run.token], self.by_id[run.run_id] = run, run
        except (OSError, ValueError, KeyError):
            pass

    def save(self):
        with self.lock:
            states = [r.to_state() for r in self.by_id.values()]
        write_json_atomic(self.path, states)

    def add(self, run):
        with self.lock:
            old = self.by_id.pop(run.run_id, None)
            if old:
                self.by_token.pop(old.token, None)
            self.by_token[run.token], self.by_id[run.run_id] = run, run
        self.save()

    def remove(self, run_id):
        with self.lock:
            run = self.by_id.pop(run_id, None)
            if run:
                self.by_token.pop(run.token, None)
        self.save()
        return run


# ---------------------------------------------------------------- SSE metering

class StreamMeter:
    """Parses forwarded SSE events: TTFT, usage, finish reason, tool calls,
    and a capped copy of the assistant output for the transcript."""

    def __init__(self, t0, drop_usage_only):
        self.t0 = t0
        self.drop_usage_only = drop_usage_only
        self.ttft_ms = None
        self.usage = None
        self.finish_reason = None
        self.tool_call_ids = set()
        self.text = []
        self.text_len = 0
        self.tool_args = {}

    def feed(self, event_bytes):
        """Returns False when the event should not be forwarded."""
        for line in event_bytes.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            if obj.get("usage"):
                self.usage = obj["usage"]
            choices = obj.get("choices") or []
            if not choices and obj.get("usage") and self.drop_usage_only:
                return False
            for ch in choices:
                delta = ch.get("delta") or {}
                if self.ttft_ms is None and (delta.get("content") or delta.get("tool_calls")
                                             or delta.get("reasoning_content")):
                    self.ttft_ms = int((time.monotonic() - self.t0) * 1000)
                if ch.get("finish_reason"):
                    self.finish_reason = ch["finish_reason"]
                content = delta.get("content")
                if content and self.text_len < TRANSCRIPT_TEXT_CAP:
                    self.text.append(content)
                    self.text_len += len(content)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if tc.get("id"):
                        self.tool_call_ids.add(tc["id"])
                    fn = tc.get("function") or {}
                    slot = self.tool_args.setdefault(idx, {"name": "", "arguments": ""})
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments") and len(slot["arguments"]) < TRANSCRIPT_TEXT_CAP:
                        slot["arguments"] += fn["arguments"]
        return True

    def n_tool_calls(self):
        return max(len(self.tool_call_ids), len(self.tool_args))

    def response(self):
        return {"content": "".join(self.text), "tool_calls": list(self.tool_args.values()),
                "finish_reason": self.finish_reason}


def usage_tokens(usage):
    usage = usage or {}
    details = usage.get("completion_tokens_details") or {}
    pdetails = usage.get("prompt_tokens_details") or {}
    return {"prompt": usage.get("prompt_tokens") or 0,
            "completion": usage.get("completion_tokens") or 0,
            "reasoning": details.get("reasoning_tokens") or 0,
            "cached": pdetails.get("cached_tokens") or 0}


# ---------------------------------------------------------------- gateway

class UpstreamFailure(Exception):
    def __init__(self, cause, status=None, body=b"", headers=None):
        super().__init__(cause)
        self.cause, self.status, self.body, self.headers = cause, status, body, headers or {}


class Gateway:
    def __init__(self, args):
        self.args = args
        self.upstream = urlsplit(args.upstream.rstrip("/"))
        self.model = args.model
        self.state_dir = Path(args.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        keys = load_keys()
        if not keys and not args.allow_no_keys:
            sys.exit("no SAIA keys found (auth.json / saia-gwdg-keys.json)")
        self.ring = KeyRing(keys or ["dummy-key-0000"], self.state_dir)
        self.registry = Registry(self.state_dir)
        self.inject_usage = args.inject_usage
        # (time, ok) per upstream attempt / stream outcome, for the health view
        # bench.py gates new runs on (SAIA degrades for hours at a time).
        self.recent = collections.deque(maxlen=20000)
        self.global_log = self.state_dir / "requests.jsonl"
        self.log_lock = threading.Lock()
        log(f"{len(self.ring.keys)} key(s) in rotation "
            f"({sum(1 for k in self.ring.keys if k.dead)} dead), upstream {args.upstream}, "
            f"model pinned to {self.model}")

    # -- upstream plumbing

    def connect(self, timeout):
        u = self.upstream
        if u.scheme == "https":
            return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                               context=ssl.create_default_context())
        return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)

    def upstream_path(self, suffix):
        return (self.upstream.path or "") + suffix

    def attempt(self, ks, path, body, req_id):
        """One HTTP exchange up to response headers. Returns (conn, resp)."""
        conn = self.connect(HEADERS_TIMEOUT_S)
        conn.request("POST", self.upstream_path(path), body=body, headers={
            "Authorization": f"Bearer {ks.key}", "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json", "x-client-request-id": req_id,
            "User-Agent": "saia-gateway/1"})
        resp = conn.getresponse()
        return conn, resp

    def exchange(self, run, path, body, req_id, rec):
        """Run the plugin's retry/rotation ladder until a response worth
        forwarding (2xx, or a final error). Returns (conn, resp, ks)."""
        tried_dead = set()
        connect_tries = 0
        retries_5xx = 0
        n429 = 0
        ks, wait = self.ring.acquire()
        while True:
            if ks is None:
                raise UpstreamFailure("budget_exhausted", 503)
            if wait > 0:
                rec["queue_ms"] += int(wait * 1000)
                time.sleep(wait)
            t = time.monotonic()
            att = {"key": ks.label}
            rec["attempts"].append(att)
            with run.lock:
                run.counters["upstream_attempts"] += 1
            try:
                conn, resp = self.attempt(ks, path, body, req_id)
            except (OSError, http.client.HTTPException) as exc:
                att.update(err=type(exc).__name__, upstream_ms=int((time.monotonic() - t) * 1000))
                self.recent.append((time.time(), False))
                connect_tries += 1
                if connect_tries >= MAX_CONNECT_TRIES:
                    raise UpstreamFailure("upstream_unreachable" if not isinstance(
                        exc, (TimeoutError, socket.timeout)) else "headers_timeout", 504)
                time.sleep(RETRY_BACKOFF_S)
                ks, wait = self.ring.acquire(exclude=tried_dead)
                continue
            att.update(status=resp.status, ttfb_ms=int((time.monotonic() - t) * 1000),
                       kong=resp.getheader("x-kong-request-id"))
            self.ring.observe(ks, {k.lower(): v for k, v in resp.getheaders()})
            self.ring.record_status(resp.status)
            if resp.status not in (401, 403):
                self.recent.append((time.time(), resp.status == 200))
            if resp.status in (401, 403):
                resp.read()
                conn.close()
                self.ring.mark_dead(ks)
                tried_dead.add(ks)
                self.ring.persist()
                ks, wait = self.ring.acquire(exclude=tried_dead)
                continue
            if resp.status == 429:
                reset = resp.getheader("ratelimit-reset")
                resp.read()
                conn.close()
                n429 += 1
                if n429 == 1:
                    try:
                        delay = min(float(reset or 60), MAX_429_WAIT_S)
                    except ValueError:
                        delay = 60
                    rec["queue_ms"] += int(delay * 1000)
                    time.sleep(delay)
                    wait = 0
                    continue
                if n429 == 2:
                    self.ring.mark_exhausted(ks, "hour")
                    self.ring.persist()
                    ks, wait = self.ring.acquire(exclude=tried_dead | {ks})
                    continue
                raise UpstreamFailure("rate_limited", 429)
            if 500 <= resp.status < 600 and retries_5xx < MAX_5XX_RETRIES:
                resp.read()
                conn.close()
                retries_5xx += 1
                time.sleep(RETRY_BACKOFF_S)
                ks, wait = self.ring.acquire(exclude=tried_dead)
                continue
            return conn, resp, ks

    # -- request handling

    def handle_chat(self, handler, run, raw_body):
        t0 = time.monotonic()
        with run.lock:
            run.seq += 1
            seq = run.seq
            run.counters["requests"] += 1
            run.inflight += 1
            run.last_activity = time.time()
        req_id = f"gw-{run.run_id[-24:]}-{seq}"
        rec = {"ts": utcnow(), "run_id": run.run_id, "seq": seq, "req_id": req_id,
               "attempts": [], "queue_ms": 0, "origin": "upstream"}
        status, cause = 200, None
        try:
            try:
                body = json.loads(raw_body or b"{}")
            except ValueError:
                status, cause = 400, "bad_json"
                return handler.send_json(400, openai_error("request body is not JSON"))
            requested = body.get("model")
            body["model"] = self.model
            overridden = {k: body.get(k) for k in run.params if k in body}
            for k, v in run.params.items():
                if v is None:
                    body.pop(k, None)
                else:
                    body[k] = v
            stream = bool(body.get("stream"))
            injected = False
            if stream and self.inject_usage and not (body.get("stream_options") or {}).get(
                    "include_usage"):
                body["stream_options"] = {**(body.get("stream_options") or {}),
                                          "include_usage": True}
                injected = True
            messages = body.get("messages") or []
            text_blob = json.dumps(messages)
            rec.update(requested_model=requested, stream=stream, msg_count=len(messages),
                       prompt_chars=len(text_blob), params={
                           k: body.get(k) for k in ("temperature", "top_p", "max_tokens",
                                                    "max_completion_tokens", "tool_choice",
                                                    "reasoning_effort")
                           if body.get(k) is not None} | {"tools_n": len(body.get("tools") or [])},
                       requested_params=overridden)
            if any(c in text_blob for c in run.canaries):
                rec["canary_hit"] = True

            if run.cap and seq > run.cap:
                status, cause = 400, "request_cap"
                rec["origin"] = "gateway"
                return handler.send_json(400, openai_error(
                    f"benchmark request cap of {run.cap} LLM requests reached for this run; "
                    "stop and finish now.", code="request_cap"))

            fault = self.pick_fault(run, seq)
            if fault in ("429", "503"):
                status, cause = int(fault), f"fault_{fault}"
                rec.update(origin="gateway", fault=fault)
                headers = {"ratelimit-reset": "5"} if fault == "429" else {}
                return handler.send_json(status, openai_error(
                    "injected fault", "rate_limit_error" if fault == "429" else "server_error"),
                    headers)

            # Transport tries: a stream that never delivers its first byte (dead
            # replica) is retried before the client has seen anything.
            for _ in range(MAX_CONNECT_TRIES):
                try:
                    conn, resp, _ks = self.exchange(run, "/chat/completions",
                                                    json.dumps(body).encode(), req_id, rec)
                except UpstreamFailure as exc:
                    status, cause = exc.status or 502, exc.cause
                    return handler.send_json(status, openai_error(
                        f"SAIA gateway: {exc.cause}", "server_error", exc.cause))
                status = resp.status
                ctype = resp.getheader("content-type") or ""
                try:
                    if status == 400 and injected:
                        err = resp.read()
                        if b"stream_options" in err or b"include_usage" in err:
                            # SAIA rejects the option: turn injection off for good.
                            self.inject_usage = injected = False
                            body.pop("stream_options", None)
                            log("upstream rejected stream_options.include_usage — disabled")
                            continue
                        cause = "upstream_400"
                        return handler.send_raw(status, resp, err)
                    if status == 200 and "text/event-stream" in ctype:
                        first = self.first_chunk(conn, resp)
                        if first is None:
                            rec["attempts"][-1]["err"] = "no_first_byte"
                            cause = "no_first_byte"
                            continue
                        cause = None
                        meter = StreamMeter(t0, drop_usage_only=injected)
                        cause = self.forward_stream(handler, run, conn, resp, meter, fault, first)
                        rec.update(ttft_ms=meter.ttft_ms, finish_reason=meter.finish_reason,
                                   n_tool_calls=meter.n_tool_calls(),
                                   usage=usage_tokens(meter.usage))
                        run.append_transcript(seq, messages, meter.response())
                        return
                    if conn.sock:
                        conn.sock.settimeout(NONSTREAM_BODY_TIMEOUT_S)
                    data = resp.read()
                    if status == 200:
                        self.record_nonstream(run, rec, seq, messages, data)
                    else:
                        cause = f"upstream_{status}"
                    return handler.send_raw(status, resp, data)
                finally:
                    conn.close()
            status = 504
            return handler.send_json(504, openai_error(
                "SAIA gateway: upstream stream never delivered data", "server_error",
                "no_first_byte"))
        except (BrokenPipeError, ConnectionResetError):
            cause = cause or "client_disconnected"
        finally:
            rec.update(status=status, cause=cause,
                       latency_ms=int((time.monotonic() - t0) * 1000))
            if cause in ("no_first_byte", "stream_too_slow", "stream_idle_timeout",
                         "stream_upstream_error"):
                self.recent.append((time.time(), False))
            with run.lock:
                run.record(rec)
                run.inflight -= 1
                run.last_activity = time.time()
            run.append_log(rec)
            with self.log_lock, open(self.global_log, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if rec["attempts"]:
                self.ring.persist()

    def pick_fault(self, run, seq):
        f = run.faults
        if not f:
            return None
        rng = random.Random(f"{f.get('seed', 0)}:{run.run_id}:{seq}")
        x = rng.random()
        if x < f.get("p429", 0):
            return "429"
        if x < f.get("p429", 0) + f.get("p503", 0):
            return "503"
        if x < f.get("p429", 0) + f.get("p503", 0) + f.get("p_cut", 0):
            return "cut"
        return None

    def record_nonstream(self, run, rec, seq, messages, data):
        try:
            obj = json.loads(data)
            choice = (obj.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
        except (ValueError, AttributeError, IndexError):
            return
        ntc = len(msg.get("tool_calls") or [])
        rec.update(usage=usage_tokens(obj.get("usage")), n_tool_calls=ntc,
                   finish_reason=choice.get("finish_reason"))
        run.append_transcript(seq, messages, {
            "content": (msg.get("content") or "")[:TRANSCRIPT_TEXT_CAP],
            "tool_calls": [tc.get("function") for tc in msg.get("tool_calls") or []],
            "finish_reason": rec["finish_reason"]})

    def first_chunk(self, conn, resp):
        """First body bytes of a stream, or None if the replica sends nothing
        (a 200 without kong headers gets the short dead-replica window)."""
        empty_replica = (resp.getheader("x-kong-request-id") is None
                         and resp.getheader("x-kong-upstream-latency") is None
                         and "academiccloud" in (self.upstream.hostname or ""))
        try:
            if conn.sock:
                conn.sock.settimeout(EMPTY_200_IDLE_S if empty_replica else STREAM_IDLE_S)
            return resp.read1(65536) or None
        except (OSError, http.client.HTTPException):
            return None

    def forward_stream(self, handler, run, conn, resp, meter, fault, first):
        """Relay SSE event-by-event. Returns a cause string on abnormal end."""
        handler.send_response(200)
        for k, v in resp.getheaders():
            if k.lower() not in STRIP_RESPONSE_HEADERS and not k.lower().startswith("x-ratelimit"):
                handler.send_header(k, v)
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        buf = b""
        sent = 0
        cut_after = run.faults.get("cut_bytes", 2000) if fault == "cut" else None
        cause = None
        chunk = first
        started = time.monotonic()
        received = 0
        while True:
            elapsed = time.monotonic() - started
            if elapsed > MAX_STREAM_S or (elapsed > SLOW_STREAM_AFTER_S
                                          and received / elapsed < SLOW_STREAM_MIN_BPS):
                cause = "stream_too_slow"
                break
            if chunk is None:
                try:
                    if conn.sock:
                        conn.sock.settimeout(STREAM_IDLE_S)
                    chunk = resp.read1(65536)
                except (TimeoutError, socket.timeout):
                    cause = "stream_idle_timeout"
                    break
                except (OSError, http.client.HTTPException):
                    cause = "stream_upstream_error"
                    break
                if not chunk:
                    break
            received += len(chunk)
            buf += chunk.replace(b"\r\n", b"\n")
            chunk = None
            while b"\n\n" in buf:
                event, buf = buf.split(b"\n\n", 1)
                if not meter.feed(event):
                    continue
                handler.write_chunk(event + b"\n\n")
                sent += len(event) + 2
                if cut_after is not None and sent >= cut_after:
                    handler.close_connection = True
                    return "fault_cut"
                with run.lock:
                    run.last_activity = time.time()
        if buf.strip():
            if meter.feed(buf):
                handler.write_chunk(buf + b"\n\n")
        if cause:
            err = json.dumps(openai_error(f"SAIA gateway: {cause}", "server_error", cause))
            handler.write_chunk(f"event: error\ndata: {err}\n\n".encode())
            handler.close_connection = True
        handler.write_chunk(b"")
        return cause

    def recent_stats(self, window_s):
        cutoff = time.time() - window_s
        hits = [ok for ts, ok in list(self.recent) if ts >= cutoff]
        return {"attempts": len(hits),
                "ok_ratio": round(sum(hits) / len(hits), 3) if hits else None}

    def models_payload(self):
        entry = {"id": self.model, "object": "model", "owned_by": "chat-ai", "status": "ready"}
        try:
            cache = json.loads(MODELS_CACHE.read_text())
            rows = cache.get("data", cache) if isinstance(cache, dict) else cache
            for m in rows if isinstance(rows, list) else []:
                if isinstance(m, dict) and m.get("id") == self.model:
                    entry = m
        except (OSError, ValueError, AttributeError):
            pass
        return {"object": "list", "data": [entry]}


# ---------------------------------------------------------------- HTTP layer

def make_handler(gw):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "saia-gateway/1"

        def log_message(self, fmt, *a):
            if gw.args.verbose:
                log("http: " + fmt % a)

        # -- helpers
        def send_json(self, status, obj, headers=None):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def send_raw(self, status, resp, data):
            self.send_response(status)
            for k, v in resp.getheaders():
                if k.lower() not in STRIP_RESPONSE_HEADERS and not k.lower().startswith(
                        "x-ratelimit"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def write_chunk(self, data):
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        def read_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def is_loopback(self):
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def run_for_request(self):
            auth = self.headers.get("Authorization") or ""
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else \
                (self.headers.get("x-api-key") or self.headers.get("api-key") or "").strip()
            return gw.registry.by_token.get(token)

        # -- routes
        def do_GET(self):
            path = self.path.split("?", 1)[0].rstrip("/")
            if path.startswith("/_bench/"):
                return self.admin_get(path)
            run = self.run_for_request()
            if run is None:
                return self.send_json(401, openai_error("unknown benchmark run token",
                                                        "authentication_error"))
            if path.endswith("/models"):
                return self.send_json(200, gw.models_payload())
            self.send_json(404, openai_error(f"unsupported path {path}"))

        def do_POST(self):
            path = self.path.split("?", 1)[0].rstrip("/")
            raw = self.read_body()
            if path.startswith("/_bench/"):
                return self.admin_post(path, raw)
            run = self.run_for_request()
            if run is None:
                return self.send_json(401, openai_error("unknown benchmark run token",
                                                        "authentication_error"))
            if path.endswith("/chat/completions"):
                return gw.handle_chat(self, run, raw)
            run.append_log({"ts": utcnow(), "run_id": run.run_id, "status": 404,
                            "cause": "unsupported_path", "path": path, "origin": "gateway"})
            self.send_json(404, openai_error(f"unsupported path {path}"))

        def do_DELETE(self):
            path = self.path.split("?", 1)[0].rstrip("/")
            if not self.is_loopback():
                return self.send_json(403, openai_error("admin API is loopback-only"))
            m = re.fullmatch(r"/_bench/runs/([^/]+)", path)
            if not m:
                return self.send_json(404, openai_error("unknown admin path"))
            run = gw.registry.remove(m.group(1))
            if run is None:
                return self.send_json(404, openai_error("unknown run"))
            # The agent may exit the instant its last response ends, before
            # that request's handler has recorded it: wait for in-flight work.
            deadline = time.time() + 15
            while run.inflight > 0 and time.time() < deadline:
                time.sleep(0.05)
            summary = run.summary()
            if run.log_dir:
                write_json_atomic(run.log_dir / "gateway_summary.json", summary)
            self.send_json(200, summary)

        def admin_get(self, path):
            if not self.is_loopback():
                return self.send_json(403, openai_error("admin API is loopback-only"))
            if path == "/_bench/health":
                return self.send_json(200, {"ok": True, "model": gw.model,
                                            "upstream": gw.args.upstream,
                                            "keys": gw.ring.describe(),
                                            "runs": len(gw.registry.by_id),
                                            "recent": {str(w): gw.recent_stats(w)
                                                       for w in (900, 1800, 3600)}})
            m = re.fullmatch(r"/_bench/runs/([^/]+)", path)
            run = gw.registry.by_id.get(m.group(1)) if m else None
            if run is None:
                return self.send_json(404, openai_error("unknown run"))
            self.send_json(200, run.summary())

        def admin_post(self, path, raw):
            if not self.is_loopback():
                return self.send_json(403, openai_error("admin API is loopback-only"))
            if path != "/_bench/runs":
                return self.send_json(404, openai_error("unknown admin path"))
            try:
                spec = json.loads(raw or b"{}")
                run = Run(spec["run_id"], spec.get("log_dir"), spec.get("cap", DEFAULT_CAP),
                          spec.get("faults"), spec.get("canaries"), spec.get("store", "delta"),
                          spec.get("params"))
            except (ValueError, KeyError) as exc:
                return self.send_json(400, openai_error(f"bad run spec: {exc}"))
            gw.registry.add(run)
            self.send_json(200, {"run_id": run.run_id, "token": run.token,
                                 "model": gw.model, "cap": run.cap})

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_hostport(value, default_port=8787):
    host, _, port = value.rpartition(":")
    return (host or value, int(port) if port else default_port)


def cmd_serve(args):
    gw = Gateway(args)
    handler = make_handler(gw)
    servers = []

    def bind_forever(addr, required):
        while True:
            try:
                srv = Server(addr, handler)
            except OSError as exc:
                if required:
                    sys.exit(f"cannot listen on {addr}: {exc}")
                log(f"cannot listen on {addr} yet ({exc}); retrying in 30s")
                time.sleep(30)
                continue
            servers.append(srv)
            log(f"listening on {addr[0]}:{addr[1]}")
            srv.serve_forever()
            return

    listens = args.listen or ["127.0.0.1:8787"]
    threads = []
    for i, spec in enumerate(listens):
        t = threading.Thread(target=bind_forever, args=(parse_hostport(spec), i == 0),
                             daemon=True)
        t.start()
        threads.append(t)
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for srv in servers:
            srv.shutdown()


# ---------------------------------------------------------------- relay

def cmd_relay(args):
    """Plain TCP forwarder: runs as the `saia-gw` container, dual-homed on the
    internal bench network and the default bridge, so agent containers reach
    the host gateway and nothing else."""
    lhost, lport = parse_hostport(args.listen)
    thost, tport = parse_hostport(args.to)
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind((lhost, lport))
    lsock.listen(128)
    log(f"relay {lhost}:{lport} -> {thost}:{tport}")

    def pump(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    while True:
        client, _ = lsock.accept()
        try:
            upstream = socket.create_connection((thost, tport), timeout=10)
            upstream.settimeout(None)
        except OSError as exc:
            log(f"relay: upstream connect failed: {exc}")
            client.close()
            continue
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=pump, args=(a, b), daemon=True).start()


# ---------------------------------------------------------------- probe-context

def admin_call(base, method, path, payload=None):
    req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def cmd_probe_context(args):
    """One deliberately oversized request: vLLM answers 400 with the model's
    maximum context length. Costs exactly one SAIA request."""
    run = admin_call(args.admin, "POST", "/_bench/runs",
                     {"run_id": f"probe-context-{int(time.time())}", "cap": 2, "store": "none"})
    try:
        filler = "lorem ipsum " * (args.tokens // 2)
        req = urllib.request.Request(
            args.admin.rstrip("/") + "/v1/chat/completions", method="POST",
            data=json.dumps({"model": "probe", "max_tokens": 1,
                             "messages": [{"role": "user", "content": filler}]}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {run['token']}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read().decode(errors="replace")
                print(f"accepted {args.tokens}-token prompt (HTTP {resp.status}); "
                      "context is at least that large")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            m = re.search(r"maximum context length is (\d+)", body) or \
                re.search(r"max(?:imum)?[_ ]model[_ ]len\D*(\d+)", body)
            if m:
                print(f"context window: {m.group(1)} tokens")
            else:
                print(f"HTTP {exc.code}: {body[:500]}")
    finally:
        admin_call(args.admin, "DELETE", f"/_bench/runs/{run['run_id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--listen", action="append",
                       help="host:port; repeatable. The first must bind; later ones retry "
                            "(e.g. the docker bridge address before docker is up)")
    serve.add_argument("--upstream", default=os.environ.get("SAIA_UPSTREAM", DEFAULT_UPSTREAM))
    serve.add_argument("--model", default=DEFAULT_MODEL)
    serve.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    serve.add_argument("--inject-usage", type=lambda s: s.lower() in ("1", "on", "true", "yes"),
                       default=True, help="add stream_options.include_usage (on|off)")
    serve.add_argument("--allow-no-keys", action="store_true",
                       help="start with a dummy key (tests against a fake upstream)")
    serve.add_argument("--verbose", action="store_true")
    serve.set_defaults(func=cmd_serve)
    relay = sub.add_parser("relay")
    relay.add_argument("--listen", default="0.0.0.0:8787")
    relay.add_argument("--to", required=True)
    relay.set_defaults(func=cmd_relay)
    probe = sub.add_parser("probe-context")
    probe.add_argument("--admin", default="http://127.0.0.1:8787")
    probe.add_argument("--tokens", type=int, default=400_000)
    probe.set_defaults(func=cmd_probe_context)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
