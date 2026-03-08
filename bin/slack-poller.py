#!/usr/bin/env python3
"""
eng-buddy Slack Poller
Fetches recent Slack messages via Claude CLI + Slack MCP.
Classifies messages with Claude CLI, writes to inbox.db, and appends to
today's daily log.
"""

import json
import os
import re
import sys
import sqlite3
import subprocess
from datetime import datetime, date, timezone
from pathlib import Path

# Ensure brain.py is importable from same directory
sys.path.insert(0, str(Path(__file__).parent))
import brain

BASE_DIR = Path.home() / ".claude" / "eng-buddy"
STATE_FILE = BASE_DIR / "slack-poller-state.json"
DB_PATH = BASE_DIR / "inbox.db"


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Daily log helpers
# ---------------------------------------------------------------------------

def get_daily_log_path():
    today = date.today().strftime("%Y-%m-%d")
    return BASE_DIR / "daily" / f"{today}.md"


def append_to_daily_log(content):
    log_path = get_daily_log_path()
    if not log_path.exists():
        return
    existing = log_path.read_text()
    if "## Slack Unreads" not in existing:
        with open(log_path, "a") as f:
            f.write("\n## Slack Unreads\n")
    with open(log_path, "a") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify(title, message):
    safe_title = str(title).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    safe_message = str(message).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    banner_script = f'display notification "{safe_message}" with title "{safe_title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", banner_script])

    alert_script = (
        f'display alert "{safe_title}" message "{safe_message}" '
        f'buttons {{"OK"}} default button "OK"'
    )
    subprocess.Popen(["osascript", "-e", alert_script])


# ---------------------------------------------------------------------------
# inbox.db writer
# ---------------------------------------------------------------------------

def _clean_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_timestamp(raw_value):
    value = _clean_text(raw_value)
    if not value:
        return ""

    try:
        if re.fullmatch(r"\d+(\.\d+)?", value):
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()

        normalized = value.replace(" ", "T") if "T" not in value and " " in value else value
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def normalize_slack_item(item):
    if not isinstance(item, dict):
        return None

    normalized = {
        "sender": _clean_text(item.get("sender") or item.get("from") or item.get("author") or item.get("user")),
        "channel": _clean_text(item.get("channel") or item.get("channel_name") or item.get("conversation") or item.get("room")),
        "channel_id": _clean_text(item.get("channel_id") or item.get("conversation_id")),
        "text": _clean_text(item.get("text") or item.get("message") or item.get("body") or item.get("summary"))[:400],
        "thread_ts": _clean_text(item.get("thread_ts") or item.get("thread") or item.get("parent_ts")),
        "timestamp": _normalize_timestamp(item.get("timestamp") or item.get("ts") or item.get("message_ts")),
        "section": _clean_text(item.get("section") or "no-action").lower(),
        "classification": _clean_text(item.get("classification") or item.get("label") or "fyi").lower(),
        "draft_response": _clean_text(item.get("draft_response") or item.get("draft") or item.get("reply_draft")) or None,
        "context_notes": _clean_text(item.get("context_notes") or item.get("context") or item.get("notes")) or None,
    }

    responded = item.get("responded")
    if isinstance(responded, str):
        normalized["responded"] = responded.strip().lower() in {"1", "true", "yes", "y"}
    elif responded is None:
        normalized["responded"] = normalized["classification"] == "responded"
    else:
        normalized["responded"] = bool(responded)

    if not any([
        normalized["sender"],
        normalized["channel"],
        normalized["channel_id"],
        normalized["thread_ts"],
        normalized["text"],
    ]):
        return None

    return normalized

