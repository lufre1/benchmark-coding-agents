#!/usr/bin/env bash
set -euo pipefail

TASK=minilang2
ISSUES_FILE=tasks/minilang2/solo_issues.md
REPEATS=3

COMBOS=(
  solo-coder
  solo-dsv4
  solo-qwen36
  solo-qwen35
  solo-devs
  planbuild-ds4-coder
)

get_models() {
  python3 -c "
import json, sys
with open('matrix.json') as f:
    m = json.load(f)
cname = sys.argv[1]
c = m['combos'][cname]
models = c.get('models', {})
phases = [p['agent'] for p in c.get('phases', [{'agent':'solo'}])]
parts = []
for p in phases:
    m = models.get(p, 'default')
    parts.append(f'{p}={m}')
print(' '.join(parts))
" "$1"
}

write_issue_file_header() {
  echo "# solo × minilang2 issue log" > "$ISSUES_FILE"
  echo "" >> "$ISSUES_FILE"
  echo "Started: $(date -u)" >> "$ISSUES_FILE"
  echo "" >> "$ISSUES_FILE"
  echo "| Combo | Models | Repeat | Issue | Details |" >> "$ISSUES_FILE"
  echo "|---|---|---|---|---|" >> "$ISSUES_FILE"
}

write_issue_file_header

log_issue() {
  local combo="$1" r="$2" issue_type="$3" details="$4"
  local models
  models=$(get_models "$combo")
  echo "| $combo | $models | r$r | $issue_type | $details |" >> "$ISSUES_FILE"
}

run_combo() {
  local combo="$1" r="$2"
  echo ""
  echo "--- Repeat $r / $REPEATS ---"

  while true; do
    echo "Running: bench.py run --task $TASK --combo $combo --repeats 1 --no-retry"

    set +e
    output=$(python3 bench.py run --task "$TASK" --combo "$combo" --repeats 1 --no-retry 2>&1)
    exit_code=$?
    set -e

    run_dir=$(ls -td runs/*"${TASK}_${combo}"* 2>/dev/null | head -1)

    if [ -z "$run_dir" ]; then
      echo "ERROR: No run directory found."
      log_issue "$combo" "$r" "no_run_dir" "Exit code: $exit_code"
      echo "Restarting..."
      continue
    fi

    result_file="$run_dir/result.json"
    if [ ! -f "$result_file" ]; then
      echo "ERROR: No result.json found."
      log_issue "$combo" "$r" "no_result_json" "result.json missing"
      echo "Restarting..."
      continue
    fi

    invalid_cause=$(python3 -c "
import json
with open('$result_file') as f:
    r = json.load(f)
cause = r.get('invalid_cause', '') or ''
print(cause)
")

    score=$(python3 -c "
import json
with open('$result_file') as f:
    r = json.load(f)
print(r.get('score', 'N/A'))
")

    if [ -n "$invalid_cause" ]; then
      echo "INVALID RUN (cause: $invalid_cause). Restarting..."
      log_issue "$combo" "$r" "${invalid_cause}" "Score: $score. Dir: $(basename $run_dir)"
      rm -rf "$run_dir"
      continue
    fi

    echo "VALID run. Score: $score"
    break
  done
}

for combo in "${COMBOS[@]}"; do
  echo ""
  echo "========================================================================"
  echo "COMBO: $combo ($(get_models "$combo"))"
  echo "========================================================================"

  for r in $(seq 1 $REPEATS); do
    run_combo "$combo" "$r"
  done
done

echo ""
echo "========================================================================"
echo "ALL DONE"
echo "========================================================================"
echo "Issues logged to: $ISSUES_FILE"
echo ""

python3 -c "
import json, os, re

runs = [d for d in os.listdir('runs') if 'minilang2' in d]
by_combo = {}
for d in runs:
    m = re.search(r'minilang2_(.+?)_r(\d+)$', d)
    if not m: continue
    by_combo.setdefault(m.group(1), []).append(d)

print('# Minilang2 Solo Campaign Results')
print()
print('| Combo | Valid/3 | Scores | Wall | API Req | In Tokens |')
print('|---|---:|---:|---:|---:|---:|')

total_wall = 0
total_steps = 0
total_in = 0
for c in sorted(by_combo.keys()):
    dirs = sorted(by_combo[c])
    vals = []
    for d in dirs:
        rf = f'runs/{d}/result.json'
        if not os.path.exists(rf): continue
        data = json.load(open(rf))
        ev = data.get('eval', {}) or {}
        totals = data.get('totals', {}) or {}
        passed = ev.get('passed', '?')
        total = ev.get('tests_total', '?')
        wall = data.get('wall_s', 0)
        steps = totals.get('steps', 0)
        tokens_in = totals.get('tokens', {}).get('input', 0) or 0
        vals.append(f'{passed}/{total} ({wall}s, {steps}req)')
        total_wall += wall
        total_steps += steps
        total_in += tokens_in
    print(f'| {c} | {sum(1 for d in dirs if os.path.exists(f\"runs/{d}/result.json\"))}/3 | {\", \".join(vals)} | {sum([json.load(open(f\"runs/{d}/result.json\")).get(\"wall_s\",0) for d in dirs if os.path.exists(f\"runs/{d}/result.json\")]):.0f}s | {sum([json.load(open(f\"runs/{d}/result.json\")).get(\"totals\",{}).get(\"steps\",0) for d in dirs if os.path.exists(f\"runs/{d}/result.json\")])} | {sum([json.load(open(f\"runs/{d}/result.json\")).get(\"totals\",{}).get(\"tokens\",{}).get(\"input\",0) or 0 for d in dirs if os.path.exists(f\"runs/{d}/result.json\")]):,} |')

print(f'| **Total** | | | {total_wall:.0f}s | {total_steps} | {total_in:,} |')
" > /home/cloud/benchmark-coding-agents/tasks/minilang2/solo_results.md

echo "Preliminary results: tasks/minilang2/solo_results.md"
