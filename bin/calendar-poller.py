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
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

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


def compute_fetch_window(today=None):
    """Fetch from today through the active weekly horizon.

    Sunday rolls forward to include the following Monday-Sunday week so the
    dashboard can show "today" separately from "upcoming this week".
    """
    today = today or date.today()
    if today.weekday() == 6:  # Sunday
        end_date = today + timedelta(days=7)
    else:
        end_date = today + timedelta(days=(6 - today.weekday()))
    return today, end_date


def format_event_summary(event):
    raw_start = str(event.get("start", "")).strip()
    title = (event.get("summary") or "No title").strip()

    if raw_start:
        try:
            if "T" in raw_start:
                start_dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                label = start_dt.strftime("%a %m/%d %H:%M")
            else:
                start_day = datetime.strptime(raw_start, "%Y-%m-%d")
                label = f"{start_day.strftime('%a %m/%d')} ALL DAY"
            return f"{label} — {title}"
        except ValueError:
            pass

    return title


def fetch_events():
    """Use Claude CLI to fetch calendar events for the active weekly horizon."""
    start_date, end_date = compute_fetch_window()
    prompt = (
        f"Use the Google Calendar MCP list-events tool to get all events from {start_date.isoformat()} "
        f"through {end_date.isoformat()} inclusive. "
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
            capture_output=True, text=True, timeout=30        )
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

Here are the calendar events in scope. For each, add:
- context_notes: Relevant context from Jira tickets, recent emails, or Slack threads related to the meeting topic or attendees. Include prep suggestions.
- priority: "high" (needs prep), "normal", or "low" (social/optional)
- prep_needed: true/false

Events:
{events_json}

Return ONLY a JSON array with the original fields plus context_notes, priority, prep_needed. No prose."""

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=45        )
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

    # Rewrite the calendar horizon each run so the dashboard always reflects the
    # current week/next-week window without stale events lingering.
    conn.execute("DELETE FROM cards WHERE source = 'calendar'")

    for event in events:
        event_start = event.get("start") or datetime.now(timezone.utc).isoformat()
        summary = format_event_summary(event)
        section = "needs-action" if event.get("prep_needed") else "no-action"
        proposed = json.dumps([{
            "type": "calendar_event",
            "id": event.get("id", ""),
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
                event_start,
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
