#!/bin/bash
#
# campaign.sh — the canned benchmark campaign: full matrix x 3 repeats, then
# the report. Designed to run under a systemd timer: an flock guard makes
# overlapping firings a no-op, output appends to campaign.log, and a nonzero
# exit surfaces failures in systemctl status.
#
# Usage: ./campaign.sh [--dry-run]
#   CAMPAIGN_ARGS extra bench.py run flags, e.g. CAMPAIGN_ARGS="--parallel 2"
#   (parallel trades per-run budget-delta accounting for wall-clock speed).
#
set -euo pipefail
cd "$(dirname "$0")"

exec 9>.campaign.lock
if ! flock -n 9; then
    echo "$(date -Is) campaign already running — skipping this firing" | tee -a campaign.log
    exit 0
fi

# Protect this process from OOM killer — lower oom_score_adj so the kernel
# prefers to kill other processes (like LLM subprocesses) before the bench.
if [ -w /proc/self/oom_score_adj ]; then
    echo -500 > /proc/self/oom_score_adj
fi

{
    echo "$(date -Is) campaign start (args: --repeats 3 ${CAMPAIGN_ARGS:-} $*)"
    free -h | tee -a campaign.log
    # shellcheck disable=SC2086
    python3 bench.py run --repeats 3 ${CAMPAIGN_ARGS:-} "$@"
    rc=$?
    if [[ "$*" != *--dry-run* ]]; then
        python3 bench.py report
    fi
    echo "$(date -Is) campaign complete (exit code $rc)"
    free -h | tee -a campaign.log
} 2>&1 | tee -a campaign.log
exit "${rc}"
