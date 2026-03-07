#!/usr/bin/env python3
"""
eng-buddy Slack Poller
Pulls DMs, private channel messages, @mentions, threads participated in,
and @here mentions since last check.
Classifies messages with Claude CLI, writes to inbox.db, and appends to
today's daily log.
"""

import json
import os
import re
import sys
import sqlite3
import subprocess
import time
from datetime import datetime, date, timedelta
from pathlib import Path
import urllib.request
import urllib.parse

# Ensure brain.py is importable from same directory
sys.path.insert(0, str(Path(__file__).parent))
import brain

TOKEN = "YOUR_SLACK_USER_TOKEN"
BASE_DIR = Path.home() / ".claude" / "eng-buddy"
STATE_FILE = BASE_DIR / "slack-poller-state.json"
TASK_INBOX = BASE_DIR / "task-inbox.md"
DB_PATH = BASE_DIR / "inbox.db"

# How far back to scan for participated threads (seconds)
THREAD_LOOKBACK_DAYS = 3


# ---------------------------------------------------------------------------
# Slack API helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
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
    """
    Fire two notifications:
    1. Banner to notification center (with sound)
    2. Persistent alert dialog (stays until dismissed)
    """
    banner_script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", banner_script])

    alert_script = (
        f'display alert "{title}" message "{message}" '
        f'buttons {{"OK"}} default button "OK"'
    )
    subprocess.Popen(["osascript", "-e", alert_script])


# ---------------------------------------------------------------------------
# inbox.db writer
# ---------------------------------------------------------------------------

