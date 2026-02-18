# 🛠️ eng-buddy — your on-call EA, built for engineers

Your intelligent assistant for staying organized, focused, and effective amid constant context switching and complex technical challenges.

## 🎯 What is eng-buddy?

eng-buddy is a specialized Claude Code skill designed for senior IT systems engineers who juggle multiple projects, meetings, requests, and incidents daily. It provides:

- **📋 Intelligent Task Organization** - Prioritize and track work across systems
- **📝 Meeting Intelligence** - Extract action items, decisions, and questions
- **💬 Communication Management** - Track requests and follow-ups
- **🔄 Context Switching Support** - Save/restore project state seamlessly
- **🚨 Incident Tracking** - Document and learn from production issues
- **🔔 Pattern Recognition** - Identify recurring problems and documentation gaps
- **📊 Capacity Planning** - Monitor workload and prevent burnout
- **💡 Learning Log** - Capture solutions and approaches that worked

## ✨ Key Features

### Persistent Memory Across Sessions
- Hierarchical markdown file system (`daily/`, `weekly/`, `monthly/`, `knowledge/`)
- Never lose context between conversations
- Build on previous work automatically

### Proactive Intelligence
- **Recurring Issue Detection** - "You've solved this 3 times this month - should we document it?"
- **Documentation Gap Analysis** - Identifies what needs runbooks based on patterns
- **Blocker Escalation Alerts** - Warns when dependencies age beyond thresholds
- **Capacity Monitoring** - Tracks context switches, on-call load, work hours
- **Follow-up Tracking** - Reminds about overdue commitments

### Auto-Logging Hook System
- Detects when you report completed actions
- Automatically prompts Claude to log to your daily file
- Only active during eng-buddy sessions
- Zero manual intervention required

### Meeting Processing
Extract from transcripts:
- ✅ Action items with owners and deadlines
- ❓ Open questions needing clarification
- 🎯 Technical decisions and rationale
- 🚨 Risks and concerns mentioned

### Systems Engineering Context
- Understands infrastructure, deployments, operations
- Considers reliability, scalability, security
- Thinks through blast radius and rollback plans
- Tracks system relationships and dependencies

## 📦 Installation

### Quick Start

1. **Install the skill:**
   ```bash
   # Place in your Claude Code skills directory
   cp -r eng-buddy ~/.claude/skills/
   ```

2. **Install the hooks (optional but recommended):**

   Follow the detailed instructions in [INSTALL.md](./INSTALL.md)

3. **Invoke the skill:**
   ```
   /eng-buddy
   ```

### Requirements

