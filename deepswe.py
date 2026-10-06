"""DeepSWE v1.1 tasks for bench.py: import, image pull, patch collection,
official grading, and the oracle/null validation gate.

Upstream: github.com/datacurve-ai/deep-swe (Apache-2.0), pinned below. Each
task runs in its published image (repo at /app, default branch at the base
commit). Only committed work counts: the upstream [[verifier.collect]] command
(`git diff --binary <base> HEAD`) produces model.patch, which the upstream
tests/test.sh + grader.py score — verbatim — in a fresh --network none
container of the same image (reward = all F2P pass and no P2P fails).

Stdlib only, Python 3.11+ (tomllib).
"""

import json
import random
import re
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

from executors import DockerExecutor, docker

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
UPSTREAM_REPO = "datacurve-ai/deep-swe"
UPSTREAM_COMMIT = "0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea"
CACHE_DIR = Path.home() / ".cache/bench-deepswe"
BENCH_TIMEOUT_S = 5400   # upstream's original agent timeout; the request cap bounds cost anyway
MAX_PATCH_BYTES = 50 * 1024 * 1024
# Agent-internal scratch that agents never commit (aider's repo-map cache):
# excluded from the grade-neutral diagnostics only, never from model.patch.
AGENT_SCRATCH = (".aider*",)

# Subset chosen from the published v1.1 trials (see AGENTS.md "DeepSWE subset"):
# not flagged by Epoch AI's review, discriminative, DeepSeek-flash solves 1-3/4
# (anchors 4/4), cheap in steps, small images, Python/TypeScript/Go balanced.
# ref = published mini_swe_agent_deepseek_v4_flash_max result (solved of 4,
# median steps) for calibrating our mini-ds runs.
SUBSET = {
    "ofetch-per-origin-circuit-breaker":       {"tiers": ["smoke"], "ref": (4, 78)},
    "wazero-multi-module-snapshots":           {"tiers": ["smoke"], "ref": (4, 74)},
    "aiomonitor-task-snapshots-diff":          {"tiers": ["smoke", "core"], "ref": (2, 102)},
    "httpx-multipart-response-parsing":        {"tiers": ["core"], "ref": (2, 120)},
    "bandit-incremental-cache-control":        {"tiers": ["core"], "ref": (1, 112)},
    "dateutil-rfc5545-timezone-interop":       {"tiers": ["core"], "ref": (2, 124)},
    "koota-entity-snapshot-rollback":          {"tiers": ["core"], "ref": (3, 85)},
    "sql-formatter-bigquery-pipe-formatting":  {"tiers": ["core"], "ref": (3, 126)},
    "cliffy-config-file-parsing":              {"tiers": ["core"], "ref": (3, 134)},
    "scc-bounded-memory-spilling":             {"tiers": ["core"], "ref": (2, 108)},
    "tengo-callable-instance-isolation":       {"tiers": ["core"], "ref": (2, 114)},
    "dasel-html-document-format":              {"tiers": ["core"], "ref": (2, 108)},
    # reserves (tier "reserve"): import explicitly by id if a task fails validation
    "mobly-grouped-test-barriers":             {"tiers": ["reserve"], "ref": (4, 104)},
    "ipython-session-bundle-replay":           {"tiers": ["reserve"], "ref": (3, 139)},
    "abs-stepped-slices":                      {"tiers": ["reserve"], "ref": (3, 104)},
    "prometheus-typed-label-sorting":          {"tiers": ["reserve"], "ref": (3, 141)},
    "testem-per-launcher-reports":             {"tiers": ["reserve"], "ref": (2, 103)},
    "kysely-window-grouping-helpers":          {"tiers": ["reserve"], "ref": (2, 167)},
    "fd-deterministic-multi-key-sorting":      {"tiers": ["reserve"], "ref": (3, 141)},
}
# Upstream mislabels (checked against Dockerfiles and patches).
LANGUAGE_OVERRIDES = {"koota-entity-snapshot-rollback": "typescript",
                      "httpx-deterministic-cookie-store": "python",
                      "prometheus-transactional-reload-status": "go"}

TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|testdata|spec)/|(^|/)test_[^/]*$|"
                          r"_test\.go$|\.(test|spec)\.[cm]?[jt]sx?$|_tests?\.py$|conftest\.py$")


def log(msg):
    print(f"[deepswe] {msg}", flush=True)


# ---------------------------------------------------------------- import

def fetch_upstream(src=None):
    """Path of the upstream tasks/ dir: a local clone/extract, or the pinned
    tarball (cached under ~/.cache/bench-deepswe/<sha>/)."""
    if src:
        p = Path(src).expanduser()
        return p / "tasks" if (p / "tasks").is_dir() else p
    dest = CACHE_DIR / UPSTREAM_COMMIT
    tasks = dest / f"deep-swe-{UPSTREAM_COMMIT}" / "tasks"
    if tasks.is_dir():
        return tasks
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://codeload.github.com/{UPSTREAM_REPO}/tar.gz/{UPSTREAM_COMMIT}"
    log(f"downloading {url}")
    tarball = dest / "deep-swe.tar.gz"
    with urllib.request.urlopen(url, timeout=120) as resp, open(tarball, "wb") as f:
        shutil.copyfileobj(resp, f)
    with tarfile.open(tarball) as tar:
        tar.extractall(dest, filter="data")
    return tasks


