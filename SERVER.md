# Running the testbench on a server (24/7)

## 1. Prerequisites

- **opencode + SAIA config** via the generated installer from the opencode-config repo
  (installs provider, plugin with key rotation, agents, prompts, /usage):

  ```bash
  GWDG_API_KEY=... GWDG_API_KEYS_EXTRA=key2,key3 bash install-auto-mode.sh --yes
  ```

  Keys land outside this repo (`~/.local/share/opencode/auth.json`,
  `~/.local/share/opencode/saia-gwdg-keys.json`) — they are never committed.
- **Python ≥ 3.11** and **pytest** (`pip install --user pytest`).

## 2. Deploy

```bash
git clone <your-remote>/testbench ~/testbench && cd ~/testbench
python3 bench.py list            # tasks + combos visible
python3 bench.py status          # keyring-aggregated SAIA budget
python3 bench.py run --dry-run   # planned commands, writes nothing
python3 bench.py run --task intervals --combo solo   # 1 cheap real cell (~5-10 requests)
python3 bench.py report && cat report.md
```

The systemd unit assumes the repo at `~/testbench`; adjust `WorkingDirectory`/`ExecStart` if elsewhere.

Note: `tasks/*/hidden_tests/` and `tasks/*/reference/` are part of this repo.
Keep the repo out of any directory an agent under test can read — the bench
only copies hidden tests into a workspace *after* the agent finished.

## 3. Schedule the daily campaign (systemd user units, no root)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/opencode-bench.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now opencode-bench.timer
loginctl enable-linger $USER     # keep user units running without an SSH session
```

The campaign is the full matrix × 3 repeats. Since the agent combos and DeepSWE tasks
were added, the *full* matrix is far beyond the SAIA monthly budget: always restrict it,
e.g. `CAMPAIGN_ARGS="--subset inhouse --combo planbuild-dsv4"` in the service unit. The budget gate
paces it across budget days automatically; the flock in campaign.sh makes an
overlapping timer firing a no-op.

Watch it:

```bash
systemctl --user list-timers opencode-bench.timer
journalctl --user -u opencode-bench -f     # or: tail -f ~/testbench/campaign.log
python3 bench.py status
```

One-off manual campaign: `nohup ./campaign.sh &` (same lock applies).
Faster, at the cost of per-run budget-delta accounting: `CAMPAIGN_ARGS="--parallel 2" ./campaign.sh`.

## 4. Getting results back

Run directories are self-contained and merge by copying — from your workstation:

```bash
rsync -a server:testbench/runs/ ~/Documents/test/testbench/runs/
python3 bench.py report          # combines local + server data
```

Quick look without merging: `scp server:testbench/{report.md,results.csv} .`

## 5. Budget notes

- Buckets per key: 30/min, 200/hour, 1000/day, 3000/month. The plugin rotates
  keys per request; the bench gate aggregates remaining budget across the keyring
  (`budget_floor_hour: 25` in matrix.json).
- Interrupted runs (SAIA 5xx, hangs, budget exhaustion) are flagged, excluded
  from scores, and retried once per invocation; see README.md for the flag
  semantics and report columns.

## 6. Multi-agent campaign (7 agents × DeepSeek × DeepSWE subset)

One-time setup:

```bash
sudo usermod -aG docker $USER        # then log out/in (or reboot) so the user manager has the group
docker info >/dev/null && echo docker ok
cp systemd/saia-gateway.service ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now saia-gateway     # listens on 127.0.0.1:8787 and 172.17.0.1:8787
bash toolbox/build-toolbox.sh                  # agents for /opt/agents, built + checked in mars-base
python3 bench.py import-deepswe                # 12 tasks (smoke + core), images pinned by digest
python3 bench.py pull-deepswe                  # ~0.7 GB shared base + ~0.1 GB per task (compressed)
python3 bench.py validate-deepswe              # oracle must score 1, untouched repo 0 — no SAIA cost
python3 -m pytest -q && python3 tests/smoke_adapters.py   # 0 SAIA requests
```

Stop other SAIA consumers first (`systemctl --user stop opencode-bench.timer
opencode-bench-watchdog.timer`; interactive opencode sessions share the keys).

Rollout (requests are estimates; the hard cap is 150 per run):

| step | command | runs | ≈ requests |
|---|---|---|---|
| pilot | `bench.py run --task intervals --combo oc-planbuild-ds aider-ds mini-ds openhands-ds omp-ds pi-ds mcode-ds` | 7 | 200 |
| in-house | `bench.py run --subset inhouse --combo <7 combos> --parallel 3` | 28 | 900 |
| smoke | `bench.py run --subset smoke --combo <7 combos>` | 21 | 1,900 |
| core | `bench.py run --subset core --combo <7 combos>` — re-runs aiomonitor (a 2nd sample); pass the 9 other core tasks via `--task` to skip it | 70 (63) | 8,400 (7,600) |

DeepSWE runs execute one at a time (5 GB container + 5 GB verifier, host has 7.8 GB),
30–60 min each plus grading. Gate the core tier on a clean smoke tier: every agent
produced commits (`model.patch` non-empty), no infra flags, and `mini-ds` close to
the published DeepSeek-flash results (report: "Calibration").
