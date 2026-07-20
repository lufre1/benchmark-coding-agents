#!/usr/bin/env bash
set -euo pipefail

TASK=minilang2
COMBO_FILE=/tmp/planbuild_combos.txt
ISSUES_FILE=tasks/minilang2/planbuild_issues.md
REPEATS=3

COMBOS=(
  planbuild
  planbuild-dsv4
  planbuild-ds4-coder
  planbuild-p_qwen35-b_qwen36
  planbuild-p_qwen35-b_coder
  planbuild-p_qwen35-b_dsv4
  planbuild-p_qwen35-b_glm47
  planbuild-p_mistral-b_qwen36
  planbuild-p_mistral-b_coder
  planbuild-p_mistral-b_dsv4
  planbuild-p_mistral-b_glm47
  planbuild-p_coder-b_qwen36
  planbuild-p_coder-b_coder
  planbuild-p_coder-b_dsv4
  planbuild-p_coder-b_glm47
)

# Helper to get model string for a combo
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

echo "# planbuild × minilang2 issue log" > "$ISSUES_FILE"
echo "" >> "$ISSUES_FILE"
echo "Started: $(date -u)" >> "$ISSUES_FILE"
echo "" >> "$ISSUES_FILE"
echo "| Combo | Models | Repeat | Issue | Details |" >> "$ISSUES_FILE"
echo "|---|---|---|---|---|" >> "$ISSUES_FILE"

log_issue() {
  local combo="$1" r="$2" issue_type="$3" details="$4"
  local models
  models=$(get_models "$combo")
  echo "| $combo | $models | r$r | $issue_type | $details |" >> "$ISSUES_FILE"
}

for combo in "${COMBOS[@]}"; do
  echo ""
  echo "========================================================================"
  echo "COMBO: $combo ($(get_models "$combo"))"
  echo "========================================================================"

  for r in $(seq 1 $REPEATS); do
    echo ""
    echo "--- Repeat $r / $REPEATS ---"

    while true; do
      echo "Running: bench.py run --task $TASK --combo $combo --repeats 1 --no-retry"

      set +e
      output=$(python3 bench.py run --task "$TASK" --combo "$combo" --repeats 1 --no-retry 2>&1)
      exit_code=$?
      set -e

      # Find the run directory that was just created (latest)
      run_dir=$(ls -td runs/*"${TASK}_${combo}"* 2>/dev/null | head -1)

      if [ -z "$run_dir" ]; then
        echo "ERROR: No run directory found. Output:"
        echo "$output"
        log_issue "$combo" "$r" "no_run_dir" "No run directory created. Exit code: $exit_code"
        echo "Restarting..."
        continue
      fi

      result_file="$run_dir/result.json"
      if [ ! -f "$result_file" ]; then
        echo "ERROR: No result.json found in $run_dir"
        log_issue "$combo" "$r" "no_result_json" "result.json missing. Run incomplete."
        echo "Restarting..."
        continue
      fi

      # Determine if run is valid — check invalid_cause (string) not the boolean invalid flag
      invalid_cause=$(python3 -c "
import json
with open('$result_file') as f:
    r = json.load(f)
cause = r.get('invalid_cause', '') or ''
print(cause)
")

      # Get score
      score=$(python3 -c "
import json
with open('$result_file') as f:
    r = json.load(f)
print(r.get('score', 'N/A'))
")

      if [ -n "$invalid_cause" ]; then
        echo "INVALID RUN (cause: $invalid_cause). Restarting..."
        log_issue "$combo" "$r" "${invalid_cause}" "Score: $score. Run dir: $(basename $run_dir)"
        rm -rf "$run_dir"
        continue
      fi

      echo "VALID run. Score: $score"
      break
    done
  done
done

echo ""
echo "========================================================================"
echo "ALL DONE"
echo "========================================================================"
echo "Issues logged to: $ISSUES_FILE"
echo ""

# Generate report
python3 bench.py report 2>&1 | tail -5
