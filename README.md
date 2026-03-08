# eng-buddy

> Your on-call engineering copilot with an approval-first action loop, a local dashboard, and continuous learning capture.

A Claude Code skill + local web dashboard that turns `~/.claude/eng-buddy` into an engineering operations cockpit. Pollers watch Gmail, Slack, Jira, Calendar, and Freshservice; cards are triaged in a queue; high-impact actions are routed through explicit decision approvals before execution.

## What You Can Do

- **Run a unified ops dashboard** at `localhost:7777` with live SSE updates and source filters.
- **Triage by source and intent** across Gmail, Slack, Jira, Freshservice, Calendar, and Tasks.
- **Use explicit decision gates** (`approved`, `rejected`, `refined`) before execution-heavy actions.
- **Track action history** with timelines for decisions, executions, and chat context.
- **Open full task sessions** in your preferred terminal (`Terminal`, `Warp`, `iTerm`, `Alacritty`, `kitty`).
- **Refine actions conversationally** before execution using per-task/per-card chat histories.
- **Write task/card updates to Jira** and append structured daily log entries from the dashboard.
- **Work across dedicated views** for `TASKS`, `DAILY`, `LEARNINGS`, and `KNOWLEDGE`.
- **Capture learning events automatically** from tool usage into local learning artifacts.
- **Restart dashboard safely** from the UI and invalidate stale source caches without full refresh churn.
- **Install/sync hooks automatically** across runtime + skill locations with one command.

## Quick Start

```bash
# 1. Clone the skill repo
git clone https://github.com/kkudumu/eng-buddy.git ~/.claude/skills/eng-buddy

# 2. Install/sync eng-buddy hooks + learning capture wiring
bash ~/.claude/skills/eng-buddy/bin/install-hooks.sh

# 3. Optional: verify hook mirrors are synchronized
bash ~/.claude/skills/eng-buddy/bin/check-hook-sync.sh

# 4. Start the dashboard
cd ~/.claude/eng-buddy/dashboard
./start.sh
# Opens at http://localhost:7777

# 5. Invoke the skill
# In Claude Code:
/eng-buddy
```

The dashboard launcher auto-creates a Python venv and installs dependencies on first run.

## Architecture

```
~/.claude/eng-buddy/
├── dashboard/              # FastAPI web dashboard
│   ├── server.py           # Queue API, decision workflow, timelines, SSE, WS execution
│   ├── static/
│   │   ├── index.html      # HTML skeleton
│   │   ├── style.css       # Neo-brutalist dark CSS
│   │   └── app.js          # Vanilla JS frontend (xterm.js for terminals)
│   ├── tests/
│   │   ├── conftest.py
│   │   └── test_server.py
│   ├── requirements.txt    # fastapi, uvicorn, ptyprocess
│   └── start.sh            # One-command launcher
├── bin/                    # Pollers + runtime helpers
│   ├── gmail-poller.py     # Watches email threads/senders → cards
│   ├── slack-poller.py     # DMs, @mentions, task signals → cards
│   ├── jira-poller.py      # Assigned issues/sprint signals → cards
│   ├── calendar-poller.py  # Upcoming meetings → cards
│   ├── install-hooks.sh    # Installs/syncs hook wiring + patches settings.json
│   └── check-hook-sync.sh  # Verifies hook mirrors are byte-identical
├── hooks/                  # Session-gated lifecycle hooks
│   ├── eng-buddy-auto-log.sh
│   ├── eng-buddy-learning-capture.sh
│   ├── eng-buddy-pre-compaction.sh
│   ├── eng-buddy-post-compaction.sh
│   ├── eng-buddy-session-snapshot.sh
│   └── eng-buddy-session-end.sh
├── inbox.db                # SQLite card queue (auto-created)
└── [personal data dirs]    # daily/, weekly/, knowledge/, etc. (gitignored)
```

## Plugging In Your Own Stuff

eng-buddy is designed to be fully portable. The framework ships empty — you populate it with your own integrations, knowledge, and credentials.

### 1. Gmail Poller

