#!/usr/bin/env python3
"""
eng-buddy Slack Poller
Pulls DMs, private channel messages, and @mentions since last check.
Appends to today's daily log.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
import urllib.request
import urllib.parse

TOKEN = "YOUR_SLACK_USER_TOKEN"
BASE_DIR = Path.home() / ".claude" / "eng-buddy"
STATE_FILE = BASE_DIR / "slack-poller-state.json"
TASK_INBOX = BASE_DIR / "task-inbox.md"

# Patterns that suggest someone needs something from you
TASK_SIGNAL_PATTERNS = [
    r"isn'?t working",
    r"not working",
    r"doesn'?t work",
    r"having (a )?problem",
    r"having (an )?issue",
    r"can'?t (access|login|log in|connect|open|see|find|get)",
    r"(something|this) is broken",
    r"getting (an )?error",
    r"failed?",
    r"help( me)?",
    r"need(s)? (help|access|a|to)",
    r"(request|please|can you|could you).{0,40}(help|fix|check|look|update|add|remove|reset|set up|setup|configure)",
    r"closed (out )?this ticket",
    r"this (ticket|request) (wasn'?t|was never|hasn'?t been)",
    r"not (fulfilled|completed|done|resolved)",
    r"freshservice\.com/support/tickets/\d+",
    r"itwork\d*-\d+",
    r"(locked out|no access|lost access|can'?t get in)",
    r"not (provisioned|set up|configured)",
    r"waiting (on|for) (you|IT|this)",
    r"follow.?up",
]


def slack_get(method, params=None, retry=5):
    url = f"https://slack.com/api/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    for attempt in range(retry + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retry:
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
            else:
                raise


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def resolve_user(user_id, user_cache):
    if user_id in user_cache:
        return user_cache[user_id]
    try:
        result = slack_get("users.info", {"user": user_id})
        if result.get("ok"):
            profile = result["user"].get("profile", {})
            name = profile.get("display_name") or profile.get("real_name") or user_id
            user_cache[user_id] = name
            return name
    except Exception:
        pass
    user_cache[user_id] = user_id
    return user_id


def get_daily_log_path():
    today = date.today().strftime("%Y-%m-%d")
    return BASE_DIR / "daily" / f"{today}.md"


def append_to_daily_log(content):
    log_path = get_daily_log_path()
    if not log_path.exists():
        return
    existing = log_path.read_text()
    if "## 💬 Slack Unreads" not in existing:
        with open(log_path, "a") as f:
            f.write("\n## 💬 Slack Unreads\n")
    with open(log_path, "a") as f:
        f.write(content)


def main():
    state = load_state()
    user_cache = state.get("user_cache", {})

    # Resolve own user ID
    if not state.get("user_id"):
        auth = slack_get("auth.test")
        if not auth.get("ok"):
            print(f"Auth failed: {auth.get('error')}")
            sys.exit(1)
        state["user_id"] = auth["user_id"]
        state["user_name"] = auth.get("user", "")
        print(f"Authenticated as {state['user_name']} ({state['user_id']})")

    user_id = state["user_id"]

    # Default oldest: last check or last hour on first run
    last_check = state.get("last_check")
    oldest = last_check if last_check else str((datetime.now() - timedelta(hours=1)).timestamp())
    now_ts = str(datetime.now().timestamp())

    messages_found = []

    # --- DMs and private channels (each type called separately) ---
    for conv_type in ["im", "private_channel", "mpim"]:
        cursor = None
        while True:
            params = {
                "types": conv_type,
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor

            result = slack_get("conversations.list", params)
            if not result.get("ok"):
                print(f"conversations.list({conv_type}) failed: {result.get('error')}")
                break

            for channel in result.get("channels", []):
                channel_id = channel["id"]
                is_dm = channel.get("is_im", False)
                is_mpim = channel.get("is_mpim", False)

                if is_dm:
                    other_user = channel.get("user", channel_id)
                    channel_label = f"DM: {resolve_user(other_user, user_cache)}"
                elif is_mpim:
                    channel_label = f"Group DM: {channel.get('name', channel_id)}"
                else:
                    channel_label = f"#{channel.get('name', channel_id)}"

                # Skip channels with no unreads (avoids unnecessary API calls)
                if channel.get("unread_count", 0) == 0:
                    continue

                time.sleep(0.3)  # avoid rate limits
                history = slack_get("conversations.history", {
                    "channel": channel_id,
                    "oldest": oldest,
                    "limit": 20,
                })

                if not history.get("ok"):
                    continue

                for msg in history.get("messages", []):
                    if msg.get("user") == user_id:
                        continue  # skip own messages
                    if msg.get("subtype"):
                        continue  # skip system messages

                    text = msg.get("text", "")
                    is_mention = f"<@{user_id}>" in text

                    # Include: all DMs, all group DMs, mentions in private channels
                    if is_dm or is_mpim or is_mention:
                        ts = float(msg.get("ts", 0))
                        sender = resolve_user(msg.get("user", ""), user_cache)
                        dt = datetime.fromtimestamp(ts).strftime("%H:%M")
                        messages_found.append({
                            "channel": channel_label,
                            "sender": sender,
                            "text": text[:300].replace("\n", " "),
                            "time": dt,
                            "ts": ts,
                            "is_mention": is_mention,
                        })

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    # --- @mentions in public channels via search ---
    try:
        search = slack_get("search.messages", {
            "query": f"<@{user_id}>",
            "sort": "timestamp",
            "sort_dir": "desc",
            "count": 20,
        })
        if search.get("ok"):
            for match in search.get("messages", {}).get("matches", []):
                ts = float(match.get("ts", 0))
                if ts <= float(oldest):
                    continue
                dt = datetime.fromtimestamp(ts).strftime("%H:%M")
                channel_name = match.get("channel", {}).get("name", "unknown")
                # Avoid duplicates from private channel scan above
                already = any(m["ts"] == ts for m in messages_found)
                if not already:
                    messages_found.append({
                        "channel": f"#{channel_name}",
                        "sender": match.get("username", "unknown"),
                        "text": match.get("text", "")[:300].replace("\n", " "),
                        "time": dt,
                        "ts": ts,
                        "is_mention": True,
                    })
    except Exception as e:
        print(f"Search failed (non-fatal): {e}")

    # Sort by time
    messages_found.sort(key=lambda x: x["ts"])

    # --- Detect task-worthy messages and write to task inbox ---
    tasks_detected = []
    for msg in messages_found:
        text_lower = msg["text"].lower()
        for pattern in TASK_SIGNAL_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                tasks_detected.append(msg)
                break  # one match is enough

    if tasks_detected:
        # Load existing inbox to avoid duplicates
        existing_inbox = TASK_INBOX.read_text() if TASK_INBOX.exists() else ""
        with open(TASK_INBOX, "a") as f:
            if not existing_inbox:
                f.write("# Slack Task Inbox\n\n")
                f.write("*Potential tasks detected from Slack. Review with eng-buddy.*\n\n")
            for msg in tasks_detected:
                ts_str = str(msg["ts"])
                if ts_str in existing_inbox:
                    continue  # already logged
                dt = datetime.fromtimestamp(msg["ts"]).strftime("%Y-%m-%d %H:%M")
                f.write(f"## [ ] {msg['sender']} via {msg['channel']} — {dt}\n")
                f.write(f"{msg['text']}\n")
                f.write(f"<!-- ts:{ts_str} -->\n\n")
        print(f"[{datetime.now().strftime('%H:%M')}] Detected {len(tasks_detected)} potential task(s) → task-inbox.md")

    # Write to daily log
    if messages_found:
        check_time = datetime.now().strftime("%H:%M")
        lines = [f"\n### Polled at {check_time} — {len(messages_found)} new\n"]
        for msg in messages_found:
            flag = " 🔔" if msg["is_mention"] else ""
            lines.append(f"- **{msg['channel']}**{flag} [{msg['time']}] **{msg['sender']}**: {msg['text']}\n")
        append_to_daily_log("".join(lines))
        print(f"[{datetime.now().strftime('%H:%M')}] Logged {len(messages_found)} messages to daily log")
    else:
        print(f"[{datetime.now().strftime('%H:%M')}] No new messages")

    state["last_check"] = now_ts
    state["user_cache"] = user_cache
    save_state(state)


if __name__ == "__main__":
    main()
