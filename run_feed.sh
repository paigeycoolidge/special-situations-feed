#!/bin/bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$DIR/logs/feed-$(date +%Y%m%d).log"

source "$DIR/venv/bin/activate"

python "$DIR/fetch_situations.py" >> "$LOG_FILE" 2>&1

if [ $? -ne 0 ]; then
    echo "Feed failed — check logs: $LOG_FILE"
    exit 1
fi

NEW_COUNT=$(python3 -c "import json; d=json.load(open('$DIR/feed_data/feed.json')); print(d.get('new_count',0))")
if [ "$NEW_COUNT" -eq 0 ]; then
    echo "No new situations today — skipping email"
else
    python "$DIR/send_email.py" >> "$LOG_FILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "Feed updated and email sent successfully ($NEW_COUNT new situations)"
    else
        echo "Feed updated but email failed — check logs: $LOG_FILE"
    fi
fi

# Push updated feed.json to GitHub Pages
cd "$DIR"
git add feed_data/feed.json feed_data/seen_items.json >> "$LOG_FILE" 2>&1
git commit -m "Feed update $(date +%Y-%m-%d)" >> "$LOG_FILE" 2>&1
if git push origin main >> "$LOG_FILE" 2>&1; then
    echo "[Git] Pushed feed_data/feed.json to GitHub Pages" >> "$LOG_FILE"
else
    echo "[Git] Push failed — check logs: $LOG_FILE" >> "$LOG_FILE"
fi
