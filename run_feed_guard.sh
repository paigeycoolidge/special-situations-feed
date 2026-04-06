#!/bin/bash
# Runs every 5 minutes via launchd. Executes run_feed.sh if:
#   1. Today is a weekday, and
#   2. The feed hasn't already run successfully today.
# This catches the case where the Mac was asleep at 8am.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Skip weekends (date +%u: 1=Mon ... 5=Fri, 6=Sat, 7=Sun)
DOW=$(date +%u)
[ "$DOW" -ge 6 ] && exit 0

# Skip if today's log already shows a completed run
LOG="$DIR/logs/feed-$(date +%Y%m%d).log"
[ -f "$LOG" ] && grep -q "=== Done ===" "$LOG" && exit 0

# Prevent concurrent runs with a lockfile
LOCK="$DIR/.feed.lock"
exec 9>"$LOCK"
flock -n 9 || exit 0

exec "$DIR/run_feed.sh"
