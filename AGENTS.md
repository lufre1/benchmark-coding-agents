# AGENTS.md — coding-agent testbench (opencode + 6 more agents on GWDG SAIA)

This repo benchmarks coding agents (scaffolds) on coding tasks scored by hidden
test suites. Since 2026-10 the main comparison is **7 agent CLIs × one pinned
model** (SAIA `deepseek-v4-flash-0731`) on a validated **DeepSWE v1.1** subset
plus the in-house tasks. The original opencode-only matrix still runs as the
"legacy" path.

## Repository structure

- `bench.py` — CLI (stdlib only, Python 3.11+): `list`, `status`, `run`, `report`, `import-deepswe`, `pull-deepswe`, `validate-deepswe`, `gc`
- `agents.py` — one adapter per agent harness: config (via the `~` SAIA installers), headless argv, output parsing
- `executors.py` — where an agent runs: `DockerExecutor` (default) or `HostExecutor` (scratch dir, tests/pilots)
- `saia_gateway.py` — local OpenAI-compatible gateway every agent uses (keys, pacing, model pin, per-run accounting)
- `deepswe.py` — DeepSWE import, image pull, official collect + grading, oracle/null validation
- `toolbox/build-toolbox.sh` — builds `~/.local/share/bench-toolbox`, mounted read-only at `/opt/agents` in agent containers
- `tasks/<name>/` — task definition: `task.json`, `prompt.md`, optional `starter/`, `hidden_tests/`, `reference/`; DeepSWE tasks are `tasks/deepswe-<id>/` (generated)
- `matrix.json` — combos (legacy opencode phases/models, or `"agent": <harness>`) and defaults
- `runs/` — per-run outputs (gitignored): `result.json`, `events_p<n>.jsonl`, `gateway.jsonl`, `gw_transcript.jsonl.gz`, `gateway_summary.json`, `agent/` (trajectories), `model.patch`/`verifier/` (DeepSWE) or `workspace/` + `junit.xml` (in-house)
- `tests/` — bench self-tests (`python3 -m pytest -q`), `fake_llm.py`, `smoke_adapters.py`
- `systemd/` — `saia-gateway.service`, campaign service+timer, watchdog
- `SERVER.md` — server deployment and campaign setup

## Key commands

