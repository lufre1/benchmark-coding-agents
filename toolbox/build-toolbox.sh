#!/usr/bin/env bash
#
# build-toolbox.sh — build the agent toolbox that every agent container mounts
# read-only at /opt/agents.
#
# All DeepSWE images are FROM mars-base (Debian bookworm, glibc 2.36), so the
# toolbox is built for, and checked inside, that base:
#   * portable host installs are copied as-is (same versions as on this host):
#     opencode + rg (bun single binary), omp (bun), OpenHands (PyInstaller),
#     pi (relocatable node app; needs the image's node), mcode (own node runtime)
#   * Python agents are reinstalled with uv-managed Python under /opt/agents
#     (their host venvs point at host-only interpreters): aider, mini-swe-agent
#   * the six SAIA installers from ~ (run per run, inside the container, to
#     write each agent's config against the gateway)
#   * pytest wheels (in-house tasks install pytest offline)
#
# Network is used at build time only (uv/pip downloads). Re-run after updating
# an agent on the host; every result.json records toolbox/manifest.json.
#
#   bash toolbox/build-toolbox.sh            # -> ~/.local/share/bench-toolbox
#
set -euo pipefail
OUT="${BENCH_TOOLBOX:-$HOME/.local/share/bench-toolbox}"
BASE="${BASE_IMAGE:-public.ecr.aws/x8v8d7g8/mars-base:latest}"
AIDER_VERSION="${AIDER_VERSION:-$("$HOME/.local/bin/aider" --version 2>/dev/null | awk '{print $2}')}"
MINI_VERSION="${MINI_VERSION:-$("$HOME/.local/bin/mini" --help 2>/dev/null | grep -oE 'version [0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d' ' -f2)}"
AIDER_VERSION="${AIDER_VERSION:-0.86.2}"
MINI_VERSION="${MINI_VERSION:-2.4.6}"

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "ERROR: docker not usable (sudo usermod -aG docker $USER, then log in again)" >&2; exit 1; }

echo "toolbox -> $OUT (base $BASE; aider $AIDER_VERSION, mini-swe-agent $MINI_VERSION)"
rm -rf "$OUT.new"
mkdir -p "$OUT.new"/{bin,opt,installers,wheels}
T="$OUT.new"

# ── portable host installs ───────────────────────────────────────────
cp "$HOME/.opencode/bin/opencode" "$T/bin/opencode"
cp "$HOME/.cache/opencode/bin/rg" "$T/bin/rg"
cp "$HOME/.local/bin/omp" "$T/bin/omp"
cp "$HOME/.local/bin/openhands" "$T/bin/openhands"
cp "$HOME/.local/bin/uv" "$T/bin/uv"

# pi: launcher + managed releases only (never auth.json / sessions / settings)
mkdir -p "$T/opt/pi"
cp -a "$HOME/.pi/agent/bin" "$HOME/.pi/agent/install" "$T/opt/pi/"
ln -s ../opt/pi/bin/pi "$T/bin/pi"

# mcode: bundled node runtime + current release; the stock launcher hard-codes
# /home/<user>/.minimax-code, so write our own
MC_RELEASE="$(tr -d '\r\n' < "$HOME/.minimax-code/current")"
MC_NODE="$(basename "$(ls -d "$HOME"/.minimax-code/runtime/node-v*-linux-x64 | head -1)")"
mkdir -p "$T/opt/minimax-code/releases" "$T/opt/minimax-code/runtime"
cp -a "$HOME/.minimax-code/releases/$MC_RELEASE" "$T/opt/minimax-code/releases/"
cp -a "$HOME/.minimax-code/runtime/$MC_NODE" "$T/opt/minimax-code/runtime/"
cat > "$T/bin/mcode" <<EOF
#!/bin/sh
exec /opt/agents/opt/minimax-code/runtime/$MC_NODE/bin/node \\
  /opt/agents/opt/minimax-code/releases/$MC_RELEASE/lib/node_modules/@minimax-ai/code/cli.js "\$@"
