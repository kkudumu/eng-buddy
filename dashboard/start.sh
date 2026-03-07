#!/bin/bash
cd ~/.claude/eng-buddy/dashboard

# Set your preferred terminal for "Open Session" (Terminal, Warp, iTerm, Alacritty, kitty)
export ENG_BUDDY_TERMINAL="${ENG_BUDDY_TERMINAL:-Warp}"

source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -q -r requirements.txt
python server.py
