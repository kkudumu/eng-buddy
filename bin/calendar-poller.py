#!/usr/bin/env python3
"""
eng-buddy Calendar Poller
Fetches today's events via Claude CLI + Google Calendar MCP.
Enriches events with context from Jira/Freshservice/email.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, date, timezone
from pathlib import Path

# Strip CLAUDECODE env var so subprocess claude calls don't fail with
# "nested session" error when eng-buddy is launched from Claude Code.
_claude_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

# Allow importing brain.py from same directory
sys.path.insert(0, str(Path(__file__).parent))
import brain

BASE_DIR = Path.home() / ".claude" / "eng-buddy"
DB_PATH = BASE_DIR / "inbox.db"
STATE_FILE = BASE_DIR / "calendar-poller-state.json"


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_events():
    """Use Claude CLI to fetch today's calendar events via Google Calendar MCP."""
    today = date.today().isoformat()
    prompt = (
        f"Use the Google Calendar MCP list-events tool to get all events for today ({today}). "
        f"Use calendarId 'primary'. "
        f"Return ONLY a JSON array of objects with keys: "
        f"id, summary, start (ISO string), end (ISO string), "
        f"location, hangout_link (Google Meet/Zoom URL if present), "
        f"attendees (array of email strings), description (first 200 chars). "
        f"No prose, just the JSON array."
    )
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=30, env=_claude_env
        )
        match = re.search(r'\[.*\]', result.stdout, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M')}] Calendar fetch failed: {e}")
    return []


def enrich_events(events):
    """Call Claude CLI to add context notes for each event."""
    if not events:
        return []

    context = brain.build_context_prompt(events)
    events_json = json.dumps(events, indent=2)

    prompt = f"""{context}

Here are today's calendar events. For each, add:
- context_notes: Relevant context from Jira tickets, recent emails, or Slack threads related to the meeting topic or attendees. Include prep suggestions.
- priority: "high" (needs prep), "normal", or "low" (social/optional)
- prep_needed: true/false

Events:
{events_json}

Return ONLY a JSON array with the original fields plus context_notes, priority, prep_needed. No prose."""

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=45, env=_claude_env
        )
        match = re.search(r'\[.*\]', result.stdout, re.DOTALL)
        if match:
            enriched = json.loads(match.group(0))
            brain.parse_learning(result.stdout)
            return enriched
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M')}] Calendar enrichment failed: {e}")

    return events


def write_to_db(events):
    """Write calendar events as cards to inbox.db."""
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(DB_PATH)
    today = date.today().isoformat()

    # Clear today's calendar cards and rewrite (events may have changed)
    conn.execute(
        "DELETE FROM cards WHERE source = 'calendar' AND date(timestamp) = ?",
        [today]
    )

    for event in events:
        summary = f"{event.get('start', '?')[:5]} — {event.get('summary', 'No title')}"
        section = "needs-action" if event.get("prep_needed") else "no-action"
        proposed = json.dumps([{
            "type": "calendar_event",
            "summary": event.get("summary", ""),
            "start": event.get("start", ""),
            "end": event.get("end", ""),
            "hangout_link": event.get("hangout_link", ""),
            "attendees": event.get("attendees", []),
        }])
        conn.execute(
            """INSERT OR IGNORE INTO cards
               (source, timestamp, summary, classification, status,
                proposed_actions, execution_status, section, context_notes)
               VALUES ('calendar', ?, ?, ?, 'pending', ?, 'not_run', ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                summary,
                event.get("priority", "normal"),
                proposed,
                section,
                event.get("context_notes", ""),
            )
        )

    conn.commit()
    conn.close()


def main():
    state = load_state()
    now = datetime.now()

    # Skip if already fetched this half-hour
    last_fetch = state.get("last_fetch", "")
    current_slot = now.strftime("%Y-%m-%d-%H") + ("-00" if now.minute < 30 else "-30")
    if last_fetch == current_slot:
        print(f"[{now.strftime('%H:%M')}] Already fetched this slot, skipping")
        return

    print(f"[{now.strftime('%H:%M')}] Fetching calendar events...")
    events = fetch_events()

    if events:
        print(f"[{now.strftime('%H:%M')}] Enriching {len(events)} events with context...")
        events = enrich_events(events)
        write_to_db(events)
        print(f"[{now.strftime('%H:%M')}] Wrote {len(events)} calendar cards to inbox.db")
    else:
        print(f"[{now.strftime('%H:%M')}] No events found for today")

    state["last_fetch"] = current_slot
    save_state(state)


if __name__ == "__main__":
    main()