def write_to_inbox_db(item, classification, section, draft_response, context_notes):
    """Write a classified Slack message card to inbox.db."""
    from datetime import timezone

    if not DB_PATH.exists():
        return

    proposed_actions = json.dumps([{
        "type": "send_slack_reply",
        "channel_id": item.get("channel_id", ""),
        "thread_ts": item.get("thread_ts", item.get("ts_str", "")),
        "draft": draft_response or "",
        "source": "slack",
        "sender": item.get("sender", ""),
        "channel_label": item.get("channel", ""),
    }])

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """INSERT INTO cards
               (source, timestamp, summary, classification, status,
                proposed_actions, execution_status,
                section, draft_response, context_notes, responded)
               VALUES ('slack', ?, ?, ?, 'pending', ?, 'not_run', ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                f"{item['sender']} via {item['channel']}: {item['text'][:200]}",
                classification,
                proposed_actions,
                section,
                draft_response,
                context_notes,
                1 if item.get("responded") else 0,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"DB write error (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Thread participation helpers
# ---------------------------------------------------------------------------

def check_responded(channel_id, thread_ts, user_id):
    """
    Return True if the authenticated user has replied in this thread
    after the most recent message from someone else.
    """
    try:
        result = slack_get("conversations.replies", {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 50,
        })
        if not result.get("ok"):
            return False

        replies = result.get("messages", [])
        if len(replies) < 2:
            return False

        # Walk messages newest-first (replies are oldest-first, so reverse)
        last_other_ts = None
        last_own_ts = None
        for msg in reversed(replies):
            msg_user = msg.get("user", "")
            msg_ts = float(msg.get("ts", 0))
            if msg_user == user_id:
                if last_own_ts is None:
                    last_own_ts = msg_ts
            else:
                if last_other_ts is None:
                    last_other_ts = msg_ts
            if last_own_ts is not None and last_other_ts is not None:
                break

        if last_own_ts is not None and last_other_ts is not None:
            return last_own_ts > last_other_ts
        return False
    except Exception as e:
        print(f"check_responded error (non-fatal): {e}")
        return False


def get_participated_threads(user_id, user_cache, oldest_ts, now_ts):
    """
    Find threads the user has participated in over the last THREAD_LOOKBACK_DAYS
    that have new messages since oldest_ts.
    Returns a list of message dicts with the same shape as messages_found items.
    """
    results = []
    seen_threads = set()

    try:
        # Search for messages where the user replied
        search = slack_get("search.messages", {
            "query": f"from:<@{user_id}>",
            "sort": "timestamp",
            "sort_dir": "desc",
            "count": 50,
        })
        if not search.get("ok"):
            return results

        for match in search.get("messages", {}).get("matches", []):
            match_ts = float(match.get("ts", 0))
            lookback_cutoff = datetime.now().timestamp() - THREAD_LOOKBACK_DAYS * 86400
            if match_ts < lookback_cutoff:
                continue

            thread_ts = match.get("ts", "")
            channel_obj = match.get("channel", {})
            channel_id = channel_obj.get("id", "")
            if not channel_id or not thread_ts:
                continue

            thread_key = f"{channel_id}:{thread_ts}"
            if thread_key in seen_threads:
                continue
            seen_threads.add(thread_key)

            time.sleep(0.3)
            # Check if thread has new replies since oldest
            replies_result = slack_get("conversations.replies", {
                "channel": channel_id,
                "ts": thread_ts,
                "oldest": oldest_ts,
                "limit": 20,
            })
            if not replies_result.get("ok"):
                continue

            new_replies = [
                r for r in replies_result.get("messages", [])
                if r.get("user") != user_id and not r.get("subtype")
            ]
            if not new_replies:
                continue

            channel_name = channel_obj.get("name", channel_id)
            channel_label = f"#{channel_name} (thread)"

            for reply in new_replies:
                r_ts = float(reply.get("ts", 0))
                if r_ts <= float(oldest_ts):
                    continue
                sender = resolve_user(reply.get("user", ""), user_cache)
                text = reply.get("text", "")
                dt = datetime.fromtimestamp(r_ts).strftime("%H:%M")
                responded = check_responded(channel_id, thread_ts, user_id)
                results.append({
                    "channel": channel_label,
                    "channel_id": channel_id,
                    "sender": sender,
                    "text": text[:400].replace("\n", " "),
                    "time": dt,
                    "ts": r_ts,
                    "ts_str": reply.get("ts", ""),
                    "thread_ts": thread_ts,
                    "is_mention": f"<@{user_id}>" in text,
                    "is_here_mention": "<!here>" in text or "<!channel>" in text,
                    "responded": responded,
                    "is_thread_reply": True,
                })
    except Exception as e:
        print(f"get_participated_threads error (non-fatal): {e}")

    return results


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------

def classify_with_claude(batch_items):
    """
    Call Claude CLI with context + classification prompt.
    Returns list of classification dicts keyed by index.
    """
    if not batch_items:
        return []

    context_prompt = brain.build_context_prompt(batch_items)

    numbered = []
    for i, item in enumerate(batch_items):
        numbered.append({
            "id": i,
            "sender": item.get("sender", ""),
            "channel": item.get("channel", ""),
            "text": item.get("text", ""),
            "thread_ts": item.get("thread_ts", ""),
            "responded": item.get("responded", False),
            "is_mention": item.get("is_mention", False),
            "is_here_mention": item.get("is_here_mention", False),
            "channel_id": item.get("channel_id", ""),
        })

    prompt = f"""{context_prompt}

Classify each Slack message below. For each, return JSON:
- section: "needs-action" or "no-action"
- classification: "needs-response", "fyi", "responded", "noise"
- draft_response: For needs-action items, write a context-aware draft reply. Use available info about Jira tickets, Freshservice tickets, or other systems mentioned. null for no-action.
- context_notes: Brief context about why this needs action or what the status is. null if obvious.

Messages:
{json.dumps(numbered, indent=2)}

