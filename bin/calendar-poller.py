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
CLAUDE_FETCH_TIMEOUT_SECONDS = 120
CLAUDE_ENRICH_TIMEOUT_SECONDS = 45


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
    """Fetch from today through the active weekly horizon."""
    today = today or date.today()
    if today.weekday() == 6:  # Sunday
        end_date = today + timedelta(days=7)
    else:
        end_date = today + timedelta(days=(6 - today.weekday()))
    return today, end_date


def _claude_env():
    """Return a clean env for spawning the Claude CLI from eng-buddy."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    path_parts = ["/opt/homebrew/bin", "/usr/local/bin"]
    existing_path = env.get("PATH", "")
    if existing_path:
        path_parts.append(existing_path)
    env["PATH"] = ":".join(path_parts)
    return env


def _extract_json_array(text):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return []


def _build_single_day_prompt(target_date):
    return (
        f"Use the Google Calendar MCP list-events tool to get all events for {target_date.isoformat()}. "
        f"Use calendarId 'primary'. "
        f"Return ONLY a JSON array of objects with keys: "
        f"id, summary, start (ISO string), end (ISO string), "
        f"location, hangout_link (Google Meet/Zoom URL if present), "
        f"attendees (array of email strings), description (first 200 chars). "
        f"No prose, just the JSON array."
    )


def _fetch_events_for_date(target_date):
    """Fetch all events for a single day."""
    prompt = _build_single_day_prompt(target_date)
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True,
        text=True,
        timeout=CLAUDE_FETCH_TIMEOUT_SECONDS,
        env=_claude_env(),
    )
    return _extract_json_array(result.stdout)


def _dedupe_events(events):
    seen = set()
    deduped = []
    for event in events:
        key = (
            event.get("id"),
            event.get("start"),
            event.get("end"),
            event.get("summary"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


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
    current_date = start_date
    events = []
    while current_date <= end_date:
        try:
            events.extend(_fetch_events_for_date(current_date))
        except Exception as e:
            print(
                f"[{datetime.now().strftime('%H:%M')}] Calendar fetch failed for "
                f"{current_date.isoformat()}: {e}"
            )
        current_date += timedelta(days=1)

    return _dedupe_events(events)


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
            capture_output=True,
            text=True,
            timeout=CLAUDE_ENRICH_TIMEOUT_SECONDS,
            env=_claude_env(),
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

    # Rewrite the current calendar horizon each run so upcoming sections do not
    # retain stale events from a previous week.
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
        print(f"[{now.strftime('%H:%M')}] No events found in the current weekly horizon")

    state["last_fetch"] = current_slot
    save_state(state)


if __name__ == "__main__":
    main()
