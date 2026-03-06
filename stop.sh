#!/bin/bash

# Configuration
APP_NAME="main.py"

# Find the Parent Process ID (PID)
PID=$(pgrep -f "python3 $APP_NAME")

if [ -z "$PID" ]; then
    echo "[ERROR] No running process found for $APP_NAME"
else
    # Get the Process Group ID (PGID)
    PGID=$(ps -o pgid= -p $PID | tr -d ' ')
    # Kill the entire process group (using the minus sign before PGID)
    kill -15 -- -$PGID
    sleep 2

    # Verify if any process in the group is still alive
    if ps -o pgid= | grep -w $PGID > /dev/null; then
        echo "[RETRY] Some processes are still alive. Sending SIGKILL to group..."
        kill -9 -- -$PGID
    fi
    
    echo "[SUCCESS] Process tree for $APP_NAME has been terminated."
fi
