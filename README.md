# eng-buddy

> Your on-call engineering assistant with a local dashboard, background pollers, and comprehensive self-tracking.

A Claude Code skill + local web dashboard that turns your `~/.claude/` directory into an intelligent engineering operations center. Background pollers watch Gmail, Slack, Jira, and Freshservice — surfacing actionable cards you can approve, hold, refine, or open as full Claude sessions.

## What You Get

- **Dashboard** at `127.0.0.1:7777` — neo-brutalist dark-mode queue UI
- **Background pollers** — Gmail, Slack, Jira, Freshservice feed cards into a local SQLite queue
- **One-click execution** — approve a card and watch Claude execute it in a streaming terminal
- **Refine before acting** — chat with Claude about a card before approving
- **Open Session** — spawn a full interactive Claude session in Terminal.app for complex tasks
- **Skill integration** — `/eng-buddy` auto-launches the dashboard and loads your full context
- **Comprehensive tracking** — passive data collection on energy, decisions, context switches, patterns

## Quick Start

```bash
# 1. Clone the repo (if you haven't already)
git clone https://github.com/kkudumu/clod.git ~/.claude

# 2. Start the dashboard
cd ~/.claude/eng-buddy/dashboard
./start.sh --background
# Serves at http://127.0.0.1:7777 via launchd

# 3. Invoke the skill
# In Claude Code:
/eng-buddy
```

`--background` returns quickly. It prints `ALREADY_RUNNING`, `STARTED`, or `STARTING` for a healthy or booting dashboard, and only prints `TIMEOUT` when launchd could not get the service off the ground.

The dashboard auto-creates a Python venv and installs dependencies on first run.

## Architecture

```
~/.claude/eng-buddy/
├── dashboard/              # FastAPI web dashboard
│   ├── server.py           # API: cards, SSE, WebSocket execution, refine, open-session
│   ├── static/
│   │   ├── index.html      # HTML skeleton
│   │   ├── style.css       # Neo-brutalist dark CSS
│   │   └── app.js          # Vanilla JS frontend (xterm.js for terminals)
│   ├── tests/
│   │   ├── conftest.py
│   │   └── test_server.py
│   ├── requirements.txt    # fastapi, uvicorn, ptyprocess
│   └── start.sh            # One-command launcher
├── bin/                    # Background pollers
│   ├── gmail-poller.py     # Watches email threads/senders → cards
│   ├── slack-poller.py     # DMs, @mentions, task signals → cards
│   └── jira-poller.py      # Assigned issues → cards
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

## Dashboard API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Dashboard UI |
| `/api/health` | GET | Health check |
| `/api/cards?status=pending&source=gmail` | GET | List cards with filters + counts |
| `/api/cards/{id}/hold` | POST | Hold a card for later |
| `/api/cards/{id}/status` | POST | Update card status |
| `/api/events` | GET | SSE stream for new cards |
| `/ws/execute/{id}` | WebSocket | Stream Claude execution output |
| `/api/cards/{id}/refine` | POST | Chat about a card before execution |
| `/api/cards/{id}/open-session` | POST | Spawn interactive Claude in Terminal.app |
| `/api/notify` | POST | Fire macOS notification |

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
