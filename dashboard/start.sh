#!/bin/bash
set -euo pipefail

RUNTIME_DIR="$HOME/.claude/eng-buddy"
DASHBOARD_DIR="$RUNTIME_DIR/dashboard"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LAUNCH_LABEL="com.engbuddy.dashboard"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LAUNCH_LABEL.plist"
LOG_FILE="$RUNTIME_DIR/dashboard.log"
HEALTH_URL="http://127.0.0.1:7777/api/health"

combined_path() {
  local claude_dir
  claude_dir="$(dirname "$(command -v claude 2>/dev/null || echo /usr/local/bin/claude)")"
  echo "$claude_dir:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
}

launch_target() {
  echo "gui/$(id -u)/$LAUNCH_LABEL"
}

cleanup_runtime() {
  find "$RUNTIME_DIR" -maxdepth 1 -type f \
    \( -name 'tmp*.sh' -o -name 'tmp*.md' -o -name 'tmp*.ctx' \) \
    -mtime +0 -delete 2>/dev/null || true
}

export_runtime_env() {
  unset CLAUDECODE
  export PATH
  PATH="$(combined_path)"
  export ENG_BUDDY_TERMINAL="${ENG_BUDDY_TERMINAL:-Warp}"
  export ENG_BUDDY_JIRA_USER="${ENG_BUDDY_JIRA_USER:-kioja.kudumu@klaviyo.com}"
  export ENG_BUDDY_JIRA_BOARD_NAME="${ENG_BUDDY_JIRA_BOARD_NAME:-Systems}"
  export ENG_BUDDY_JIRA_PROJECT_KEY="${ENG_BUDDY_JIRA_PROJECT_KEY:-ITWORK2}"
  export ENG_BUDDY_DASHBOARD_RELOAD="${ENG_BUDDY_DASHBOARD_RELOAD:-0}"
}

ensure_python_env() {
  cd "$DASHBOARD_DIR"
  if [[ ! -d venv ]]; then
    python3 -m venv venv
  fi
  # shellcheck disable=SC1091
  source venv/bin/activate
  pip install -q -r requirements.txt
}

is_healthy() {
  curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

is_loaded() {
  launchctl print "$(launch_target)" >/dev/null 2>&1
}

legacy_dashboard_pid() {
  local pid command
  for pid in $(lsof -nP -iTCP:7777 -sTCP:LISTEN -t 2>/dev/null || true); do
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command" == *".claude/eng-buddy/dashboard"* && "$command" == *"server.py"* ]]; then
      echo "$pid"
      return 0
    fi
  done
  return 1
}

stop_legacy_dashboard_process() {
  local pid
  pid="$(legacy_dashboard_pid || true)"
  if [[ -z "$pid" ]]; then
    return 0
  fi

  kill "$pid" >/dev/null 2>&1 || true
  for _ in {1..10}; do
    if ! ps -p "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
}

write_plist() {
  local tmp_path plist_changed=0 runtime_path

  mkdir -p "$LAUNCH_AGENTS_DIR"
  runtime_path="$(combined_path)"
  tmp_path="$PLIST_PATH.tmp"

  cat > "$tmp_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LAUNCH_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$DASHBOARD_DIR/start.sh</string>
        <string>--serve</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DASHBOARD_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$runtime_path</string>
        <key>HOME</key>
        <string>$HOME</string>
        <key>ENG_BUDDY_TERMINAL</key>
        <string>${ENG_BUDDY_TERMINAL:-Warp}</string>
        <key>ENG_BUDDY_JIRA_USER</key>
        <string>${ENG_BUDDY_JIRA_USER:-kioja.kudumu@klaviyo.com}</string>
        <key>ENG_BUDDY_JIRA_BOARD_NAME</key>
        <string>${ENG_BUDDY_JIRA_BOARD_NAME:-Systems}</string>
        <key>ENG_BUDDY_JIRA_PROJECT_KEY</key>
        <string>${ENG_BUDDY_JIRA_PROJECT_KEY:-ITWORK2}</string>
        <key>ENG_BUDDY_DASHBOARD_RELOAD</key>
        <string>0</string>
    </dict>
</dict>
</plist>
EOF

  if cmp -s "$tmp_path" "$PLIST_PATH" 2>/dev/null; then
    rm -f "$tmp_path"
  else
    mv "$tmp_path" "$PLIST_PATH"
    plist_changed=1
  fi

  return "$plist_changed"
}

bootstrap_agent() {
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || \
    launchctl load "$PLIST_PATH" >/dev/null 2>&1
}

bootout_agent() {
  launchctl bootout "$(launch_target)" >/dev/null 2>&1 || \
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
}

wait_for_health() {
  local timeout_seconds="${1:-30}"
  local elapsed=0

  while (( elapsed < timeout_seconds )); do
    if is_healthy; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

start_agent() {
  local plist_changed=0

  export_runtime_env
  cleanup_runtime
  write_plist || plist_changed=$?

  if is_loaded && is_healthy && [[ "$plist_changed" -eq 0 ]]; then
    echo "ALREADY_RUNNING"
    return 0
  fi

  stop_legacy_dashboard_process

  if is_loaded; then
    if [[ "$plist_changed" -eq 1 ]]; then
      bootout_agent
      bootstrap_agent
    else
      launchctl kickstart -k "$(launch_target)" >/dev/null 2>&1 || {
        bootout_agent
        bootstrap_agent
      }
    fi
  else
    bootstrap_agent
  fi

  if wait_for_health 45; then
    echo "STARTED"
    return 0
  fi

  echo "TIMEOUT"
  return 1
}

restart_agent() {
  local plist_changed=0

  export_runtime_env
  cleanup_runtime
  write_plist || plist_changed=$?
  stop_legacy_dashboard_process

  if is_loaded; then
    if [[ "$plist_changed" -eq 1 ]]; then
      bootout_agent
      bootstrap_agent
    else
      launchctl kickstart -k "$(launch_target)" >/dev/null 2>&1 || {
        bootout_agent
        bootstrap_agent
      }
    fi
  else
    bootstrap_agent
  fi

  if wait_for_health 45; then
    echo "STARTED"
    return 0
  fi

  echo "TIMEOUT"
  return 1
}

stop_agent() {
  bootout_agent
  stop_legacy_dashboard_process
  echo "STOPPED"
}

print_status() {
  if is_loaded && is_healthy; then
    echo "RUNNING"
    return 0
  fi
  if is_loaded; then
    echo "LOADED_UNHEALTHY"
    return 1
  fi
  if legacy_dashboard_pid >/dev/null 2>&1; then
    echo "LEGACY_PROCESS"
    return 1
  fi
  echo "STOPPED"
  return 1
}

serve_foreground() {
  export_runtime_env
  cleanup_runtime
  ensure_python_env
  cd "$DASHBOARD_DIR"
  exec python3 server.py
}

case "${1:-}" in
  --background)
    start_agent
    ;;
  --restart)
    restart_agent
    ;;
  --stop)
    stop_agent
    ;;
  --status)
    print_status
    ;;
  --serve)
    serve_foreground
    ;;
  *)
    serve_foreground
    ;;
esac
