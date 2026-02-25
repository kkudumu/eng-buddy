#!/bin/bash
# Hook: Auto-log progress to eng-buddy daily log
# Triggers: When user reports completed actions while eng-buddy is active

# Check if eng-buddy session is active
if [ ! -f ~/.claude/eng-buddy/.session-active ]; then
    exit 0  # Not in eng-buddy session, skip
fi

# Get the user's message from stdin or first argument
USER_MESSAGE="${1:-$(cat)}"

# Action indicators (what users say when they've done something)
ACTION_PATTERNS=(
    "^[Ii] (did|completed?|finished|fixed|sent|responded|closed|created|updated|deployed|merged|pushed|committed|tested|reviewed)"
    "^[Jj]ust (did|completed?|finished|fixed|sent|responded|closed|created|updated|deployed|merged|pushed|committed|tested|reviewed)"
    "^[Dd]one"
    "^[Ff]inished"
    "^[Cc]ompleted?"
    "^[Ss]ent (email|message|response)"
    "^[Rr]esponded to"
    "^[Mm]erged"
    "^[Pp]ushed to"
    "^[Cc]ommitted"
    "^[Dd]eployed"
    "^[Ff]ixed"
    "^[Cc]losed (ticket|issue|task)"
    "[Tt]ask.*complete"
    "[Tt]icket.*closed"
)

# Check if message matches any action pattern
SHOULD_LOG=false
for pattern in "${ACTION_PATTERNS[@]}"; do
    if echo "$USER_MESSAGE" | grep -qE "$pattern"; then
        SHOULD_LOG=true
        break
    fi
done

# Also check for follow-up questions after taking action
# (e.g., "I sent the email. What should I do next?")
if echo "$USER_MESSAGE" | grep -qE "(I|i) .* (what|should|next|now)\?"; then
    SHOULD_LOG=true
fi

# If action detected, output logging reminder for Claude to see
if [ "$SHOULD_LOG" = true ]; then
    echo ""
    echo "📝 [Auto-log] Detected progress update. Please log this to today's daily log."
    echo ""
fi

# --- Check for pending Slack task inbox items ---
TASK_INBOX=~/.claude/eng-buddy/task-inbox.md
TASK_SHOWN_MARKER=~/.claude/eng-buddy/.task-inbox-last-shown

if [ -f "$TASK_INBOX" ]; then
    PENDING_COUNT=$(grep -c "^## \[ \]" "$TASK_INBOX" 2>/dev/null || echo 0)

    if [ "$PENDING_COUNT" -gt 0 ]; then
        # Only surface once per 10 minutes to avoid noise
        SHOULD_SHOW=true
        if [ -f "$TASK_SHOWN_MARKER" ]; then
            LAST_SHOWN=$(stat -f %m "$TASK_SHOWN_MARKER" 2>/dev/null || echo 0)
            NOW=$(date +%s)
            ELAPSED=$(( NOW - LAST_SHOWN ))
            if [ "$ELAPSED" -lt 600 ]; then
                SHOULD_SHOW=false
            fi
        fi

        if [ "$SHOULD_SHOW" = true ]; then
            touch "$TASK_SHOWN_MARKER"
            echo ""
            echo "📬 [Slack Task Inbox] $PENDING_COUNT unreviewed message(s) detected from Slack that may need action:"
            grep -A2 "^## \[ \]" "$TASK_INBOX" | grep -v "^<!--" | grep -v "^--$" | head -40
            echo ""
            echo "Please review these with the user and offer to create tasks. Mark as [x] in task-inbox.md once reviewed."
            echo ""
        fi
    fi
fi
