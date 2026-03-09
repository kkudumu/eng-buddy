# eng-buddy Dashboard

## Start

```bash
cd ~/.claude/eng-buddy/dashboard
./start.sh --background
```

`--background` is intentionally non-blocking for cold starts. Expect `ALREADY_RUNNING`, `STARTED`, or `STARTING` while the LaunchAgent finishes bringing up the dashboard.

To wait for health and only open the browser after the dashboard is reachable:

```bash
cd ~/.claude/eng-buddy/dashboard
./start.sh --ensure-open
```

`--ensure-open` performs a cold-start health check, retries once with a restart if needed, and prints `READY` only after the browser-safe launch path succeeds.

Managed by `launchd` and served at http://127.0.0.1:7777

## Background pollers (LaunchAgents)

| Poller | Interval | Log |
|---|---|---|
| Freshservice | varies | freshservice-ingestor.log |
| Gmail | 10 min | gmail-poller.log |
| Slack | 10 min | slack-poller.log |
| Jira | 5 min | jira-poller.log |

Check all: `launchctl list | grep engbuddy`
