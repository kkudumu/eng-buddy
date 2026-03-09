# eng-buddy Dashboard

## Start

```bash
cd ~/.claude/eng-buddy/dashboard
./start.sh --background
```

Managed by `launchd` and served at http://127.0.0.1:7777

## Background pollers (LaunchAgents)

| Poller | Interval | Log |
|---|---|---|
| Freshservice | varies | freshservice-ingestor.log |
| Gmail | 10 min | gmail-poller.log |
| Slack | 10 min | slack-poller.log |
| Jira | 5 min | jira-poller.log |

Check all: `launchctl list | grep engbuddy`