- **Claude Code CLI** (or Claude.ai with skills support)
- **macOS, Linux, or WSL** (for bash hooks)
- **~/.claude/eng-buddy/** workspace directory (auto-created on first run)

## 🚀 Usage

### Starting a Session

```
/eng-buddy
```

eng-buddy will:
1. Load your current context (today's tasks, blockers, capacity)
2. Restore tasks from previous session
3. Show proactive alerts (aging blockers, recurring issues, etc.)
4. Suggest what to tackle first

### Common Commands

**During the session:**
- "Help me process this meeting transcript" → Extracts action items, decisions
- "I need to context switch" → Documents current state for restoration
- "What's blocking me?" → Shows all active blockers with aging
- "Am I overcommitted?" → Capacity analysis and recommendations
- "Draft status update" → Generates stakeholder communication
- "Wrap up" → Summarizes day, rolls forward open items

### Daily Workflow Example

```
User: /eng-buddy
eng-buddy: Good morning! Week 8 review:
📌 Open Items: 7 action items (2 high priority)
🚧 Active Blockers: 1 blocker (escalate today?)
🔔 Recurring Issues:
- Database timeout occurred 3x - document it?

User: I completed the API migration and sent the status update
eng-buddy: [Logs to daily file]

User: Show me the GitHub incident from yesterday
eng-buddy: [Retrieves incident details from incidents/]

User: What patterns do you see this week?
eng-buddy: [Analyzes recurring issues, questions, documentation gaps]

User: Wrap up
eng-buddy: [Summarizes, rolls forward open items to tomorrow]
```

## 📁 Workspace Structure

```
~/.claude/eng-buddy/
├── daily/                    # Daily working logs (2026-02-18.md)
├── weekly/                   # Weekly summaries (2026-W08.md)
├── monthly/                  # Monthly overviews (2026-02.md)
├── knowledge/                # Static knowledge
│   ├── infrastructure.md     # Systems, architecture
│   ├── team.md              # People, roles
│   ├── preferences.md       # Work style, preferences
│   └── solutions.md         # Learning log
├── patterns/                 # Intelligence
│   ├── recurring-issues.md
│   ├── recurring-questions.md
│   └── documentation-gaps.md
├── incidents/                # Incident tracking
│   ├── incident-index.md
│   └── 2026-02-18-*.md
├── dependencies/             # Blockers and dependencies
│   ├── active-blockers.md
│   └── dependency-map.md
├── capacity/                 # Time tracking
│   ├── time-estimates.md
│   ├── weekly-capacity.md
│   └── burnout-indicators.md
├── stakeholders/             # Communications
│   ├── communication-log.md
│   ├── follow-ups.md
│   └── status-updates/
├── references/               # API docs and technical refs
└── archive/                  # Completed daily files
```

## 🔧 Hook System

The optional hook system provides automatic progress logging:

### How It Works

1. **UserPromptSubmit Hook** - Detects when you report actions
2. **Pattern Matching** - Recognizes phrases like "I completed", "I sent", "I fixed"
3. **Auto-Logging Prompt** - Reminds Claude to log to daily file
4. **Session-Gated** - Only fires during active eng-buddy sessions
5. **Auto-Cleanup** - SessionEnd hook deactivates after session

### Installation

See [INSTALL.md](./INSTALL.md) for complete hook installation instructions.

**TL;DR:**
1. Copy `hooks/*.sh` to your `~/.claude/hooks/` directory
2. Add hook configuration to `settings.json`
3. Update paths in SKILL.md

Hooks are **optional** - the skill works without them, you just won't get automatic logging prompts.

## 💡 Example Scenarios

### Processing Meeting Transcripts

```
User: [Pastes meeting transcript]
User: Help me process this

eng-buddy:
## Action Items from Product Planning Meeting

**High Priority:**
- [ ] Design API schema for new feature - @You - Due Friday
- [ ] Review security requirements with InfoSec - @You - This week

**Open Questions:**
- What's our rate limit strategy? (Critical for scaling)
- Should we support batch operations? (Nice to have)

**Decisions Made:**
- Using REST API (not GraphQL) - simpler for initial launch
- Launch with read-only endpoints first - write endpoints in v2
```

### Context Switching

```
User: I need to switch to the incident investigation

eng-buddy: [Saves current project state]

## Context Saved: API Migration
- What I was doing: Writing integration tests for payment endpoints
- Where I left off: 3 of 5 test cases complete
- Next steps:
  - Finish remaining test cases
  - Run full test suite
  - Deploy to staging
- Blockers: Waiting on staging environment refresh

Switching to: Incident Investigation
[Loads incident context]
```

### Blocker Management

```
User: What's blocking me?

eng-buddy:
## 🚧 Active Blockers

**CRITICAL - Escalate Today:**
### Waiting on Security team: API key rotation policy
- Started: 15 days ago ⚠️ AGING
- Blocking: 2 projects (New API, Mobile app)
- Last follow-up: 3 days ago
- Impact: Cannot deploy to production

**Recommended actions:**
1. Escalate to VP Engineering (Security team's manager)
2. Propose alternative: Temporary approval with audit trail
3. Schedule sync meeting with Security lead

Want me to draft an escalation email?
```

## 🎓 Personal Profile Integration

eng-buddy includes optional personal profile tracking (`knowledge/kioja-profile.md` in the example) that helps Claude understand:

- Work patterns and communication style
- Memory and organization preferences
- Stress indicators and coping mechanisms

**Important:** Profile information is for Claude's understanding only - it won't reference personal details back to you.

## 🤝 Contributing

### Making It Your Own

1. **Customize knowledge files** - Add your systems, team, preferences
2. **Adjust detection patterns** - Edit `hooks/eng-buddy-auto-log.sh`
3. **Add custom workflows** - Extend SKILL.md with your patterns
4. **Create team templates** - Share common incident/meeting templates

### Contributing Back

- Report bugs via GitHub issues
- Share improvements via pull requests
- Document patterns that worked for you
- Help others in discussions

## 📝 License

[Your chosen license - MIT recommended for open source]

## 🙏 Acknowledgments

Built for senior systems engineers who live in the intersection of:
- Complex distributed systems
- Constant interruptions and context switching
- High-stakes production incidents
- Cross-team coordination challenges
- "Remember that thing from 3 weeks ago?" moments

If you're constantly thinking "I should document this" but never have time - eng-buddy is for you.

## 📬 Support

- **Documentation**: [INSTALL.md](./INSTALL.md) for hook installation
- **Issues**: [Report bugs or request features](#)
- **Discussions**: [Share patterns and workflows](#)

---

**Remember**: eng-buddy is as valuable as the context you give it. The more you use it, the smarter it becomes about your systems, patterns, and work style.

Start today: `/eng-buddy`
