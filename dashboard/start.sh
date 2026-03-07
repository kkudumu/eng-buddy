#!/bin/bash
cd ~/.claude/eng-buddy/dashboard

# Set your preferred terminal for "Open Session" (Terminal, Warp, iTerm, Alacritty, kitty)
export ENG_BUDDY_TERMINAL="${ENG_BUDDY_TERMINAL:-Warp}"

# Set your Jira email for sprint board (leave empty to use currentUser())
export ENG_BUDDY_JIRA_USER="${ENG_BUDDY_JIRA_USER:-kioja.kudumu@klaviyo.com}"

source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -q -r requirements.txt

if [ "$1" = "--background" ]; then
    # Check if already running
    if curl -s http://127.0.0.1:7777/api/health >/dev/null 2>&1; then
        echo "ALREADY_RUNNING"
        exit 0
    fi
    nohup python server.py > ~/.claude/eng-buddy/dashboard.log 2>&1 &
    echo $! > ~/.claude/eng-buddy/dashboard.pid
    # Wait for server to be ready
    for i in $(seq 1 20); do
        if curl -s http://127.0.0.1:7777/api/health >/dev/null 2>&1; then
            echo "STARTED"
            exit 0
        fi
        sleep 0.5
    done
    echo "TIMEOUT"
    exit 1
else
    python server.py
fi
