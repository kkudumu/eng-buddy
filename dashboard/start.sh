#!/bin/bash
cd ~/.claude/eng-buddy/dashboard

# Set your preferred terminal for "Open Session" (Terminal, Warp, iTerm, Alacritty, kitty)
export ENG_BUDDY_TERMINAL="${ENG_BUDDY_TERMINAL:-Warp}"

# Set your Jira email for sprint board (leave empty to use currentUser())
export ENG_BUDDY_JIRA_USER="${ENG_BUDDY_JIRA_USER:-kioja.kudumu@klaviyo.com}"

source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -q -r requirements.txt
python server.py
