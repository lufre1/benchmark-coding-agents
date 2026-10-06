#!/usr/bin/env python3
"""Minimal OpenAI-compatible fake LLM for adapter smoke tests (no SAIA cost).

Answers /v1/chat/completions (streaming or not) and /v1/models. If the
request offers tools and no tool result is in the conversation yet, it calls
the shell tool once (`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` — mini's
submit marker, harmless for everyone else); afterwards it replies "Done."
so every agent loop terminates. Prints the bound port on stdout and appends
one JSON line per request to $FAKE_LOG.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ.get("FAKE_LOG")
lock = threading.Lock()
SHELL_TOOLS = ("bash", "execute_bash", "terminal", "shell", "run_shell_command", "exec",
               "execute_command")


def pick_tool(body):
    names = [(t.get("function") or {}).get("name") for t in body.get("tools") or []]
    for want in SHELL_TOOLS:
        if want in names:
            return want
    return None


def plan_reply(body):
    msgs = body.get("messages") or []
    tool = pick_tool(body)
    if tool and not any(m.get("role") == "tool" for m in msgs):
        args = {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}
        if tool == "bash":
            args["description"] = "finish"
        return {"tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": tool, "arguments": json.dumps(args)}}]}
    return {"content": "Done."}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_json({"object": "list", "data": [{"id": "deepseek-v4-flash-0731",
                                                    "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        reply = plan_reply(body)
        if LOG:
            with lock, open(LOG, "a") as f:
                f.write(json.dumps({"model": body.get("model"), "stream": body.get("stream"),
                                    "tools": [(t.get("function") or {}).get("name")
                                              for t in body.get("tools") or []],
                                    "reply": "tool" if "tool_calls" in reply else "text"}) + "\n")
        usage = {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}
        finish = "tool_calls" if "tool_calls" in reply else "stop"
        if not body.get("stream"):
            msg = {"role": "assistant", "content": reply.get("content")}
            if "tool_calls" in reply:
                msg["tool_calls"] = reply["tool_calls"]
            return self.send_json({"id": "fake-1", "object": "chat.completion", "created": 0,
                                   "model": body.get("model"), "usage": usage,
                                   "choices": [{"index": 0, "message": msg,
                                                "finish_reason": finish}]})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def emit(obj):
            raw = ("data: " + json.dumps(obj) + "\n\n").encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
            self.wfile.flush()

        base = {"id": "fake-1", "object": "chat.completion.chunk", "created": 0,
                "model": body.get("model")}
        delta = {"role": "assistant"}
        if "tool_calls" in reply:
            delta["tool_calls"] = [{"index": 0, **tc} for tc in reply["tool_calls"]]
        else:
            delta["content"] = reply["content"]
        emit({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        emit({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        if (body.get("stream_options") or {}).get("include_usage"):
            emit({**base, "choices": [], "usage": usage})
        raw = b"data: [DONE]\n\n"
        self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(raw), raw))
        self.wfile.flush()


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0), H)
    srv.daemon_threads = True
    print(srv.server_address[1], flush=True)
    srv.serve_forever()
