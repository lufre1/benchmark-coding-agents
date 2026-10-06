"""Where a benchmarked agent runs: a scratch dir on the host, or a docker
container built from the task image.

Both expose the same paths (workdir, home, agent_dir) and the same small API,
so agents.py adapters never care which one they got. The agent environment is
always built from an allowlist (never the bench's own environment), so keys
exported in ~/.bashrc cannot leak into an agent process.

Stdlib only, Python 3.10+.
"""

import io
import os
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

HOME = Path.home()
WORK_ROOT = Path(os.environ.get("BENCH_WORK_ROOT", "/var/tmp/bench-ws"))
TOOLBOX = Path(os.environ.get("BENCH_TOOLBOX", HOME / ".local/share/bench-toolbox"))
# Overridable so tests can run a second network + relay against a test gateway.
NETWORK = os.environ.get("BENCH_AGENT_NETWORK", "bench-agents")
RELAY_NAME = os.environ.get("BENCH_RELAY_NAME", "saia-gw")
RELAY_ALIAS = "saia-gw"  # what agent configs point at (per-network alias)
OWNER_LABEL = "bench.owner=benchmark-coding-agents"

HOST_PATH = [str(HOME / p) for p in (".local/bin", ".opencode/bin", ".minimax-code/bin",
                                     ".pi/agent/bin", ".cache/opencode/bin")] + \
    ["/usr/local/bin", "/usr/bin", "/bin"]

GIT_IDENTITY = {"GIT_AUTHOR_NAME": "bench-agent", "GIT_AUTHOR_EMAIL": "agent@bench.invalid",
                "GIT_COMMITTER_NAME": "bench-agent", "GIT_COMMITTER_EMAIL": "agent@bench.invalid"}
BASE_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "NO_COLOR": "1", "CI": "1",
            "PAGER": "cat", "GIT_PAGER": "cat", **GIT_IDENTITY}


