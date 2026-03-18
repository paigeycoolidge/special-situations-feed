#!/bin/bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$DIR/logs/feed-$(date +%Y%m%d).log"

source "$DIR/venv/bin/activate"

python "$DIR/fetch_situations.py" >> "$LOG_FILE" 2>&1

if [ $? -ne 0 ]; then
    echo "Feed failed — check logs: $LOG_FILE"
    exit 1
fi

python "$DIR/send_email.py" >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    echo "Feed updated and email sent successfully"
else
    echo "Feed updated but email failed — check logs: $LOG_FILE"
fi