def write_to_inbox_db(item):
    """Write a classified Slack message card to inbox.db."""
    if not DB_PATH.exists():
        return

    proposed_actions = json.dumps([{
        "type": "send_slack_reply",
        "channel_id": item.get("channel_id", ""),
        "thread_ts": item.get("thread_ts", ""),
        "draft": item.get("draft_response") or "",
        "source": "slack",
        "sender": item.get("sender", ""),
        "channel_label": item.get("channel", ""),
    }])

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """INSERT OR IGNORE INTO cards
               (source, timestamp, summary, classification, status,
                proposed_actions, execution_status,
               section, draft_response, context_notes, responded)
               VALUES ('slack', ?, ?, ?, 'pending', ?, 'not_run', ?, ?, ?, ?)""",
            (
                item.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                f"{item.get('sender') or 'Someone'} via {item.get('channel') or 'Slack'}: "
                f"{(item.get('text') or item.get('context_notes') or item.get('draft_response') or '(no preview)')[:200]}",
                item.get("classification", "fyi"),
                proposed_actions,
                item.get("section", "no-action"),
                item.get("draft_response"),
                item.get("context_notes"),
                1 if item.get("responded") else 0,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"DB write error (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Fetch + classify via Claude CLI + Slack MCP
# ---------------------------------------------------------------------------

def fetch_and_classify():
    """
    Single Claude CLI call that uses Slack MCP to fetch recent messages
    and classify them with brain context.
    """
    context = brain.build_context_prompt()

    prompt = f"""{context}

You have access to the Slack MCP tools. Do the following:

1. Call slack_list_channels to get all channels (include DMs/group DMs).
2. For channels with recent activity, call slack_get_channel_history (limit 15 messages per channel, check at most 10 channels) to find messages from the last 24 hours.
3. Identify messages that need my attention:
   - Direct messages to me
   - Messages that @mention me
   - @here/@channel mentions
   - New replies in threads I participated in
   - Skip messages I sent myself

4. For each relevant message, classify it:
   - section: "needs-action" or "no-action"
   - classification: "needs-response", "fyi", "responded", "noise"
   - draft_response: For needs-action items, draft a context-aware reply. null for no-action.
   - context_notes: Brief context about why this needs action. null if obvious.

Return ONLY a JSON array of objects with these keys:
sender, channel, channel_id, text (first 400 chars), thread_ts, timestamp, section, classification, draft_response, context_notes, responded (boolean)

Do not omit keys. Use empty strings for unknown string fields and false for responded when unsure.

If there are no relevant messages, return an empty array: []
No prose, just the JSON array."""

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"Claude CLI error: {result.stderr[:200]}")
            return []

        output = result.stdout.strip()

        # Parse learning from Claude output
        try:
            brain.parse_learning(output)
        except Exception as e:
            print(f"brain.parse_learning error (non-fatal): {e}")

        # Extract JSON array
        json_match = re.search(r"\[\s*\{.*\}\s*\]", output, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        # Check for empty array
        if re.search(r"\[\s*\]", output):
            return []

        # Try direct parse
        return json.loads(output)

    except subprocess.TimeoutExpired:
        print("Claude CLI timed out (non-fatal)")
        return []
    except json.JSONDecodeError as e:
        print(f"JSON parse error (non-fatal): {e}")
        return []
    except Exception as e:
        print(f"fetch_and_classify error (non-fatal): {e}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    state = load_state()
    now = datetime.now()

    print(f"[{now.strftime('%H:%M')}] Fetching and classifying Slack messages via MCP...")
    raw_messages = fetch_and_classify()
    messages = []
    skipped_count = 0

    for item in raw_messages:
        normalized = normalize_slack_item(item)
        if not normalized:
            skipped_count += 1
            print(f"[{now.strftime('%H:%M')}] Skipping malformed Slack item: {json.dumps(item)[:300]}")
            continue
        messages.append(normalized)

    if not messages:
        print(f"[{now.strftime('%H:%M')}] No new messages needing attention")
        state["last_check"] = str(now.timestamp())
        save_state(state)
        return

    print(f"[{now.strftime('%H:%M')}] Processing {len(messages)} message(s)...")
    if skipped_count:
        print(f"[{now.strftime('%H:%M')}] Skipped {skipped_count} malformed Slack item(s)")

    # Write to inbox.db + collect needs-action for notification
    needs_action_items = []

    for item in messages:
        write_to_inbox_db(item)
        if item.get("section") == "needs-action" and not item.get("responded"):
            needs_action_items.append(item)

    # Write to daily log
    check_time = now.strftime("%H:%M")
    lines = [f"\n### Polled at {check_time} — {len(messages)} new\n"]
    for item in messages:
        flag = ""
        responded_tag = " [responded]" if item.get("responded") else ""
        lines.append(
            f"- **{item.get('channel', '?')}**{flag}{responded_tag} "
            f"**{item.get('sender', '?')}**: {item.get('text', '')[:200]}\n"
        )
    append_to_daily_log("".join(lines))
    print(f"[{now.strftime('%H:%M')}] Logged {len(messages)} message(s) to daily log")

    # Notify for needs-action items
    for item in needs_action_items:
        preview = (item.get("draft_response") or item.get("text", ""))[:80]
        notify(
            title=f"eng-buddy: {item.get('classification', 'message')} from {item.get('sender', '?')}",
            message=f"{item.get('channel', '')}\n{preview}",
        )

    print(
        f"[{now.strftime('%H:%M')}] "
        f"{len(needs_action_items)} needs-action item(s) written to inbox.db"
    )

    # Persist state
    state["last_check"] = str(now.timestamp())
    save_state(state)


if __name__ == "__main__":
    main()
