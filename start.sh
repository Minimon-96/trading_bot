#!/bin/bash

# Configuration
APP_NAME="main.py"

# Check if the process is already running
PID=$(pgrep -f "python3 $APP_NAME")

if [ -n "$PID" ]; then
    echo "[WARNING] $APP_NAME is already running with PID: $PID"
else
    # Execute with nohup
    nohup python3 $APP_NAME 1> /dev/null 2>&1 &
    echo "[SUCCESS] $APP_NAME has been started."
fi
