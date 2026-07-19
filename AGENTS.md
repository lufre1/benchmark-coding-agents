# AGENTS.md — opencode model/agent testbench

This repo benchmarks opencode agents and open-weight models (SAIA/GWDG provider)
on coding tasks scored by hidden pytest suites.

## Repository structure

- `bench.py` — single-file cli (stdlib only, Python 3.10+): `list`, `status`, `run`, `report`
- `tasks/<name>/` — task definition: `task.json`, `prompt.md`, optional `starter/`, `hidden_tests/`, `reference/`
- `matrix.json` — combo definitions (agent phases + model overrides) and defaults (timeouts, budget floors, provider)
- `runs/` — per-run outputs (gitignored). Each run dir: `workspace/`, `events_p<n>.jsonl`, `result.json`, `junit.xml`
- `systemd/` — user-unit service+timer for scheduled daily campaigns
- `SERVER.md` — server deployment and 24/7 campaign setup

## Key commands

| Command | What it does |
|---|---|
| `python3 bench.py list` | List tasks and combos |
| `python3 bench.py status` | Show SAIA budget + run counts |
| `python3 bench.py run` | Run all tasks × all combos (sequential, budget-gated) |
| `python3 bench.py run --task intervals --combo solo` | One cell of the matrix |
| `python3 bench.py run --agent solo --model glm-4.7` | Ad-hoc model override |
| `python3 bench.py run --repeats 3` | Repeat for noise reduction |
| `python3 bench.py run --dry-run` | Print planned commands, write nothing |
| `python3 bench.py run --parallel N` | Run N cells concurrently (useful N ≈ SAIA keys) |
| `python3 bench.py run --no-wait` | Abort instead of waiting when budget low |
| `python3 bench.py run --no-retry` | Skip automatic retry of provider-invalidated runs |
| `python3 bench.py report` | Regenerate `results.csv` + `report.md` from existing runs |

`bench.py report` runs automatically after `bench.py run` completes.

## How it works

1. Each run creates `runs/<ts>_<task>_<combo>_r<N>/` with a fresh workspace.
2. Starter files (if any) are copied in; agent→model overrides are written to `workspace/opencode.json`.
3. `opencode run --format json --auto <prompt>` is invoked per phase; later phases continue the same session via `-s <session_id>`.
4. Events go to `events_p<n>.jsonl`; tokens/cost/steps come from `step_finish` events.
5. DB subagent usage is aggregated from `opencode.db` (child sessions via `parent_id`).
6. After the agent finishes, `hidden_tests/` are copied in and run with pytest (5s per-test watchdog). JUnit XML gives the score.
7. Everything lands in `result.json`.

## Budget gating

The bench checks `~/.cache/opencode/saia-gwdg-budget.json` before each run. It
blocks (waits 2 min polls) while fewer than `budget_floor_hour` (25) hourly
requests remain across all keys. `--no-wait` aborts instead.

SAIA key rotation (`~/.local/share/opencode/saia-gwdg-keys.json`) — the bench
reads key count from the file but never the key material. Multi-key rotation is
exploited by `--parallel N`.

## Combo definitions (`matrix.json`)

- `solo` — single agent with its configured models + debugger validation
- `auto` — orchestrator with subagents (researcher/coder/coder2/debugger)
- `plansolo` — `plan` agent (read-only: edit/write/bash/task denied), then `solo` implements
- `planbuild` — `plan` agent, then `build` agent continues the session
- `solo-dsv4`, `planbuild-dsv4` — variants pinned to deepseek-v4-flash

All combos use `auto_approve: true` (headless, no confirmation prompts).

**Global YAGNI instruction:** since 2026-07-16, `~/.config/opencode/opencode.jsonc`
appends `~/.config/opencode/yagni.md` (a YAGNI-first principle) to the system
prompt of *every* agent via the top-level `instructions` field. Runs from that
date onward are not comparable with earlier ones.

## Adding a task

Create `tasks/<name>/` with:
- `task.json` — `{name, description, timeout_s, expects: [deliverable files]}`
- `prompt.md` — exactly what the agent sees
- `starter/` — optional buggy code the agent must fix
- `hidden_tests/` — pytest suite (never visible to the agent during the run)
- `reference/` — known-good solution (validates hidden tests)

Hidden tests must pass against reference before the task is ready.

## Result classification

Runs flagged `invalid` are excluded from aggregate scores. Invalid causes:
- `agent_fallback` — agent not found on first attempt
- `provider_error` — SAIA 5xx / server error / overloaded
- `budget_exhausted` — all SAIA keys nearly exhausted
- `stalled` — event stream made no progress for `stall_timeout_s` (300s)
- `no_steps` — agent completed 0 steps
- `expected_agent_missing_in_db` — phase agent not found in DB usage

Invalid runs get one automatic retry (unless `--no-retry`).

## Task details

| Task | Type | Expects | Description |
|---|---|---|---|
| `csv-bugfix` | Debugging (medium) | `csvstats.py` | Fix 4 planted bugs from user bug reports |
| `intervals` | Greenfield (easy-medium) | `intervals.py` | Half-open interval set (merge/split/query) |
| `ratelimit` | Greenfield (medium) | `ratelimit.py` | Token-bucket rate limiter with injectable clock, per-key state |
| `spreadsheet` | Greenfield (hard) | `spreadsheet.py` | Formula parser, ranges, dependency graph, cycle detection |
| `minilang` | Greenfield (very hard) | `interp.py` | Tree-walking interpreter: lexer, recursive-descent parser, closures, scoping, error taxonomy |

## Security note

`tasks/*/hidden_tests/` and `tasks/*/reference/` are part of this repo. Keep
the repo out of any directory an agent under test can read — hidden tests are
only copied into the workspace *after* the agent finished.
