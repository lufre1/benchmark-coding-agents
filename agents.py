"""Agent adapters: how each benchmarked coding-agent CLI is configured,
invoked headless, and parsed.

Every adapter talks to SAIA only through saia_gateway.py with a per-run token,
so the real keys never reach an agent and every agent runs the same pinned
model. Configuration happens in the run's fresh home (a scratch dir on the
host, /root in a container): the six SAIA installers from ~ write their normal
config there (with SAIA_BASE_URL pointing at the gateway), then the adapter
overlays bench-only settings (step caps, context limits, all model roles ->
the pinned model). opencode is configured directly: its installer would add
the SAIA plugin (model fallback) and the YAGNI instruction, both confounds.

Stdlib only, Python 3.10+.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "deepseek-v4-flash-0731"
TOKEN_KEYS = ("input", "output", "reasoning", "cache_read", "cache_write")

FALLBACK_RE = re.compile(r"(?i)agent\b.*\b(not found|unknown|does not exist|falling back|invalid)")


def empty_tokens():
    return {k: 0 for k in TOKEN_KEYS}


def add_tokens(total, part):
    for k in TOKEN_KEYS:
        total[k] += part.get(k, 0)


def empty_parse():
    return {"steps": 0, "tool_calls": 0, "cost": 0.0, "tokens": empty_tokens(),
            "session_ids": [], "errors": []}


def iter_jsonl(path):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


# ---------------------------------------------------------------- opencode parsing

def parse_events(events_path):
    """Aggregate the NDJSON event stream of one opencode run."""
    agg = empty_parse()
    for event in iter_jsonl(events_path):
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


def db_usage(root_session_ids, db_file, warn=print):
    """Aggregate per-(agent, model) usage from an opencode.db, including
    subagent child sessions (session.parent_id). Returns None on failure."""
    if not root_session_ids or not Path(db_file).exists():
        return None
    try:
        db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, timeout=5)
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
        warn(f"WARNING: db usage lookup failed: {exc}")
        return None


# ---------------------------------------------------------------- run context

@dataclass
class PhaseCmd:
    argv: list
    env: dict = field(default_factory=dict)
    cwd: str | None = None
    stdin_path: str | None = None  # host file fed to the agent's stdin


@dataclass
class RunCtx:
    run_id: str
    run_dir: Path
    task: dict
    combo: dict
    defaults: dict
    ex: object                     # executors.HostExecutor | executors.DockerExecutor
    token: str                     # per-run gateway token (never a real SAIA key)
    gw_url: str                    # gateway base URL as seen from inside the target
    prompt: str
    request_cap: int
    timeout: int
    kind: str                      # "host" (in-house task) | "deepswe"
    model: str = MODEL
    context_window: int = 131072
    max_output: int = 16384

    @property
    def prompt_file(self):
        """The prompt inside the target (put there by bench before prepare)."""
        return f"{self.ex.agent_dir}/prompt.md"

    @property
    def host_prompt_file(self):
        return str(self.run_dir / "prompt.md")


def run_installer(ctx, repo, script, args=(), env=None):
    """Run one of the ~ SAIA installers inside the target, against the
    gateway, with the per-run token as the 'SAIA key'."""
    path = ctx.ex.installer_path(repo, script)
    cmd = " ".join(["bash", _q(path), *(_q(a) for a in args)])
    res = ctx.ex.sh(cmd, env={"SAIA_API_KEY": ctx.token, "SAIA_BASE_URL": ctx.gw_url,
                              "SAIA_DEFAULT_MODEL": ctx.model, **(env or {})}, timeout=300)
    log_path = ctx.run_dir / f"installer_{repo}.log"
    log_path.write_text((res.stdout or "") + "\n" + (res.stderr or ""))
    if res.returncode != 0:
        raise RuntimeError(f"installer {repo} failed (exit {res.returncode}), see {log_path}")


def _q(s):
    s = str(s)
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------- adapters

class AgentAdapter:
    name = None

    def __init__(self, combo):
        self.combo = combo

    def phases(self, ctx):
        return [{"agent": self.name}]

    def prepare(self, ctx):
        """Write the agent's config into the target's fresh home."""

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token}

    def build_cmd(self, ctx, i, phase, prev):
        raise NotImplementedError

    def parse(self, ctx, i, events_path, stderr_path):
        return empty_parse()

    def artifacts(self, ctx):
        """(path inside target, name under run_dir/agent/) to copy out."""
        return []

    def usage(self, ctx):
        return None

    def flags(self, ctx, phase_results):
        return []

    def max_steps(self, ctx):
        return min(self.combo.get("max_steps") or ctx.request_cap, ctx.request_cap)


class OpencodeAdapter(AgentAdapter):
    """opencode in isolated mode: per-run config with the gateway as provider,
    no plugin (--pure), no global instructions (YAGNI off), every agent pinned
    to the model. Phases come from the combo (plan -> build by default)."""
    name = "opencode"

    def config_path(self, ctx):
        return f"{ctx.ex.home}/.config/opencode/opencode.json"

    def phases(self, ctx):
        return self.combo.get("phases") or [{"agent": "build"}]

    def prepare(self, ctx):
        m = f"saia-gwdg/{ctx.model}"
        agents = {}
        for name in ("plan", "build", "general", "explore"):
            agents[name] = {"model": m}
        steps = self.combo.get("steps") or {"plan": 40, "build": max(1, self.max_steps(ctx) - 40)}
        for name, n in steps.items():
            agents.setdefault(name, {"model": m})["steps"] = n
        for name, cfg in (self.combo.get("agent_config") or {}).items():
            agents.setdefault(name, {"model": m}).update(cfg)
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": m, "small_model": m, "autoupdate": False, "share": "disabled",
            "enabled_providers": ["saia-gwdg"],
            "provider": {"saia-gwdg": {
                "npm": "@ai-sdk/openai-compatible", "name": "GWDG SAIA (bench gateway)",
                "options": {"baseURL": ctx.gw_url, "apiKey": "{env:SAIA_API_KEY}",
                            "chunkTimeout": 150000},
                "models": {ctx.model: {
                    "name": ctx.model, "tool_call": True, "temperature": True,
                    "limit": {"context": ctx.context_window, "output": ctx.max_output}}}}},
            "agent": agents,
        }
        ctx.ex.put_files({self.config_path(ctx): (json.dumps(config, indent=2), 0o600)})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token,
                "OPENCODE_CONFIG": self.config_path(ctx),
                "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1", "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1"}

    def build_cmd(self, ctx, i, phase, prev):
        message = phase.get("prompt") or ctx.prompt
        argv = ["opencode", "run", "--pure", "--dir", ctx.ex.workdir, "--agent", phase["agent"],
                "--format", "json", "--auto", "--title", ctx.run_id[:60]]
        if i > 1 and prev.get("session_id"):
            argv += ["-s", prev["session_id"]]
        argv.append(message)
        return PhaseCmd(argv, self.run_env(ctx))

    def parse(self, ctx, i, events_path, stderr_path):
        return parse_events(events_path)

    def artifacts(self, ctx):
        base = f"{ctx.ex.home}/.local/share/opencode"
        return [(f"{base}/opencode.db", "opencode.db"),
                (f"{base}/opencode.db-wal", "opencode.db-wal")]

    def usage(self, ctx, session_ids=()):
        return db_usage(session_ids, ctx.run_dir / "agent/opencode.db")

    def flags(self, ctx, phase_results):
        out = []
        for p in phase_results:
            stderr = Path(ctx.run_dir / f"stderr_p{p['phase']}.log")
            try:
                if FALLBACK_RE.search(stderr.read_text(errors="replace")):
                    out.append(f"agent_fallback_p{p['phase']}")
            except OSError:
                pass
        return out


class AiderAdapter(AgentAdapter):
    name = "aider"

    def prepare(self, ctx):
        run_installer(ctx, "aider-saia-gwdg", "install-aider-saia-gwdg.sh", ["--yes"],
                      {"AIDER_CONFIG_FILE": f"{ctx.ex.home}/.aider.conf.yml"})
        meta = {f"openai/{ctx.model}": {
            "max_input_tokens": ctx.context_window, "max_output_tokens": ctx.max_output,
            "max_tokens": ctx.max_output, "input_cost_per_token": 0.0,
            "output_cost_per_token": 0.0, "litellm_provider": "openai", "mode": "chat",
            "supports_function_calling": True}}
        ctx.ex.put_files({f"{ctx.ex.agent_dir}/model-metadata.json": (json.dumps(meta), 0o644)})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token, "OPENAI_API_KEY": ctx.token,
                "LITELLM_LOCAL_MODEL_COST_MAP": "True", "AIDER_CHECK_UPDATE": "false"}

    def build_cmd(self, ctx, i, phase, prev):
        a = ctx.ex.agent_dir
        argv = ["aider", "--config", f"{ctx.ex.home}/.aider.conf.yml",
                "--model", f"openai/{ctx.model}", "--weak-model", f"openai/{ctx.model}",
                "--editor-model", f"openai/{ctx.model}", "--openai-api-base", ctx.gw_url,
                "--model-metadata-file", f"{a}/model-metadata.json",
                "--message-file", ctx.prompt_file, "--yes-always", "--no-analytics",
                "--analytics-log", f"{a}/analytics.jsonl", "--llm-history-file", f"{a}/llm.log",
                "--chat-history-file", f"{a}/chat.md", "--input-history-file", f"{a}/input.hist",
                "--no-check-update", "--no-show-release-notes", "--no-show-model-warnings",
                "--no-pretty", "--no-fancy-input", "--no-gitignore", "--env-file", "/dev/null",
                "--timeout", "600"]
        if ctx.kind == "deepswe":
            argv += ["--auto-commits"]  # only committed work is graded; aider's native way
        else:
            argv += ["--no-auto-commits", "--no-dirty-commits"]
            argv += [f for f in ctx.task.get("expects", [])]  # starter/deliverable files
        return PhaseCmd(argv, self.run_env(ctx))

    def parse(self, ctx, i, events_path, stderr_path):
        agg = empty_parse()
        for ev in iter_jsonl(ctx.run_dir / "agent/analytics.jsonl"):
            if ev.get("event") == "message_send":
                props = ev.get("properties") or {}
                agg["steps"] += 1
                add_tokens(agg["tokens"], {"input": props.get("prompt_tokens") or 0,
                                           "output": props.get("completion_tokens") or 0})
        try:
            text = Path(events_path).read_text(errors="replace")
            agg["errors"] = re.findall(r"(?m)^.*(?:litellm\.\w+Error|APIError|Exception).*$",
                                       text)[:20]
        except OSError:
            pass
        return agg

    def artifacts(self, ctx):
        a = ctx.ex.agent_dir
        return [(f"{a}/analytics.jsonl", "analytics.jsonl"), (f"{a}/llm.log", "llm.log"),
                (f"{a}/chat.md", "chat.md")]


class MiniAdapter(AgentAdapter):
    name = "mini"

    def cfg_dir(self, ctx):
        return f"{ctx.ex.home}/.config/mini-swe-agent"

    def prepare(self, ctx):
        run_installer(ctx, "mini-swe-agent-saia-gwdg", "install-mini-swe-agent-saia-gwdg.sh",
                      ["--yes"], {"MSWEA_GLOBAL_CONFIG_DIR": self.cfg_dir(ctx)})
        overlay = {  # JSON is valid YAML
            "agent": {"mode": "yolo", "step_limit": self.max_steps(ctx), "cost_limit": 0},
            "environment": {"cwd": ctx.ex.workdir, "timeout": 300},
            "model": {"model_name": ctx.model, "cost_tracking": "ignore_errors",
                      "model_kwargs": {"custom_llm_provider": "openai", "api_base": ctx.gw_url,
                                       "api_key": ctx.token, "drop_params": True}},
        }
        ctx.ex.put_files({f"{self.cfg_dir(ctx)}/bench.yaml": (json.dumps(overlay, indent=1), 0o600)})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token, "OPENAI_API_KEY": ctx.token,
                "MSWEA_GLOBAL_CONFIG_DIR": self.cfg_dir(ctx), "MSWEA_CONFIGURED": "true",
                "MSWEA_SILENT_STARTUP": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "MSWEA_COST_TRACKING": "ignore_errors"}

    def build_cmd(self, ctx, i, phase, prev):
        d = self.cfg_dir(ctx)
        return PhaseCmd(["mini", "-y", "--exit-immediately", "-c", f"{d}/mini.yaml",
                         "-c", f"{d}/bench.yaml", "-o", f"{ctx.ex.agent_dir}/traj.json",
                         "-t", ctx.prompt], self.run_env(ctx))

    def parse(self, ctx, i, events_path, stderr_path):
        agg = empty_parse()
        try:
            traj = json.loads((ctx.run_dir / "agent/traj.json").read_text())
        except (OSError, ValueError):
            return agg
        info = traj.get("info") or {}
        stats = info.get("model_stats") or {}
        agg["steps"] = stats.get("api_calls") or 0
        agg["exit_status"] = info.get("exit_status")
        msgs = traj.get("messages") or []
        agg["tool_calls"] = sum(len(m.get("tool_calls") or []) for m in msgs
                                if isinstance(m, dict) and m.get("role") == "assistant")
        return agg

    def artifacts(self, ctx):
        return [(f"{ctx.ex.agent_dir}/traj.json", "traj.json")]

    def flags(self, ctx, phase_results):
        status = str((phase_results[-1] if phase_results else {}).get("exit_status") or "")
        return ["step_limit"] if "limit" in status.lower() else []


class OpenHandsAdapter(AgentAdapter):
    name = "openhands"

    def prepare(self, ctx):
        run_installer(ctx, "openhands-saia-gwdg", "install-openhands-saia.sh", [],
                      {"OPENHANDS_DATA_DIR": f"{ctx.ex.home}/.openhands"})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token, "LLM_MODEL": f"openai/{ctx.model}",
                "LLM_BASE_URL": ctx.gw_url, "LLM_API_KEY": ctx.token,
                "OPENHANDS_SUPPRESS_BANNER": "1", "OPENHANDS_WORK_DIR": ctx.ex.workdir,
                "OPENHANDS_CONVERSATIONS_DIR": f"{ctx.ex.agent_dir}/conversations",
                "TMPDIR": f"{ctx.ex.agent_dir}/tmp", "LITELLM_LOCAL_MODEL_COST_MAP": "True"}

    def build_cmd(self, ctx, i, phase, prev):
        return PhaseCmd(["bash", "-c", f"mkdir -p {_q(ctx.ex.agent_dir)}/tmp && exec openhands "
                         f"--headless --json --override-with-envs --exit-without-confirmation "
                         f"-f {_q(ctx.prompt_file)}"], self.run_env(ctx))

    @staticmethod
    def iter_events(path):
        """`--headless --json` prints pretty-printed JSON objects, each after
        a `--JSON Event--` marker line (not JSONL)."""
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            return
        dec = json.JSONDecoder()
        for block in text.split("--JSON Event--")[1:]:
            try:
                obj, _ = dec.raw_decode(block.lstrip())
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj

    def parse(self, ctx, i, events_path, stderr_path):
        agg = empty_parse()
        for ev in self.iter_events(events_path):
            kind = str(ev.get("kind") or "")
            if kind == "ActionEvent":
                agg["tool_calls"] += 1
                agg["steps"] += 1
            elif kind == "MessageEvent" and ev.get("source") == "agent":
                agg["steps"] += 1
            elif "Error" in kind:
                agg["errors"].append(json.dumps(ev)[:500])
        return agg

    def artifacts(self, ctx):
        return [(f"{ctx.ex.agent_dir}/conversations", "conversations")]


class PiFamilyAdapter(AgentAdapter):
    """pi and omp share the event format (omp is a pi fork)."""
    provider = "gwdg-saia"

    def parse(self, ctx, i, events_path, stderr_path):
        agg = empty_parse()
        for ev in iter_jsonl(events_path):
            etype = ev.get("type")
            if etype == "message_end":
                msg = ev.get("message") or {}
                if msg.get("role") == "assistant":
                    agg["steps"] += 1
                    u = msg.get("usage") or {}
                    add_tokens(agg["tokens"], {
                        "input": u.get("input") or 0, "output": u.get("output") or 0,
                        "cache_read": u.get("cacheRead") or 0,
                        "cache_write": u.get("cacheWrite") or 0})
                    if msg.get("errorMessage"):
                        agg["errors"].append(str(msg["errorMessage"])[:500])
            elif etype == "tool_execution_start":
                agg["tool_calls"] += 1
            elif etype in ("error", "auto_retry_start"):
                agg["errors"].append(json.dumps(ev)[:500])
        return agg


class PiAdapter(PiFamilyAdapter):
    name = "pi"

    def agent_dir(self, ctx):
        return f"{ctx.ex.home}/.pi/agent"

    def prepare(self, ctx):
        d = self.agent_dir(ctx)
        run_installer(ctx, "pi-saia-gwdg", "install-pi-saia-gwdg.sh", ["--yes"],
                      {"PI_CODING_AGENT_DIR": d})
        models = json.loads(ctx.ex.read_text(f"{d}/models.json"))
        for m in models["providers"][self.provider]["models"]:
            if m.get("id") == ctx.model:
                m.update(contextWindow=ctx.context_window, maxTokens=ctx.max_output)
        settings = json.loads(ctx.ex.read_text(f"{d}/settings.json"))
        settings.update(quietStartup=True, enableInstallTelemetry=False)
        ctx.ex.put_files({f"{d}/models.json": (json.dumps(models, indent=2), 0o600),
                          f"{d}/settings.json": (json.dumps(settings, indent=2), 0o600)})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token, "PI_CODING_AGENT_DIR": self.agent_dir(ctx),
                "PI_OFFLINE": "1", "PI_TELEMETRY": "0"}

    def build_cmd(self, ctx, i, phase, prev):
        return PhaseCmd(["pi", "-p", "--mode", "json", "--offline",
                         "--model", f"{self.provider}/{ctx.model}",
                         "--session-dir", f"{ctx.ex.agent_dir}/pi-sessions", "--", ctx.prompt],
                        self.run_env(ctx))

    def artifacts(self, ctx):
        return [(f"{ctx.ex.agent_dir}/pi-sessions", "pi-sessions")]


class OmpAdapter(PiFamilyAdapter):
    name = "omp"
    ROLES = ("default", "smol", "slow", "plan", "commit", "task")

    def agent_dir(self, ctx):
        return f"{ctx.ex.home}/.omp/agent"

    def prepare(self, ctx):
        d = self.agent_dir(ctx)
        run_installer(ctx, "omp-saia-gwdg", "install-omp-saia-gwdg.sh", ["--yes"],
                      {"PI_CODING_AGENT_DIR": d, "OMP_AGENT_ENV_FILE": f"{d}/.env"})
        m = f"{self.provider}/{ctx.model}"
        overlay = {"modelRoles": {r: m for r in self.ROLES},
                   "retry": {"modelFallback": False}, "advisor": {"enabled": False}}
        ctx.ex.put_files({f"{ctx.ex.agent_dir}/omp-bench.yml": (json.dumps(overlay), 0o600)})

    def run_env(self, ctx):
        d = self.agent_dir(ctx)
        return {"SAIA_API_KEY": ctx.token, "PI_CODING_AGENT_DIR": d,
                "OMP_AGENT_ENV_FILE": f"{d}/.env", "PI_NO_TITLE": "1", "OMP_SKIP_SETUP": "1",
                "PI_STREAM_FIRST_EVENT_TIMEOUT_MS": "120000", "PI_STREAM_IDLE_TIMEOUT_MS": "120000"}

    def build_cmd(self, ctx, i, phase, prev):
        return PhaseCmd(["omp", "-p", "--mode", "json", "--cwd", ctx.ex.workdir,
                         "--model", f"{self.provider}/{ctx.model}", "--approval-mode", "yolo",
                         "--config", f"{ctx.ex.agent_dir}/omp-bench.yml",
                         "--max-time", str(ctx.timeout), "--no-title", "--no-lsp",
                         "--session-dir", f"{ctx.ex.agent_dir}/omp-sessions", "--", ctx.prompt],
                        self.run_env(ctx))

    def artifacts(self, ctx):
        return [(f"{ctx.ex.agent_dir}/omp-sessions", "omp-sessions")]


class McodeAdapter(AgentAdapter):
    name = "mcode"

    def data_dir(self, ctx):
        return f"{ctx.ex.home}/.minimax"

    def prepare(self, ctx):
        run_installer(ctx, "mcode-saia", "install-mcode-saia.sh", [],
                      {"MINIMAX_DATA_DIR": self.data_dir(ctx)})

    def run_env(self, ctx):
        return {"SAIA_API_KEY": ctx.token, "MINIMAX_DATA_DIR": self.data_dir(ctx)}

    def build_cmd(self, ctx, i, phase, prev):
        a = ctx.ex.agent_dir
        return PhaseCmd(["mcode", "exec", "--cwd", ctx.ex.workdir,
                         "--model", f"custom_provider:gwdg-saia/{ctx.model}",
                         "--permission", "full", "--max-steps", str(self.max_steps(ctx)),
                         "--timeout", f"{ctx.timeout}s", "--prompt-mode", "coding",
                         "--output-format", "stream-json", "--diagnostics-dir", f"{a}/mcode-diag",
                         "-o", f"{a}/last-message.md", "--input", "-"],
                        self.run_env(ctx), stdin_path=ctx.host_prompt_file)

    def parse(self, ctx, i, events_path, stderr_path):
        agg = empty_parse()
        for ev in iter_jsonl(events_path):
            etype = ev.get("type")
            if etype == "turn.completed":
                agg["steps"] += 1
                u = ev.get("usage") or {}
                add_tokens(agg["tokens"], {
                    "input": u.get("inputTokens") or 0, "output": u.get("outputTokens") or 0,
                    "reasoning": u.get("reasoningTokens") or 0,
                    "cache_read": u.get("cacheReadTokens") or 0,
                    "cache_write": u.get("cacheWriteTokens") or 0})
            elif etype == "item.completed" and "tool" in json.dumps(ev.get("item") or {})[:200]:
                agg["tool_calls"] += 1
            elif etype == "exec.result":
                agg["exit_status"] = ev.get("status")
            elif etype in ("error", "turn.failed"):
                agg["errors"].append(json.dumps(ev)[:500])
        return agg

    def artifacts(self, ctx):
        a = ctx.ex.agent_dir
        return [(f"{a}/mcode-diag", "mcode-diag"), (f"{a}/last-message.md", "last-message.md")]


ADAPTERS = {cls.name: cls for cls in (OpencodeAdapter, AiderAdapter, MiniAdapter,
                                      OpenHandsAdapter, PiAdapter, OmpAdapter, McodeAdapter)}


def make_adapter(combo):
    name = combo.get("agent", "opencode")
    if name not in ADAPTERS:
        raise SystemExit(f"unknown agent harness {name!r}; available: {sorted(ADAPTERS)}")
    return ADAPTERS[name](combo)