| Command | What it does |
|---|---|
| `python3 bench.py list` | Tasks (kind, subsets) and combos |
| `python3 bench.py status` | Merged SAIA budget (plugin + gateway, dead keys = 0), gateway health, run counts |
| `python3 bench.py run --subset smoke --combo mini-ds` | DeepSWE smoke tier with one agent |
| `python3 bench.py run --subset smoke core --combo oc-planbuild-ds aider-ds mini-ds openhands-ds omp-ds pi-ds mcode-ds` | The Core campaign (DeepSWE) |
| `python3 bench.py run --subset inhouse --combo mini-ds --parallel 3` | In-house tasks for an agent |
| `python3 bench.py run --harness pi --task intervals --executor host` | Ad-hoc harness run on the host (pilot/debug) |
| `python3 bench.py run --task intervals --combo planbuild-dsv4` | Legacy opencode cell (host, global config + plugin) |
| `python3 bench.py run --dry-run ...` | Print planned (docker) commands, write nothing |
| `python3 bench.py import-deepswe [--id <reserve>]` | Import the pinned DeepSWE subset into `tasks/` |
| `python3 bench.py import-deepswe --n-tasks 12 --sample-seed 0` | Seeded random sample of all 113 tasks (pier's algorithm on sorted ids), subset `seed0` |
| `python3 bench.py pull-deepswe` / `validate-deepswe` | Pre-pull images / oracle=1, null=0 gate (required before runs) |
| `python3 bench.py gc` | Remove orphaned bench containers |
| `python3 bench.py report` | Regenerate `results.csv` + `report.md` |
| `python3 saia_gateway.py probe-context` | One oversized request → model context limit |
| `python3 -m pytest -q` / `python3 tests/smoke_adapters.py` | Self-tests / all 7 adapters end-to-end vs. a fake LLM (0 SAIA requests) |

`bench.py report` runs automatically after `bench.py run` completes.

## How an agent run works (`"agent"` combos)

1. Budget gate, then the run is registered with the gateway → per-run token, request cap (150), canary string.
2. Executor starts: for DeepSWE a container of the task image pinned by digest (repo at `/app`, default branch at the base commit); for in-house tasks a mars-base container with the starter as a fresh git repo. Internal network `bench-agents`; the only reachable host is the `saia-gw` relay → host gateway. Toolbox at `/opt/agents` (ro). 5 GB / 2 CPUs.
3. The agent's `~` SAIA installer runs **inside** the fresh home with `SAIA_BASE_URL=http://saia-gw:8787/v1` and the run token as key; the adapter overlays bench settings (step caps, context limit, every model role → the pinned model). opencode instead gets an isolated config (gateway provider, `--pure`, no plugin, **no YAGNI instructions**, plan read-only).
4. Phases run via `docker exec` with an allowlisted env (never the bench's env — `~/.bashrc` exports a real key). Stall detection = no stdout growth **and** no gateway activity.
5. DeepSWE: the upstream `[[verifier.collect]]` (`git diff --binary <base> HEAD`, committed work only) → `model.patch`; then upstream `tests/test.sh` + `grader.py` **verbatim** in a fresh `--network none` container → `reward.json`. `worktree.patch` (incl. uncommitted work) is graded too as `reward_worktree` (diagnostic only). In-house: workspace copied out and scored by `evaluate()`.
6. Everything lands in `result.json` (schema 2): gateway summary (requests, upstream attempts, tokens, ttft, causes, requested models, canary hits), adapter-parsed steps/tool calls, collect diagnostics + patch stats, eval, toolbox manifest.

Legacy combos (no `"agent"` key) keep the old flow: `opencode run --format json --auto` on the host with the global opencode config + SAIA plugin — but the workspace now lives in `/var/tmp/bench-ws/<run_id>/` (own git repo), runs with `cwd` set and an allowlisted env, and is archived into the run dir.

## SAIA gateway (`saia_gateway.py`, systemd user unit `saia-gateway`)

- Keys: `auth.json` + `saia-gwdg-keys.json` in the plugin's order and labels; agents never see them.
- Mirrors the plugin: ≥2.1 s between request starts per key, floors hour 5 / day 10 / month 30, 429 → wait `ratelimit-reset` once then fail over, 401/403 → key dead (persisted), 3 consecutive 5xx → 30 s pause, 90 s stream idle. Unlike the plugin: **no model substitution**, no resume injection, transparent retries only before the first byte (identical transport for all agents), LRU key choice for parallel runs.
- Pins `model` to `deepseek-v4-flash-0731` (logs `requested_model`), answers `/v1/models` locally, strips `x-ratelimit-*`, injects `stream_options.include_usage` (auto-disabled if SAIA rejects it).
- Per run: request cap → HTTP 400 `request_cap` (never reaches SAIA), JSONL log, de-duplicated transcript, optional seeded fault injection (`fault_profile: {seed, p429, p503, p_cut}`), canary scan.
- Budget snapshot `~/.cache/saia-gateway/budget.json` (plugin schema + `dead`); `bench.py` merges it with the plugin's file.
- Context probe 2026-10-05: SAIA accepted a 600,005-token prompt → `context_window: 600000` (verified lower bound).
- Forced request params (`defaults.gateway_params`, per-combo override): `reasoning_effort: medium`, `max_completion_tokens: 32768`, `max_tokens` stripped — identical model settings for all agents. History: agents sent different efforts (omp high, mcode medium, others none); forcing `high` made deepseek reason through the whole 16k/32k output with no answer (pi `stopReason: length`, mcode `EMPTY_RESPONSE`, aider 32,768 reasoning tokens), so the smoke tier was re-run twice (archived in `runs/_smoke-v1-*`, `runs/_smoke-v2-*`).
- Slow-stream guard: a stream delivering < 1 KB/s after 2 min, or running > 15 min, is aborted (`stream_too_slow`; SAIA replicas can trickle ~1 token/s for half an hour). Per-run counters are rebuilt from `gateway.jsonl` after a gateway restart.
- `/_bench/health` reports the upstream attempt success ratio over the last 15/30/60 min.

## SAIA health gating

SAIA degrades for hours at a time (2026-10-05/06: 0–30% of attempts succeeding overnight), and **failed attempts are charged**. Before each run `health_gate` waits while < 50% of the gateway's attempts in the last 15 min succeeded (probing with one tiny request every 10 min, giving up after 6 h). During a run, `outage_check` (polled every 60 s) kills the agent if < 20% of ≥ 10 attempts succeeded in the last 15 min → flag `provider_outage_p<n>` (invalid, retried later). Thresholds: `defaults.health_gate`, `defaults.outage_abort`.

## Budget gating

`budget_gate` blocks (2 min polls, up to 90 min) while fewer than `budget_floor_hour` (25) hourly requests remain across live keys; dead keys count as 0, exhausted buckets as 0 until their TTL. `--no-wait` aborts instead. Limits per key: 30/min, 200/hour, 1000/day, **3000/month** — the monthly bucket is what bounds the campaign (3 live keys ≈ 9k/month; key1 is dead since 2026-10-05).

## Combo definitions (`matrix.json`)

Agent combos (all `deepseek-v4-flash-0731`, `request_cap: 150`):
`oc-planbuild-ds` (opencode plan 40 steps read-only → build 110 steps), `aider-ds`, `mini-ds`, `openhands-ds`, `omp-ds`, `pi-ds`, `mcode-ds`.

Legacy opencode combos: `solo`, `auto`, `plansolo` (need the solo/auto agents from `~/opencode-extras`, currently not installed), `planbuild*`, `solo-*`. Combos pinned to models SAIA no longer serves are `"retired": true` and skipped by default. **The plugin's config hook overrides combo model pins** (observed all-or-nothing in 158/183 old runs) — legacy runs whose DB usage shows another model get `model_substituted`.

## DeepSWE subset (v1.1, upstream `datacurve-ai/deep-swe@0b9fabbb`)

Chosen from the published `trials.json` (31,617 rollouts): excluded the 23 Epoch-AI-flagged false-negative tasks and 13 non-discriminative ones; DeepSeek-V4-flash (mini-swe-agent) solved 1–3/4 (anchors 4/4); ≤ ~135 median steps; small images; 4 Python / 4 TypeScript / 4 Go.

- smoke: `ofetch-per-origin-circuit-breaker`, `wazero-multi-module-snapshots`, `aiomonitor-task-snapshots-diff`
- core: aiomonitor + `httpx-multipart-response-parsing`, `bandit-incremental-cache-control`, `dateutil-rfc5545-timezone-interop`, `koota-entity-snapshot-rollback`, `sql-formatter-bigquery-pipe-formatting`, `cliffy-config-file-parsing`, `scc-bounded-memory-spilling`, `tengo-callable-instance-isolation`, `dasel-html-document-format`
- seeded alternative: `--n-tasks N --sample-seed S` = pier's `random.Random(S).shuffle` → first N, but over **sorted** ids (pier shuffles unsorted `iterdir()` order, so its own seed-0 picks vary by machine). Unlike the curated subset it can include Epoch-flagged and expensive tasks; validate before running.
- reserves (`import-deepswe --id ...`): mobly-grouped-test-barriers, ipython-session-bundle-replay, abs-stepped-slices, prometheus-typed-label-sorting, testem-per-launcher-reports, kysely-window-grouping-helpers, fd-deterministic-multi-key-sorting

Per-task reference results (`reference_runs` in task.json) feed the report's calibration table for `mini-ds`. Deviations from upstream: 5 GB memory cap (host has 7.8 GB; up to `deepswe.max_parallel: 2` runs at once — real use is ~0.5–1 GB each), 5400 s agent timeout, 150-request cap, forced `reasoning_effort: medium` + 32k output.

## Adding a task

In-house: `tasks/<name>/` with `task.json` (`{name, description, timeout_s, expects, subsets}`), `prompt.md`, optional `starter/`, `hidden_tests/`, `reference/`. Hidden tests must pass against reference and fail on the starter/empty workspace. DeepSWE: add the id to `deepswe.SUBSET` (or use `--id`), import, validate.

## Result classification

Runs flagged `invalid` are excluded from aggregate scores:
- gateway runs: `no_requests`, `provider_error` (last request or >20% failed upstream), `provider_outage_p<n>` (aborted during a SAIA outage), `budget_exhausted`, `stalled` (gateway had a stuck request), `verifier_crash`, `harness_error`, `gateway_summary_missing`, `infra_slow_stream` (manual)
- legacy runs: `agent_fallback`, `provider_error`, `budget_exhausted`, `stalled`, `no_steps`, `expected_agent_missing_in_db`
- retro (old runs): `read_hidden` (tool calls read `tasks/*/hidden_tests|reference`; 73 runs), `model_substituted`, `contaminated_hidden_tests` (minilang2 from 2026-07-20: a full solution sat in `hidden_tests/`)

Recorded but valid: `request_cap`, `idle_kill` (agent hung itself), `timeout_p<n>`, `model_rewritten`, `canary_read`, `uncommitted_changes`, `commits_not_on_head`, `collect_failed`, `fault_injected`.

Invalid runs are retried up to 3 times with 10/30/60 min backoff (unless `--no-retry`; harness errors are not retried).

## Task details (in-house)

| Task | Type | Expects | Subset |
|---|---|---|---|
| `csv-bugfix` | Debugging (medium) | `csvstats.py` | inhouse |
| `intervals` | Greenfield (easy-medium) | `intervals.py` | inhouse |
| `ratelimit` | Greenfield (medium) | `ratelimit.py` | inhouse |
| `minilang` | Greenfield (very hard) | `interp.py` | inhouse |
| `minilang2` | Greenfield (expert) | `interp.py` | — (≈130 requests/run) |
| `spreadsheet` | Greenfield (hard) | `spreadsheet.py` | — (no reference) |

## Security / integrity

- Agents never run inside this repo: containers see only `/app`, `/agent` and `/opt/agents`; host runs use `/var/tmp/bench-ws/<run_id>/` with a fresh HOME. Agent envs are allowlisted; agents get per-run gateway tokens only.
- `evaluate()` scores a clean copy: agent `conftest.py`/`pytest.ini`/`pyproject.toml`/`setup.cfg`/`tox.ini`/`sitecustomize.py`/`*.pth` are dropped, pytest uses a bench-owned ini, hidden-test files named like a deliverable are never copied and workspace files named like hidden-test helpers are removed.
- A canary "solution" is planted outside the workdir; its marker in any LLM request flags `canary_read`.
- Never commit agent output from a run into `tasks/` (it happened: `a07f09c` committed an agent-fixed csv starter, `d20c1ea` a solution into `minilang2/hidden_tests/`).