EOF
chmod +x "$T/bin/mcode"

# SAIA installers (the built single-file ones; each packs its src/)
for repo in aider-saia-gwdg mcode-saia mini-swe-agent-saia-gwdg omp-saia-gwdg \
            openhands-saia-gwdg pi-saia-gwdg; do
  mkdir -p "$T/installers/$repo"
  cp "$HOME/$repo"/install-*.sh "$T/installers/$repo/"
  (cd "$HOME/$repo" && git describe --always --dirty 2>/dev/null || echo unknown) \
    > "$T/installers/$repo/REVISION"
done

# ── Python agents + pytest wheels, built inside mars-base ────────────
# Same absolute prefix as at run time (/opt/agents), so venv shebangs work.
# Reuse the host's uv-managed CPython (python-build-standalone, relocatable)
# instead of downloading it again; uv falls back to a download if absent.
mkdir -p "$T/uv/python"
for py in "$HOME"/.local/share/uv/python/cpython-3.12*-linux-x86_64-gnu; do
  [ -d "$py" ] && cp -a "$py" "$T/uv/python/"
done
# --network host: docker0's MTU (1500) exceeds this VM's NIC MTU (1450), which
# stalls TLS downloads from bridge containers; build-time only.
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e UV_CACHE_DIR=/opt/agents/.uv-cache \
  -e UV_TOOL_DIR=/opt/agents/uv/tools -e UV_TOOL_BIN_DIR=/opt/agents/bin \
  -e UV_PYTHON_INSTALL_DIR=/opt/agents/uv/python \
  -v "$T:/opt/agents" "$BASE" bash -euc "
    /opt/agents/bin/uv tool install --python-preference only-managed --python 3.12 \
      'aider-chat==$AIDER_VERSION'
    /opt/agents/bin/uv tool install --python-preference only-managed --python 3.12 \
      'mini-swe-agent==$MINI_VERSION'
    python3 -m pip download -q -d /opt/agents/wheels pytest
    rm -rf /opt/agents/.uv-cache"

# ── check every agent inside a fresh mars-base container ─────────────
docker run --rm -v "$T:/opt/agents:ro" -e PATH="/opt/agents/bin:/usr/local/bin:/usr/bin:/bin" \
  -e HOME=/tmp -e TMPDIR=/tmp -e MSWEA_CONFIGURED=true -e OPENHANDS_SUPPRESS_BANNER=1 \
  "$BASE" bash -euc '
    v() { printf "\"%s\": \"%s\",\n" "$1" "$(timeout 60 "$@" 2>&1 | grep -oE "[0-9]+\.[0-9]+\.[0-9]+" | head -1)"; }
    {
      echo "{"
      v opencode --version; v aider --version; v mini --help; v openhands --version
      v omp --version; v pi --version; v mcode --version; v rg --version; v uv --version
      printf "\"node\": \"%s\",\n" "$(node --version)"
      printf "\"glibc\": \"%s\"\n" "$(ldd --version | head -1 | grep -oE "[0-9]+\.[0-9]+$")"
      echo "}"
    }' > "$T/versions.json"
python3 - "$T" "$BASE" <<'PY'
import json, sys, datetime, pathlib
t = pathlib.Path(sys.argv[1])
versions = json.loads((t / "versions.json").read_text())
missing = [k for k, v in versions.items() if not v]
manifest = {"built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "base_image": sys.argv[2], "versions": versions,
            "installers": {p.parent.name: p.read_text().strip()
                           for p in sorted((t / "installers").glob("*/REVISION"))}}
(t / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
if missing:
    sys.exit(f"ERROR: no version from: {', '.join(missing)} — agent not runnable in {sys.argv[2]}")
PY
rm -rf "$OUT"
mv "$T" "$OUT"
echo "toolbox ready: $OUT"
