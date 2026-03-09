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
JIRA_USER = "kioja.kudumu@klaviyo.com"
JIRA_BOARD_NAME = "Systems"
JIRA_PROJECT_KEY = "ITWORK2"

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
        f"1. Call jira_get_agile_boards with board_name='{JIRA_BOARD_NAME}' and project_key='{JIRA_PROJECT_KEY}'.\n"
        f"2. Choose the board that best matches project '{JIRA_PROJECT_KEY}' and the Systems sprint workflow.\n"
        "3. Call jira_get_sprints_from_board with that board's ID, state='active'.\n"
        f"4. If multiple active sprints exist, prefer the sprint whose name contains '{JIRA_PROJECT_KEY}' or starts with 'SYSTEMS'.\n"
        f"5. Call jira_search with JQL: assignee = \"{JIRA_USER}\" "
        f"AND project = {JIRA_PROJECT_KEY} AND sprint = <sprint_id> ORDER BY priority DESC, status ASC\n"
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
    jira_key = issue.get('key', '')
    summary = f"{jira_key} — {issue.get('summary', '')}"
    proposed = json.dumps([{
        "type": "review_jira_issue",
        "draft": f"Review and update Jira issue {jira_key}: {issue.get('summary')}",
        "source": "jira",
        "url": issue.get("url", "")
    }])
    # UNIQUE(source, summary) index prevents duplicates via INSERT OR IGNORE
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
