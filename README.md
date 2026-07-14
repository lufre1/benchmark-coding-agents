# opencode model/agent testbench

Benchmarks opencode agents and open-weight models (GWDG SAIA provider) on coding
tasks with hidden test suites.

## Usage

```bash
python3 bench.py list                                  # tasks, combos, models
python3 bench.py status                                # SAIA budget + run counts
python3 bench.py run --dry-run                         # show what would run
python3 bench.py run                                   # all tasks x all combos
python3 bench.py run --task intervals --combo solo     # one cell of the matrix
python3 bench.py run --agent solo --model glm-4.7      # ad-hoc model override
python3 bench.py run --repeats 3                       # repeat for noise
python3 bench.py report                                # regenerate results.csv + report.md
```

Runs are sequential by default and budget-gated: before each run the SAIA request
budget (`~/.cache/opencode/saia-gwdg-budget.json`) is checked and the bench waits
while fewer than `budget_floor_hour` hourly requests remain (`--no-wait` aborts
instead). The gate aggregates across all keys in rotation.

## Multiple SAIA keys

The opencode plugin rotates API keys (extras in
`~/.local/share/opencode/saia-gwdg-keys.json`, format `{"keys": ["<key2>"]}`),
failing over per request when a key's bucket empties. The bench exploits this two
ways: budget exhaustion is classified as a retryable pacing event
(`budget_exhausted` flag → cooldown + retry round), and `run --parallel N` runs up
to N cells concurrently — useful N ≈ number of keys. Caveat: overlapping runs
share the budget counters, so parallel runs report request counts from opencode's
DB instead of budget deltas (`~N` in the report).

## How a run works

1. A fresh workspace is created under `runs/<ts>_<task>_<combo>_r<n>/workspace/`,
   starter files (if any) are copied in, and agent→model overrides from the combo
   are written to a workspace `opencode.json` (merges over your global config).
2. Each combo phase invokes `opencode run --dir <workspace> --agent <agent>
   --format json --auto <prompt>`; later phases continue the same session
   (that is how `planbuild` chains the built-in plan and build agents).
3. Events are captured to `events_p<n>.jsonl`; `step_finish` events are summed for
   tokens/cost/steps, and subagent usage is aggregated from `opencode.db`
   (child sessions via `parent_id`) into `db_usage`.
4. The task's `hidden_tests/` (never visible to the agent) are copied in and run
   with pytest; the junit XML gives the score.
5. Everything lands in `result.json`; workspaces are kept for inspection.

## Anatomy of a task

```
tasks/<name>/
  task.json        # {name, description, timeout_s, expects: [deliverable files]}
  prompt.md        # exactly what the agent sees
  starter/         # optional: files pre-copied into the workspace (e.g. buggy code)
  hidden_tests/    # pytest/unittest suite, copied in only AFTER the run
  reference/       # known-good solution used to validate the hidden suite (never used in runs)
```

To add a task: create that layout, verify `hidden_tests` pass against `reference/`,
and it is picked up automatically.

## Combos (matrix.json)

A combo is a list of phases (`[{agent, prompt?}]` — no prompt means the task
prompt) plus an agent→model override map. Invalid runs (agent fallback, zero
steps) are flagged and marked `invalid` in results.
