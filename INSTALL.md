# eng-buddy Hook Installation Guide

## Overview

The eng-buddy skill includes an intelligent auto-logging hook system that detects when you report completed actions and automatically prompts Claude to log them to your daily log.

## Installation Steps

### 1. Copy Hook Scripts to Your Hooks Directory

**Find your hooks directory:**
- **Claude Code default**: `~/.claude/hooks/`
- **Custom setup**: Check your `settings.json` for `CLAUDE_HOME` environment variable

**Copy the hooks:**

```bash
# For default Claude Code setup:
cp ~/.claude/skills/eng-buddy/hooks/*.sh ~/.claude/hooks/

# For custom CLAUDE_HOME setup:
cp ~/.claude/skills/eng-buddy/hooks/*.sh $CLAUDE_HOME/hooks/
```

**Make them executable:**

```bash
chmod +x ~/.claude/hooks/eng-buddy-*.sh
# Or for custom CLAUDE_HOME:
chmod +x $CLAUDE_HOME/hooks/eng-buddy-*.sh
```

### 2. Update Your settings.json

**Location:**
- Default: `~/.claude/settings.json`
- Custom: `$CLAUDE_HOME/settings.json`

**Add hook configuration:**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/YOUR_USERNAME/.claude/hooks/eng-buddy-auto-log.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/YOUR_USERNAME/.claude/hooks/eng-buddy-session-end.sh"
          }
        ]
      }
    ]
  }
}
```

**⚠️ Replace `/Users/YOUR_USERNAME/` with your actual home directory path!**

### 3. Update SKILL.md Paths

Open `~/.claude/skills/eng-buddy/SKILL.md` and find **STEP 0** in the "Workspace Initialization Protocol" section.

**Update the path to match your hooks directory:**

```
STEP 0: Activate auto-logging hook (MUST DO FIRST)
- Use Bash: /Users/YOUR_USERNAME/.claude/hooks/eng-buddy-session-manager.sh start
```

**Replace with your actual hooks path.**

### 4. Verify Installation

```bash
# Check hooks are in place and executable:
ls -la ~/.claude/hooks/eng-buddy-*.sh

# Check session manager works:
~/.claude/hooks/eng-buddy-session-manager.sh status
```

You should see: `⏸️  eng-buddy auto-logging is INACTIVE`

## How It Works

### When You Invoke `/eng-buddy`

1. **STEP 0 activates** → Runs `eng-buddy-session-manager.sh start`
2. **Creates marker file** → `~/.claude/eng-buddy/.session-active`
3. **Hook is now active** → Monitors your messages for progress updates

### During Your Session

When you report actions like:
- "I completed the feature"
- "I sent the email"
- "I fixed the bug"
- "Just merged the PR"

The `UserPromptSubmit` hook detects these patterns and reminds Claude to log them to your daily file.

### When Session Ends

1. **SessionEnd hook fires** → Runs `eng-buddy-session-end.sh`
2. **Removes marker file** → `~/.claude/eng-buddy/.session-active`
3. **Hook deactivates** → Won't fire in other conversations

## Hook Files Explained

### eng-buddy-auto-log.sh
- **Trigger**: UserPromptSubmit (every user message)
- **Purpose**: Detects progress updates and prompts logging
- **Only runs when**: `.session-active` marker file exists
- **Detection patterns**: "I completed", "I sent", "I fixed", etc.

### eng-buddy-session-manager.sh
- **Trigger**: Manual or SKILL.md STEP 0
- **Purpose**: Activate/deactivate the auto-logging system
- **Commands**:
  - `start` - Activates hook (creates marker file)
  - `stop` - Deactivates hook (removes marker file)
  - `status` - Check if hook is active

### eng-buddy-session-end.sh
- **Trigger**: SessionEnd (when conversation ends)
- **Purpose**: Auto-deactivate hook when session ends
- **Action**: Removes `.session-active` marker file

## Troubleshooting

### Hook Not Triggering

**Check if active:**
```bash
~/.claude/hooks/eng-buddy-session-manager.sh status
```

**Manually activate:**
```bash
~/.claude/hooks/eng-buddy-session-manager.sh start
```

**Check marker file exists:**
```bash
ls -la ~/.claude/eng-buddy/.session-active
```

### Hook Triggering in Other Conversations

The hook should ONLY fire during eng-buddy sessions. If it's firing elsewhere:

1. Check if marker file exists when it shouldn't:
   ```bash
   rm ~/.claude/eng-buddy/.session-active
   ```

2. Verify SessionEnd hook is configured in settings.json

3. Restart Claude Code

### Hook Scripts Not Found

Verify paths in settings.json match where you copied the hooks:

```bash
# Check your hooks directory:
ls -la ~/.claude/hooks/eng-buddy-*.sh

# Or for custom CLAUDE_HOME:
ls -la $CLAUDE_HOME/hooks/eng-buddy-*.sh
```

Update settings.json paths to match actual location.

## Customization

### Adjust Detection Patterns

Edit `eng-buddy-auto-log.sh` to add/remove action patterns:

```bash
ACTION_PATTERNS=(
    "^[Ii] (completed?|finished|fixed)"
    "^[Jj]ust (completed?|finished|fixed)"
    # Add your own patterns here
)
```

### Change Session Marker Location

Default: `~/.claude/eng-buddy/.session-active`

To change, edit all three hook scripts and update the path.

## Uninstallation

To remove the auto-logging system:

1. **Remove hooks:**
   ```bash
   rm ~/.claude/hooks/eng-buddy-*.sh
   ```

2. **Remove settings.json configuration:**
   - Delete the `UserPromptSubmit` and `SessionEnd` hook entries

3. **Remove marker file:**
   ```bash
   rm ~/.claude/eng-buddy/.session-active
   ```

The eng-buddy skill will still work without hooks - you just won't get automatic logging prompts.

---

## Support

**Issues?** Check:
1. Hook scripts are executable (`chmod +x`)
2. Paths in settings.json are absolute and correct
3. Marker file exists during active sessions
4. SessionEnd hook is configured for auto-cleanup

**Questions?** Open an issue in the eng-buddy repository.
