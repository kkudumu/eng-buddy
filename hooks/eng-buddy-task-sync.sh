#!/bin/bash
# eng-buddy-task-sync.sh
# Hook: Remind Claude to sync task state file when tasks are completed
# Trigger: PostToolUse (fires after TaskUpdate)
#
# When a TaskUpdate sets status=completed, injects a reminder to update
# active-tasks.md so the state file stays in sync across sessions.

set -euo pipefail

ENG_BUDDY_ROOT="$HOME/.claude/eng-buddy"
SESSION_MARKER="$ENG_BUDDY_ROOT/.session-active"
TASKS_FILE="$ENG_BUDDY_ROOT/tasks/active-tasks.md"

# Only fire during eng-buddy sessions
if [ ! -f "$SESSION_MARKER" ]; then
  exit 0
fi

PAYLOAD=$(cat)
if [ -z "$PAYLOAD" ]; then
  exit 0
fi

# Parse hook event and tool name
read -r HOOK_EVENT TOOL_NAME TOOL_INPUT <<'PYEOF'
$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("hook_event_name", ""))
    print(d.get("tool_name", ""))
    print(json.dumps(d.get("tool_input", {})))
except Exception:
    print("")
    print("")
    print("{}")
' 2>/dev/null)
PYEOF

# Alternative parsing that works reliably
HOOK_EVENT=$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try: print(json.load(sys.stdin).get("hook_event_name", ""))
except: print("")
' 2>/dev/null)

if [ "$HOOK_EVENT" != "PostToolUse" ]; then
  exit 0
fi

TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try: print(json.load(sys.stdin).get("tool_name", ""))
except: print("")
' 2>/dev/null)

# Only care about TaskUpdate
if [ "$TOOL_NAME" != "TaskUpdate" ]; then
  exit 0
fi

# Check if status was set to completed or deleted
STATUS=$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    inp = d.get("tool_input", {})
    print(inp.get("status", ""))
except:
    print("")
' 2>/dev/null)

if [ "$STATUS" != "completed" ] && [ "$STATUS" != "deleted" ]; then
  exit 0
fi

TASK_ID=$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    inp = d.get("tool_input", {})
    print(inp.get("taskId", ""))
except:
    print("")
' 2>/dev/null)

# Inject reminder into conversation
cat <<EOF
[TASK STATE SYNC]: You just marked task #${TASK_ID} as ${STATUS}.
Update ~/.claude/eng-buddy/tasks/active-tasks.md NOW:
1. Find the task entry and set **Status**: ${STATUS} ($(date +%Y-%m-%d))
2. Update the "Task Count Summary" section at the bottom
Do this silently — don't announce it, just do it alongside your response.
EOF
