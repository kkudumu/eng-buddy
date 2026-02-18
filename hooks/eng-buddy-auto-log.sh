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
