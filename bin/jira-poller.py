#!/usr/bin/env python3
"""
eng-buddy Jira Poller
Fetches Jira issues assigned to current user since last check.
Writes cards to inbox.db.
"""
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path.home() / ".claude" / "eng-buddy"
STATE_FILE = BASE_DIR / "jira-ingestor-state.json"
DB_PATH = BASE_DIR / "inbox.db"

def get_last_checked():
    try:
        state = json.loads(STATE_FILE.read_text())
        return state.get("last_checked", "2020-01-01T00:00:00Z")
    except Exception:
        return "2020-01-01T00:00:00Z"

def set_last_checked(ts):
    STATE_FILE.write_text(json.dumps({"last_checked": ts}))

def fetch_jira_issues():
    """Use claude --print to call Atlassian MCP and get assigned issues."""
    prompt = (
        "Use the Atlassian MCP tools to find my current sprint tasks:\n"
        "1. Call jira_get_agile_boards to find the board with 'Systems' in its name.\n"
        "2. Call jira_get_sprints_from_board with that board's ID, state='active' to get the current sprint.\n"
        "3. Call jira_search with JQL: assignee = 'kioja.kudumu@klaviyo.com' "
        "AND sprint = <sprint_id> ORDER BY priority DESC, status ASC\n"
        "Fields: summary,status,priority,issuetype,labels,updated. Limit: 30.\n"
        "Return ONLY a JSON array of objects with keys: "
        "key, summary, status, priority, updated, url. "
        "No prose, just the JSON array. Empty array [] if no issues found."
    )
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout.strip()
    # Extract JSON array from output
    match = re.search(r'\[.*\]', output, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return []

def write_card(conn, issue):
    summary = f"{issue.get('key', '')} — {issue.get('summary', '')}"
    proposed = json.dumps([{
        "type": "review_jira_issue",
        "draft": f"Review and update Jira issue {issue.get('key')}: {issue.get('summary')}",
        "source": "jira",
        "url": issue.get("url", "")
    }])
    conn.execute(
        """INSERT OR IGNORE INTO cards
           (source, timestamp, summary, classification, status, proposed_actions, execution_status)
           VALUES (?, ?, ?, ?, 'pending', ?, 'not_run')""",
        ("jira", datetime.now(timezone.utc).isoformat(),
         summary,
         issue.get("priority", "needs-response").lower(),
         proposed)
    )

def main():
    issues = fetch_jira_issues()
    if not issues:
        print(f"[{datetime.now()}] No Jira issues found.")
        return

    conn = sqlite3.connect(DB_PATH)
    for issue in issues:
        write_card(conn, issue)
    conn.commit()
    conn.close()
    set_last_checked(datetime.now(timezone.utc).isoformat())
    print(f"[{datetime.now()}] Processed {len(issues)} Jira issues.")

if __name__ == "__main__":
    main()
