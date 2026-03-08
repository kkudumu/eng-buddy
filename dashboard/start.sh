#!/bin/bash
set -euo pipefail

cd ~/.claude/eng-buddy/dashboard

# Keep runtime isolated from the parent Claude session.
unset CLAUDECODE
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Remove stale temporary launcher/context files that can confuse startup state.
find ~/.claude/eng-buddy -maxdepth 1 -type f \
  \( -name 'tmp*.sh' -o -name 'tmp*.md' -o -name 'tmp*.ctx' \) \
  -mtime +0 -delete 2>/dev/null || true

# Set your preferred terminal for "Open Session" (Terminal, Warp, iTerm, Alacritty, kitty)
export ENG_BUDDY_TERMINAL="${ENG_BUDDY_TERMINAL:-Warp}"

# Set your Jira email for sprint board (leave empty to use currentUser())
export ENG_BUDDY_JIRA_USER="${ENG_BUDDY_JIRA_USER:-kioja.kudumu@klaviyo.com}"

source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -q -r requirements.txt

is_running() {
  lsof -iTCP:7777 -sTCP:LISTEN -n -P >/dev/null 2>&1
}

if [[ "${1:-}" == "--background" ]]; then
  if is_running; then
    echo "ALREADY_RUNNING"
    exit 0
  fi

  LOG_FILE="$HOME/.claude/eng-buddy/dashboard.log"
  nohup python server.py >"$LOG_FILE" 2>&1 &

  for _ in {1..20}; do
    if is_running; then
      echo "STARTED"
      exit 0
    fi
    sleep 1
  done

  echo "TIMEOUT"
  exit 1
fi

python server.py
