#!/bin/bash
#
# campaign-watchdog.sh — detect aborted campaigns and restart them.
#
# Runs as a systemd timer (every 15 min). If campaign.sh is NOT currently
# running but the last campaign.log entry shows it was killed (or campaign
# never completed), re-launch campaign.sh.
#
set -euo pipefail
cd "$(dirname "$0")/.."

CAMPAIGN_LOG="campaign.log"
LOCK=".campaign.lock"
WATCHDOG_STAMP=".watchdog_last_restart"

# If the campaign is currently running, nothing to do.
if flock -n "$LOCK" true 2>/dev/null; then
    # We acquired the lock — no campaign running. Check if restart needed.
    :
else
    echo "$(date -Is) campaign is running — nothing to do"
    exit 0
fi

# Check last 10 lines of campaign.log for "campaign complete" or "killed"
if [ ! -f "$CAMPAIGN_LOG" ]; then
    echo "$(date -Is) no campaign.log yet — nothing to do"
    exit 0
fi

last_complete=$(tac "$CAMPAIGN_LOG" | grep -m1 -o 'campaign complete' || true)
last_killed=$(tac "$CAMPAIGN_LOG" | grep -m1 -o 'Killed' || true)

# If the last campaign completed successfully, nothing to do.
if [ -n "$last_complete" ]; then
    # Make sure "Killed" did NOT appear after the last "campaign complete"
    last_complete_line=$(grep -n 'campaign complete' "$CAMPAIGN_LOG" | tail -1 | cut -d: -f1)
    last_killed_line=$(grep -n 'Killed' "$CAMPAIGN_LOG" | tail -1 | cut -d: -f1 || echo "0")
    if [ "${last_killed_line:-0}" -le "${last_complete_line:-0}" ]; then
        echo "$(date -Is) last campaign completed normally — nothing to do"
        exit 0
    fi
fi

# If we get here, the last campaign was killed or incomplete. Restart it.
# Throttle: don't restart more than once per 2 hours.
if [ -f "$WATCHDOG_STAMP" ]; then
    last_restart=$(cat "$WATCHDOG_STAMP")
    now=$(date +%s)
    if [ "$((now - last_restart))" -lt 7200 ]; then
        echo "$(date -Is) last restart was only $((now - last_restart))s ago — throttling"
        exit 0
    fi
fi

date +%s > "$WATCHDOG_STAMP"
echo "$(date -Is) watchdog triggering campaign restart (last campaign was killed/incomplete)"
# shellcheck disable=SC2086
nohup ./campaign.sh &>> campaign-watchdog.out &
echo "$(date -Is) watchdog: campaign.sh launched in background"
