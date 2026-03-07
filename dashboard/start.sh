#!/bin/bash
cd ~/.claude/eng-buddy/dashboard
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -q -r requirements.txt
python server.py