**What it does**: Watches for emails matching patterns you define, creates dashboard cards.

**Setup**:
```bash
# a) Set up Gmail MCP credentials (required)
# Follow: https://github.com/anthropics/gmail-mcp-server
# Credentials land at: ~/.gmail-mcp/credentials.json and gcp-oauth.keys.json

# b) Create your watch list
cp ~/.claude/eng-buddy/email-watches.md.example ~/.claude/eng-buddy/email-watches.md
```

**Watch file format** (`email-watches.md`):
```markdown
## Watch: Vendor Response
- From: vendor@example.com
- Subject contains: renewal, contract
- Action: create

## Watch: Boss Thread
- Thread ID: 18d1a2b3c4d5e6f7
- Task: #42
- Action: update
```

**Install as LaunchAgent** (auto-runs every 10 min):
```bash
cat > ~/Library/LaunchAgents/com.engbuddy.gmailpoller.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.engbuddy.gmailpoller</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>${HOME}/.claude/eng-buddy/bin/gmail-poller.py</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
  <key>StandardOutPath</key><string>${HOME}/.claude/eng-buddy/gmail-poller.log</string>
  <key>StandardErrorPath</key><string>${HOME}/.claude/eng-buddy/gmail-poller.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.engbuddy.gmailpoller.plist
```

### 2. Slack Poller

**What it does**: Pulls DMs, @mentions, and messages matching task-signal patterns.

**Setup**:
```bash
# Edit the poller and replace the token placeholder:
# TOKEN = "YOUR_SLACK_USER_TOKEN"
# Get a Slack user token from: https://api.slack.com/apps
# Required scopes: channels:history, groups:history, im:history, mpim:history, users:read
vi ~/.claude/eng-buddy/bin/slack-poller.py
```

**Install LaunchAgent** (same pattern as Gmail, 10-min interval).

### 3. Jira Poller

**What it does**: Uses Claude CLI + Atlassian MCP to fetch your assigned Jira issues.