Return ONLY a JSON array with one object per message, in order. No prose.
"""

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"Claude CLI error: {result.stderr[:200]}")
            return []

        output = result.stdout.strip()

        # Parse learning sections from Claude output
        try:
            brain.parse_learning(output)
        except Exception as e:
            print(f"brain.parse_learning error (non-fatal): {e}")

        # Extract JSON array from output (Claude may prepend/append text)
        json_match = re.search(r"\[\s*\{.*\}\s*\]", output, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        # Attempt direct parse if output is clean JSON
        return json.loads(output)

    except subprocess.TimeoutExpired:
        print("Claude CLI timed out (non-fatal)")
        return []
    except json.JSONDecodeError as e:
        print(f"Claude response JSON parse error (non-fatal): {e}")
        return []
    except Exception as e:
        print(f"classify_with_claude error (non-fatal): {e}")
        return []


def default_classification(item):
    """Fallback classification when Claude is unavailable."""
    is_dm = item.get("channel", "").startswith("DM:")
    is_mention = item.get("is_mention", False)
    is_here = item.get("is_here_mention", False)
    responded = item.get("responded", False)

    if responded:
        return {"section": "no-action", "classification": "responded",
                "draft_response": None, "context_notes": None}
    if is_dm or is_mention:
        return {"section": "needs-action", "classification": "needs-response",
                "draft_response": None, "context_notes": None}
    if is_here:
        return {"section": "needs-action", "classification": "fyi",
                "draft_response": None, "context_notes": None}
    return {"section": "no-action", "classification": "fyi",
            "draft_response": None, "context_notes": None}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # Timestamps
    last_check = state.get("last_check")
    oldest = last_check if last_check else str((datetime.now() - timedelta(hours=1)).timestamp())
    now_ts = str(datetime.now().timestamp())

    messages_found = []

    # -----------------------------------------------------------------------
    # 1. DMs, private channels, group DMs — unreads
    # -----------------------------------------------------------------------
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

                if channel.get("unread_count", 0) == 0:
                    continue

                time.sleep(0.3)
                history = slack_get("conversations.history", {
                    "channel": channel_id,
                    "oldest": oldest,
                    "limit": 20,
                })

                if not history.get("ok"):
                    continue

                for msg in history.get("messages", []):
                    if msg.get("user") == user_id:
                        continue
                    if msg.get("subtype"):
                        continue

                    text = msg.get("text", "")
                    is_mention = f"<@{user_id}>" in text
                    is_here = "<!here>" in text or "<!channel>" in text
                    thread_ts = msg.get("thread_ts", msg.get("ts", ""))

                    if is_dm or is_mpim or is_mention or is_here:
                        ts = float(msg.get("ts", 0))
                        sender = resolve_user(msg.get("user", ""), user_cache)
                        dt = datetime.fromtimestamp(ts).strftime("%H:%M")
                        responded = False
                        if thread_ts and thread_ts != msg.get("ts", ""):
                            responded = check_responded(channel_id, thread_ts, user_id)
                        messages_found.append({
                            "channel": channel_label,
                            "channel_id": channel_id,
                            "sender": sender,
                            "text": text[:400].replace("\n", " "),
                            "time": dt,
                            "ts": ts,
                            "ts_str": msg.get("ts", ""),
                            "thread_ts": thread_ts,
                            "is_mention": is_mention,
                            "is_here_mention": is_here,
                            "responded": responded,
                            "is_thread_reply": False,
                        })

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    # -----------------------------------------------------------------------
    # 2. @mentions in public channels via search
    # -----------------------------------------------------------------------
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
                channel_obj = match.get("channel", {})
                channel_name = channel_obj.get("name", "unknown")
                channel_id = channel_obj.get("id", "")
                thread_ts = match.get("ts", "")
                already = any(m["ts"] == ts for m in messages_found)
                if not already:
                    responded = check_responded(channel_id, thread_ts, user_id) if channel_id else False
                    messages_found.append({
                        "channel": f"#{channel_name}",
                        "channel_id": channel_id,
                        "sender": match.get("username", "unknown"),
                        "text": match.get("text", "")[:400].replace("\n", " "),
                        "time": dt,
                        "ts": ts,
                        "ts_str": match.get("ts", ""),
                        "thread_ts": thread_ts,
                        "is_mention": True,
                        "is_here_mention": False,
                        "responded": responded,
                        "is_thread_reply": False,
                    })
    except Exception as e:
        print(f"@mention search failed (non-fatal): {e}")

    # -----------------------------------------------------------------------
    # 3. @here / @channel mentions in public channels via search
    # -----------------------------------------------------------------------
    try:
        here_search = slack_get("search.messages", {
            "query": "<!here> OR <!channel>",
            "sort": "timestamp",
            "sort_dir": "desc",
            "count": 20,
        })
        if here_search.get("ok"):
            for match in here_search.get("messages", {}).get("matches", []):
                ts = float(match.get("ts", 0))
                if ts <= float(oldest):
                    continue
                msg_user = match.get("user", match.get("username", ""))
                if msg_user == user_id:
                    continue
                dt = datetime.fromtimestamp(ts).strftime("%H:%M")
                channel_obj = match.get("channel", {})
                channel_name = channel_obj.get("name", "unknown")
                channel_id = channel_obj.get("id", "")
                thread_ts = match.get("ts", "")
                already = any(m["ts"] == ts for m in messages_found)
                if not already:
                    messages_found.append({
                        "channel": f"#{channel_name}",
                        "channel_id": channel_id,
                        "sender": match.get("username", "unknown"),
                        "text": match.get("text", "")[:400].replace("\n", " "),
                        "time": dt,
                        "ts": ts,
                        "ts_str": match.get("ts", ""),
                        "thread_ts": thread_ts,
                        "is_mention": False,
                        "is_here_mention": True,
                        "responded": False,
                        "is_thread_reply": False,
                    })
    except Exception as e:
        print(f"@here search failed (non-fatal): {e}")

    # -----------------------------------------------------------------------
    # 4. Threads the user participated in (last THREAD_LOOKBACK_DAYS days)
    # -----------------------------------------------------------------------
    try:
        thread_msgs = get_participated_threads(user_id, user_cache, oldest, now_ts)
        for tm in thread_msgs:
            already = any(m["ts"] == tm["ts"] for m in messages_found)
            if not already:
                messages_found.append(tm)
    except Exception as e:
        print(f"get_participated_threads failed (non-fatal): {e}")

    # Sort by timestamp ascending
    messages_found.sort(key=lambda x: x["ts"])

    if not messages_found:
        print(f"[{datetime.now().strftime('%H:%M')}] No new messages")
        state["last_check"] = now_ts
        state["user_cache"] = user_cache
        save_state(state)
        return

    print(f"[{datetime.now().strftime('%H:%M')}] Collected {len(messages_found)} message(s), classifying...")

    # -----------------------------------------------------------------------
    # 5. Batch classify with Claude
    # -----------------------------------------------------------------------
    classifications = classify_with_claude(messages_found)

    # Build lookup by id; fall back to default if Claude returned fewer items
    classif_map = {}
    for c in classifications:
        idx = c.get("id")
        if idx is not None:
            classif_map[idx] = c

    # -----------------------------------------------------------------------
    # 6. Write to inbox.db + collect needs-action for notification
    # -----------------------------------------------------------------------
    needs_action_items = []

    for i, item in enumerate(messages_found):
        clf = classif_map.get(i, None)
        if clf is None:
            clf = default_classification(item)

        section = clf.get("section", "needs-action")
        classification = clf.get("classification", "fyi")
        draft_response = clf.get("draft_response")
        context_notes = clf.get("context_notes")

        write_to_inbox_db(item, classification, section, draft_response, context_notes)

        if section == "needs-action" and not item.get("responded"):
            needs_action_items.append((item, classification, draft_response))

    # -----------------------------------------------------------------------
    # 7. Write to daily log
    # -----------------------------------------------------------------------
    check_time = datetime.now().strftime("%H:%M")
    lines = [f"\n### Polled at {check_time} — {len(messages_found)} new\n"]
    for i, item in enumerate(messages_found):
        clf = classif_map.get(i, default_classification(item))
        flag = ""
        if item["is_mention"]:
            flag += " [mention]"
        if item["is_here_mention"]:
            flag += " [here]"
        if item.get("is_thread_reply"):
            flag += " [thread]"
        responded_tag = " [responded]" if item.get("responded") else ""
        lines.append(
            f"- **{item['channel']}**{flag}{responded_tag} "
            f"[{item['time']}] **{item['sender']}**: {item['text']}\n"
        )
    append_to_daily_log("".join(lines))
    print(f"[{datetime.now().strftime('%H:%M')}] Logged {len(messages_found)} message(s) to daily log")

    # -----------------------------------------------------------------------
    # 8. Notify for needs-action items
    # -----------------------------------------------------------------------
    for item, classification, draft_response in needs_action_items:
        preview = (draft_response[:80] if draft_response else item["text"][:80])
        notify(
            title=f"eng-buddy: {classification} from {item['sender']}",
            message=f"{item['channel']}\n{preview}",
        )

    print(
        f"[{datetime.now().strftime('%H:%M')}] "
        f"{len(needs_action_items)} needs-action item(s) written to inbox.db"
    )

    # -----------------------------------------------------------------------
    # 9. Persist state
    # -----------------------------------------------------------------------
    state["last_check"] = now_ts
    state["user_cache"] = user_cache
    save_state(state)


if __name__ == "__main__":
    main()