def ecr_digest(image):
    """Manifest digest of a public.ecr.aws image tag (anonymous registry API),
    or None if the registry can't be reached."""
    m = re.fullmatch(r"public\.ecr\.aws/([^:]+):(.+)", image)
    if not m:
        return None
    repo, tag = m.groups()
    try:
        with urllib.request.urlopen(
                f"https://public.ecr.aws/token/?scope=repository:{repo}:pull"
                f"&service=public.ecr.aws", timeout=30) as resp:
            token = json.loads(resp.read())["token"]
        req = urllib.request.Request(
            f"https://public.ecr.aws/v2/{repo}/manifests/{tag}", method="HEAD", headers={
                "Authorization": f"Bearer {token}",
                "Accept": ", ".join([
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json"])})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.headers.get("Docker-Content-Digest")
    except (OSError, ValueError, KeyError) as exc:
        log(f"WARNING: no digest for {image}: {exc}")
        return None


def patch_files(text):
    files = []
    for line in text.splitlines():
        m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
        if m:
            files.append(m.group(2))
    return list(dict.fromkeys(files))


def patch_stats(text, reference_files=(), test_patch_files=()):
    added = deleted = 0
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1
    files = patch_files(text)
    ref = set(reference_files)
    return {"files": len(files), "added": added, "deleted": deleted, "bytes": len(text.encode()),
            "test_files": sum(1 for f in files if TEST_PATH_RE.search(f)),
            "outside_reference": sum(1 for f in files if ref and f not in ref),
            "touches_test_patch_files": sorted(set(files) & set(test_patch_files))}


def task_ids_for(subsets, ids=()):
    picked = [t for t, meta in SUBSET.items() if set(meta["tiers"]) & set(subsets)]
    return list(dict.fromkeys(picked + list(ids)))


def sample_ids(upstream, n_tasks, seed):
    """pier's `--n-tasks N --sample-seed S` (random.Random(S).shuffle, first N),
    but over sorted ids: pier shuffles unsorted iterdir() order, so its own
    picks differ between machines/checkouts."""
    ids = sorted(p.name for p in upstream.iterdir() if (p / "task.toml").is_file())
    random.Random(seed).shuffle(ids)
    return ids[:n_tasks]


def import_tasks(subsets=("smoke", "core"), ids=(), src=None, pin_digest=True,
                 n_tasks=None, sample_seed=0):
    upstream = fetch_upstream(src)
    sampled = sample_ids(upstream, n_tasks, sample_seed) if n_tasks else []
    written = []
    for tid in task_ids_for(subsets, [*ids, *sampled]):
        src_dir = upstream / tid
        if not src_dir.is_dir():
            raise SystemExit(f"upstream task {tid!r} not found in {upstream}")
        toml = tomllib.loads((src_dir / "task.toml").read_text())
        meta, env = toml["metadata"], toml["environment"]
        collect = toml["verifier"]["collect"][0]
        instruction = (src_dir / "instruction.md").read_text()
        tests_dockerfile = (src_dir / "tests/Dockerfile").read_text()
        # Import assertions: the grading reproduction below relies on these.
        assert meta["base_commit_hash"] in collect["command"], f"{tid}: collect/base mismatch"
        assert "commit everything" in instruction, f"{tid}: instruction lacks commit line"
        copies = re.findall(r"^COPY (\S+) (\S+)$", tests_dockerfile, re.M)
        assert {(a, b) for a, b in copies} <= {
            ("test.sh", "/tests/test.sh"), ("test.patch", "/tests/test.patch"),
            ("grader.py", "/tests/grader.py"), ("config.json", "/tests/config.json")}, \
            f"{tid}: unexpected tests/Dockerfile {copies}"
        config = json.loads((src_dir / "tests/config.json").read_text())
        test_patch = (src_dir / "tests/test.patch").read_text(errors="replace")
        solution = (src_dir / "solution/solution.patch").read_text(errors="replace")
        image = env["docker_image"]
        dest = TASKS_DIR / f"deepswe-{tid}"
        validation = dest / "validation.json"  # kept: is_validated() rechecks commit + digest
        validation = validation.read_bytes() if validation.is_file() else None
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_dir / "tests", dest / "hidden_tests")
        shutil.copytree(src_dir / "solution", dest / "reference")
        (dest / "upstream/environment").mkdir(parents=True)
        shutil.copy2(src_dir / "task.toml", dest / "upstream/task.toml")
        shutil.copy2(src_dir / "environment/Dockerfile", dest / "upstream/environment/Dockerfile")
        (dest / "prompt.md").write_text(instruction)
        ref_files = patch_files(solution)
        task = {
            "name": f"deepswe-{tid}",
            "kind": "deepswe",
            "description": f"DeepSWE v1.1 ({meta.get('category')}, "
                           f"{LANGUAGE_OVERRIDES.get(tid, meta.get('language'))}): "
                           f"{meta.get('display_title')}",
            "language": LANGUAGE_OVERRIDES.get(tid, meta.get("language")),
            "category": meta.get("category"),
            "subsets": SUBSET.get(tid, {}).get("tiers", [])
                       + ([f"seed{sample_seed}"] if tid in sampled else []),
            "upstream_task_id": tid, "ext_id": meta.get("ext_id"),
            "upstream_commit": UPSTREAM_COMMIT, "repository_url": meta.get("repository_url"),
            "image": image, "image_digest": ecr_digest(image) if pin_digest else None,
            "workdir": "/app", "base_commit": meta["base_commit_hash"],
            "collect_command": collect["command"],
            "collect_timeout_s": int(collect.get("timeout_sec", 300)),
            "agent_timeout_s": int(toml["agent"]["timeout_sec"]),
            "timeout_s": BENCH_TIMEOUT_S,
            "verifier_timeout_s": int(toml["verifier"]["timeout_sec"]),
            "f2p_total": len(config.get("f2p_node_ids", [])),
            "p2p_total": len(config.get("p2p_node_ids", [])),
            "test_patch_paths": patch_files(test_patch),
            "reference_files": ref_files,
            "reference_stats": patch_stats(solution),
            "reference_runs": dict(zip(("ds_flash_solved_of_4", "ds_flash_median_steps"),
                                       SUBSET.get(tid, {}).get("ref", (None, None)))),
            "expects": [],
        }
        (dest / "task.json").write_text(json.dumps(task, indent=2) + "\n")
        if validation:
            (dest / "validation.json").write_bytes(validation)
        log(f"imported {task['name']} ({task['language']}, image digest "
            f"{(task['image_digest'] or 'unpinned')[:19]})")
        written.append(task["name"])
    return written


def image_ref(task):
    return f"{task['image']}@{task['image_digest']}" if task.get("image_digest") else task["image"]


def pull(task, retries=3):
    ref = image_ref(task)
    for attempt in range(1, retries + 1):
        res = docker("pull", "--platform", "linux/amd64", ref, check=False, timeout=1800)
        if res.returncode == 0:
            return ref
        log(f"pull {ref} failed (attempt {attempt}): {res.stderr.strip()[:200]}")
    raise RuntimeError(f"could not pull {ref}")


# ---------------------------------------------------------------- run-time

def agent_executor(task, run_id, defaults):
    d = defaults.get("deepswe", {})
    return DockerExecutor(run_id, image_ref(task), workdir=task.get("workdir", "/app"),
                          memory=d.get("memory", "5g"), cpus=d.get("cpus", 2),
                          pids_limit=d.get("pids_limit", 4096))


def collect(ex, task, run_dir):
    """Official collect step -> model.patch (+ grade-neutral diagnostics)."""
    run_dir = Path(run_dir)
    out = {"collect_exit": None, "diagnostics": {}}
    try:
        res = ex.sh(task["collect_command"], timeout=task.get("collect_timeout_s", 300), cwd="/")
        out["collect_exit"] = res.returncode
    except subprocess.TimeoutExpired:
        out["collect_exit"] = "timeout"
    got = ex.copy_out("/logs/artifacts/model.patch", run_dir / "model.patch")
    if not got:
        (run_dir / "model.patch").write_text("")
    base = task["base_commit"]
    scratch = " ".join(f"':(exclude){pat}'" for pat in AGENT_SCRATCH)
    diag = ex.sh(f"""cd /app
git config --global --add safe.directory /app
echo "head_branch=$(git rev-parse --abbrev-ref HEAD)"
echo "commits_ahead=$(git rev-list --count {base}..HEAD)"
echo "uncommitted=$(git status --porcelain -uall -- . {scratch} | wc -l)"
n=0; for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  c=$(git rev-list --count HEAD..$b); [ "$c" -gt 0 ] && n=$((n+c)); done
echo "commits_not_on_head=$n"
export GIT_INDEX_FILE=/tmp/bench-worktree.idx
git read-tree HEAD && git add -A -- . {scratch} && git diff --cached --binary {base} > /tmp/worktree.patch
echo "worktree_patch_bytes=$(stat -c %s /tmp/worktree.patch)"
""", timeout=600, cwd="/")
    for line in (diag.stdout or "").splitlines():
        k, _, v = line.partition("=")
        out["diagnostics"][k] = int(v) if v.isdigit() else v
    if int(out["diagnostics"].get("worktree_patch_bytes") or 0) <= MAX_PATCH_BYTES:
        ex.copy_out("/tmp/worktree.patch", run_dir / "worktree.patch")
    model_patch = (run_dir / "model.patch").read_text(errors="replace")
    out["patch"] = patch_stats(model_patch, task.get("reference_files", ()),
                               task.get("test_patch_paths", ()))
    return out


def grade(task, patch_path, run_dir, label="verifier", defaults=None):
    """Upstream verifier, verbatim, in a fresh --network none container."""
    d = (defaults or {}).get("deepswe", {})
    run_dir = Path(run_dir)
    tests = task["dir"] / "hidden_tests"
    ex = DockerExecutor(f"{run_dir.name}-{label}", image_ref(task), network=None, toolbox=None,
                        role="verifier", memory=d.get("memory", "5g"), cpus=d.get("cpus", 2))
    result = {"kind": "deepswe", "reward": 0, "ran": False, "eval_timed_out": False,
              "verifier_crash": False, "apply_failed": 0}
    files = {"/tests/test.sh": ((tests / "test.sh").read_bytes(), 0o755)}
    for name in ("test.patch", "grader.py", "config.json"):
        files[f"/tests/{name}"] = ((tests / name).read_bytes(), 0o644)
    patch = Path(patch_path).read_bytes() if patch_path and Path(patch_path).exists() else b""
    if patch:
        files["/logs/artifacts/model.patch"] = (patch, 0o644)
    out_dir = run_dir / label
    try:
        ex.start()
        ex.put_files(files)
        ex.sh("mkdir -p /logs/verifier /logs/artifacts && chmod 777 /logs/verifier", cwd="/")
        try:
            ex.sh("/tests/test.sh > /logs/verifier/test-stdout.txt 2>&1",
                  timeout=task.get("verifier_timeout_s", 1800), cwd="/app")
        except subprocess.TimeoutExpired:
            result["eval_timed_out"] = True
        ex.copy_out("/logs/verifier", out_dir)
    finally:
        ex.remove()
    reward_file = out_dir / "reward.json"
    if reward_file.exists():
        try:
            reward = json.loads(reward_file.read_text())
            result.update(reward)
            result["ran"] = True
        except ValueError:
            result["verifier_crash"] = True
    else:
        result["verifier_crash"] = not result["eval_timed_out"]
    # Map onto the bench's generic eval fields: one "test" per task, as in
    # DeepSWE's headline metric (binary solve rate).
    result.update(passed=int(result.get("reward") or 0), tests_total=1,
                  failed=0 if result.get("reward") else 1, errors=0, skipped=0,
                  p2p_failed=(result.get("p2p_total") or 0) - (result.get("p2p_passed") or 0),
                  expected_missing=[])
    return result


def validate(task, defaults=None):
    """Oracle (reference solution) must score 1, the untouched repo 0 with
    every P2P passing. Stored in tasks/<name>/validation.json."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="deepswe-validate-") as tmp:
        tmp = Path(tmp)
        run_id = f"validate-{task['name']}"
        ex = agent_executor(task, run_id, defaults or {})
        ex.toolbox, ex.network = None, None  # the oracle needs no agents and no network
        try:
            ex.start()
            ex.put_files({f"/solution/{p.name}": (p.read_bytes(), 0o755)
                          for p in (task["dir"] / "reference").iterdir() if p.is_file()})
            ex.sh("bash /solution/solve.sh", timeout=600, cwd="/app")
            col = collect(ex, task, tmp)
        finally:
            ex.remove()
        oracle = grade(task, tmp / "model.patch", tmp, "oracle", defaults)
        null = grade(task, None, tmp, "null", defaults)
    ok = (oracle.get("reward") == 1 and null.get("reward") == 0
          and null.get("f2p_passed", 1) == 0 and (null.get("p2p_total") or 0) == (
              null.get("p2p_passed") or 0))
    record = {"upstream_commit": task.get("upstream_commit"),
              "image_digest": task.get("image_digest"), "ok": ok,
              "oracle": {k: oracle.get(k) for k in ("reward", "f2p_passed", "f2p_total",
                                                    "p2p_passed", "p2p_total", "apply_failed")},
              "oracle_patch": col.get("patch"),
              "null": {k: null.get(k) for k in ("reward", "f2p_passed", "f2p_total",
                                                "p2p_passed", "p2p_total")}}
    (task["dir"] / "validation.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def is_validated(task):
    try:
        v = json.loads((task["dir"] / "validation.json").read_text())
    except (OSError, ValueError):
        return False
    return (v.get("ok") and v.get("upstream_commit") == task.get("upstream_commit")
            and v.get("image_digest") == task.get("image_digest"))