**Requires**:
- Claude Code CLI installed
- [Atlassian MCP server](https://github.com/sooperset/mcp-atlassian) configured in your `.claude.json`

The poller calls `claude --dangerously-skip-permissions --print` to query Jira via MCP. No separate Jira credentials needed — it uses your existing MCP setup.

**Install LaunchAgent** (5-min interval):
```bash
cat > ~/Library/LaunchAgents/com.engbuddy.jirapoller.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.engbuddy.jirapoller</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>${HOME}/.claude/eng-buddy/bin/jira-poller.py</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>${HOME}/.claude/eng-buddy/jira-poller.log</string>
  <key>StandardErrorPath</key><string>${HOME}/.claude/eng-buddy/jira-poller.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.engbuddy.jirapoller.plist
```

### 4. Freshservice Poller

**What it does**: Watches for new/updated Freshservice tickets assigned to you.

**Setup**: Uses the Freshservice MCP server. Configure your MCP server in `.claude.json`, then create a poller following the same pattern as the Jira poller (call Claude CLI to query Freshservice MCP).

### 5. Writing Your Own Poller

Any script that writes rows to `inbox.db` becomes a card source. The schema:

```sql
CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,                    -- 'gmail', 'slack', 'jira', 'freshservice', 'custom'
    timestamp TEXT,                 -- ISO 8601 UTC
    summary TEXT,                   -- Card title shown in dashboard
    classification TEXT,            -- 'needs-response', 'fyi', 'action-required'
    status TEXT DEFAULT 'pending',  -- 'pending', 'held', 'approved', 'completed', 'failed'
    proposed_actions TEXT,          -- JSON array of action objects
    execution_status TEXT DEFAULT 'not_run',
    execution_result TEXT,
    executed_at TEXT
);
```

**Minimal Python example**:
```python
import sqlite3, json
from datetime import datetime, timezone
from pathlib import Path

db = Path.home() / ".claude" / "eng-buddy" / "inbox.db"
conn = sqlite3.connect(db)
conn.execute("""INSERT INTO cards
    (source, timestamp, summary, classification, status, proposed_actions, execution_status)
    VALUES (?, ?, ?, ?, 'pending', ?, 'not_run')""",
    ("my-custom-source",
     datetime.now(timezone.utc).isoformat(),
     "Something happened that needs attention",
     "action-required",
     json.dumps([{"type": "custom", "draft": "Do the thing"}])))
conn.commit()
conn.close()
```

## Dashboard API (Key Endpoints)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Dashboard UI |
| `/api/health` | GET | Health check |
| `/api/cards?status=pending&source=gmail` | GET | List cards with filters + counts |
| `/api/inbox-view?source=gmail` | GET | Split view for needs-action vs no-action |
| `/api/tasks` | GET | Parse `tasks/active-tasks.md` into task cards |
| `/api/cards/{id}/decision` | POST | Record decision for a card action |
| `/api/tasks/{task_number}/decision` | POST | Record decision for a task action |
| `/api/cards/{id}/timeline` | GET | Decision/execution/chat timeline for a card |
| `/api/tasks/{task_number}/timeline` | GET | Decision/execution/chat timeline for a task |
| `/api/cards/{id}/refine` | POST | Refine a card action conversationally |
| `/api/tasks/{task_number}/refine` | POST | Refine a task action conversationally |
| `/api/cards/{id}/open-session` | POST | Spawn interactive Claude in your terminal |
| `/api/tasks/{task_number}/open-session` | POST | Spawn task-focused Claude session |
| `/api/cards/{id}/write-jira` | POST | Write/update Jira from card context |
| `/api/tasks/{task_number}/write-jira` | POST | Write/update Jira from task context |
| `/api/cards/{id}/daily-log` | POST | Append structured daily log entry |
| `/api/tasks/{task_number}/daily-log` | POST | Append task daily log entry |
| `/api/events` | GET | SSE stream for new cards + cache invalidation |
| `/api/cache-invalidate` | POST | Mark source cache stale from pollers |
| `/api/restart` | POST | Restart dashboard server from UI |
| `/ws/execute/{id}` | WebSocket | Stream Claude execution output |
| `/api/notify` | POST | Fire macOS notification |
| `/api/daily/logs` | GET | Enumerate daily logs for dashboard |
| `/api/learnings/summary` | GET | Learning loop summary by date/range |
| `/api/knowledge/index` | GET | Indexed knowledge browser |

## Personalizing the Workspace

eng-buddy auto-creates these directories on first `/eng-buddy` invocation:

```
daily/          # Daily logs (auto-created per day)
weekly/         # Weekly summaries
knowledge/      # Your systems, team, preferences
  infrastructure.md   # Your infrastructure and systems
  team.md             # People you work with
  preferences.md      # How you like to work
patterns/       # Recurring issues, success/failure patterns
capacity/       # Time tracking, burnout indicators
stakeholders/   # Follow-ups, communication logs
tasks/          # Active task state
```

All personal data directories are gitignored — your data stays local.

## Skill Commands

In a `/eng-buddy` session:

| Say this | Get this |
|----------|----------|
| "what happened today" | Comprehensive narrative analysis with data backing |
| "what's blocking me?" | Active blockers with aging and escalation suggestions |
| "am I overcommitted?" | Capacity analysis and recommendations |
| "what patterns do you see?" | Recurring issues, questions, success/failure patterns |
| "show my stats" | Key metrics: completion rate, energy, context switches |
| "draft status update" | Generate stakeholder communication |
| "wrap up" | Summarize day, roll forward open items |

## Requirements

- **macOS** (LaunchAgents, Terminal.app, osascript — Linux support is possible with cron + alternatives)
- **Python 3.11+**
- **Claude Code CLI** (`claude` in PATH)
- **MCP servers** configured for the pollers you want to use

## Checking Poller Status

```bash
# See all running pollers
launchctl list | grep engbuddy

# Check logs
tail -f ~/.claude/eng-buddy/gmail-poller.log
tail -f ~/.claude/eng-buddy/jira-poller.log
```

## License

MIT — see [LICENSE](../LICENSE)