def tar_bytes(files):
    """In-memory tar for `docker cp -`: {abs path: (str|bytes, mode)}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        dirs = set()
        for path in files:
            parent = Path(path).parent
            while str(parent) not in ("/", ".") and parent not in dirs:
                dirs.add(parent)
                parent = parent.parent
        for d in sorted(dirs, key=lambda p: len(p.parts)):
            info = tarfile.TarInfo(str(d).lstrip("/"))
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
            tar.addfile(info)
        for path, (data, mode) in files.items():
            raw = data.encode() if isinstance(data, str) else data
            info = tarfile.TarInfo(str(path).lstrip("/"))
            info.size, info.mode, info.mtime = len(raw), mode, int(time.time())
            tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


class HostExecutor:
    """Agent runs on the host in /var/tmp/bench-ws/<run_id>/, outside every
    git repo, with a fresh HOME. Weaker isolation than docker (absolute paths
    stay readable); meant for in-house tasks, adapter tests and pilots."""
    kind = "host"

    def __init__(self, run_id, root=WORK_ROOT):
        self.root = Path(root) / run_id
        self.workdir = str(self.root / "workspace")
        self.home = str(self.root / "home")
        self.agent_dir = str(self.root / "agent")

    def describe(self):
        return f"host:{self.root}"

    def start(self):
        for d in (self.workdir, self.home, self.agent_dir, self.root / "tmp"):
            Path(d).mkdir(parents=True, exist_ok=True)

    def env(self, extra=None):
        h = self.home
        env = {**BASE_ENV, "HOME": h, "PATH": ":".join(HOST_PATH), "TMPDIR": str(self.root / "tmp"),
               "XDG_CONFIG_HOME": f"{h}/.config", "XDG_DATA_HOME": f"{h}/.local/share",
               "XDG_CACHE_HOME": f"{h}/.cache", "XDG_STATE_HOME": f"{h}/.local/state"}
        env.update(extra or {})
        return env

    def installer_path(self, repo, script):
        return str(HOME / repo / script)

    def put_files(self, files):
        for path, (data, mode) in files.items():
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data.encode() if isinstance(data, str) else data)
            p.chmod(mode)

    def read_text(self, path):
        return Path(path).read_text()

    def sh(self, script, env=None, timeout=300, cwd=None):
        return subprocess.run(["bash", "-c", script], env=self.env(env), cwd=cwd or self.workdir,
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)

    def phase_command(self, cmd):
        return cmd.argv, {"env": self.env(cmd.env), "cwd": cmd.cwd or self.workdir,
                          "stdin_path": cmd.stdin_path}

    def on_kill(self):
        pass  # run_phase kills the whole process group

    def copy_out(self, src, dst):
        src, dst = Path(src), Path(dst)
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(src, dst)
        return True

    def remove(self, keep=False):
        if not keep:
            shutil.rmtree(self.root, ignore_errors=True)


class DockerExecutor:
    """Agent runs as root inside a fresh container of the task image. The
    container sits on an internal network whose only reachable endpoint is
    the saia-gw relay; the toolbox is mounted read-only at /opt/agents."""
    kind = "docker"

    def __init__(self, run_id, image, *, workdir="/app", memory="5g", cpus=2, pids_limit=4096,
                 network=NETWORK, toolbox=TOOLBOX, role="agent", extra_env=None):
        self.name = re.sub(r"[^A-Za-z0-9_.-]", "-", f"bench-{role}-{run_id}")[:120]
        self.image, self.memory, self.cpus, self.pids_limit = image, memory, cpus, pids_limit
        self.network, self.role = network, role
        self.toolbox = Path(toolbox) if toolbox else None
        self.run_id = run_id
        self.workdir, self.home, self.agent_dir = workdir, "/root", "/agent"
        self.image_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        self.extra_env = extra_env or {}
        self.started = False

    def describe(self):
        return f"docker:{self.name} ({self.image})"

    def run_argv(self):
        argv = ["docker", "run", "-d", "--init", "--name", self.name, "--platform", "linux/amd64",
                "--label", OWNER_LABEL, "--label", f"bench.run_id={self.run_id}",
                "--label", f"bench.role={self.role}", "--label", f"bench.pid={os.getpid()}",
                "--cpus", str(self.cpus), "--memory", self.memory, "--memory-swap", self.memory,
                "--pids-limit", str(self.pids_limit), "--security-opt", "no-new-privileges",
                "-w", self.workdir]
        argv += ["--network", self.network] if self.network else ["--network", "none"]
        if self.toolbox and self.role == "agent":
            argv += ["--mount", f"type=bind,src={self.toolbox},dst=/opt/agents,readonly"]
        return argv + [self.image, "sleep", "infinity"]

    def start(self):
        if self.role == "agent" and self.toolbox and not (self.toolbox / "bin").is_dir():
            raise RuntimeError(f"agent toolbox missing at {self.toolbox} — run "
                               "toolbox/build-toolbox.sh first")
        docker(*self.run_argv()[1:], timeout=600)
        self.started = True
        path = docker("exec", self.name, "printenv", "PATH", check=False).stdout.strip()
        if path:
            self.image_path = path
        docker("exec", self.name, "mkdir", "-p", self.agent_dir)

    def env(self, extra=None):
        if self.role != "agent":
            # The verifier must see the image's own environment, exactly as
            # upstream grades (CI/TERM/NO_COLOR change some test runners).
            return dict(extra or {})
        env = {**BASE_ENV, "HOME": self.home,
               "PATH": "/opt/agents/bin:" + self.image_path, **self.extra_env}
        env.update(extra or {})
        return env

    def installer_path(self, repo, script):
        return f"/opt/agents/installers/{repo}/{script}"

    def exec_argv(self, argv, env=None, cwd=None, interactive=False):
        cmd = ["docker", "exec"] + (["-i"] if interactive else []) + ["-w", cwd or self.workdir]
        for k, v in self.env(env).items():
            cmd += ["-e", f"{k}={v}"]
        return cmd + [self.name] + list(argv)

    def put_files(self, files):
        subprocess.run(["docker", "cp", "-", f"{self.name}:/"], input=tar_bytes(files),
                       check=True, capture_output=True, timeout=120)

    def read_text(self, path):
        return docker("exec", self.name, "cat", path).stdout

    def sh(self, script, env=None, timeout=300, cwd=None):
        return subprocess.run(self.exec_argv(["bash", "-c", script], env, cwd),
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)

    def phase_command(self, cmd):
        argv = self.exec_argv(cmd.argv, cmd.env, cmd.cwd, interactive=bool(cmd.stdin_path))
        return argv, {"env": None, "cwd": None, "stdin_path": cmd.stdin_path}

    def on_kill(self):
        """Killing the `docker exec` client leaves the agent alive inside the
        container: kill PID 1 instead, then restart the (sleep) container so
        the writable layer can still be collected."""
        docker("kill", self.name, check=False)
        docker("start", self.name, check=False)

    def copy_out(self, src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(["docker", "cp", f"{self.name}:{src}", str(dst)],
                             capture_output=True, text=True, timeout=600)
        return res.returncode == 0

    def remove(self, keep=False):
        if self.started and not keep:
            docker("rm", "-f", self.name, check=False)


def docker(*args, check=True, timeout=300, input=None):
    res = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                         input=input)
    if check and res.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:3])} failed: {res.stderr.strip()[:500]}")
    return res


def docker_available():
    try:
        return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_agent_network(relay_image, gateway_script, host_port=8787):
    """Internal network + the dual-homed relay container that is the only way
    out of it (to the host gateway on the default bridge)."""
    if docker("network", "inspect", NETWORK, check=False).returncode != 0:
        docker("network", "create", "--internal", "--label", OWNER_LABEL, NETWORK)
    state = docker("inspect", "-f", "{{.State.Running}}", RELAY_NAME, check=False)
    if state.returncode == 0 and state.stdout.strip() == "true":
        return
    docker("rm", "-f", RELAY_NAME, check=False)
    docker("run", "-d", "--name", RELAY_NAME, "--restart", "unless-stopped",
           "--label", OWNER_LABEL, "--network", NETWORK, "--network-alias", RELAY_ALIAS,
           "--add-host", "host.docker.internal:host-gateway",
           "--mount", f"type=bind,src={gateway_script},dst=/gw/saia_gateway.py,readonly",
           relay_image, "python3", "/gw/saia_gateway.py", "relay",
           "--listen", "0.0.0.0:8787", "--to", f"host.docker.internal:{host_port}")
    docker("network", "connect", "bridge", RELAY_NAME)


def gc_containers():
    """Remove bench containers whose owning bench process is gone."""
    res = docker("ps", "-a", "--filter", f"label={OWNER_LABEL}", "--format",
                 '{{.Names}} {{.Label "bench.pid"}} {{.Label "bench.role"}}', check=False)
    removed = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] == "" or parts[0] == RELAY_NAME:
            continue
        name, pid = parts[0], parts[1]
        alive = pid.isdigit() and Path(f"/proc/{pid}").exists()
        if not alive:
            docker("rm", "-f", name, check=False)
            removed.append(name)
    return removed
