#!/usr/bin/env python3
"""
eng-buddy Gmail Poller
Checks email-watches.md for tracked threads/senders/subjects.
On match: updates linked task in task-inbox.md or creates new task entry.
Appends to today's daily log.

Watch sources:
  - Proactive: registered by eng-buddy ("watch for reply from X about Y")
  - Thread-based: registered from pasted email (matched by thread ID)
"""

import json
import re
import sys
import time
import base64
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from email.utils import parseaddr
import urllib.request
import urllib.parse
import urllib.error

# --- Config ---
CREDS_FILE   = Path.home() / ".gmail-mcp" / "credentials.json"
OAUTH_FILE   = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
BASE_DIR     = Path.home() / ".claude" / "eng-buddy"
STATE_FILE   = BASE_DIR / "gmail-poller-state.json"
WATCHES_FILE = BASE_DIR / "email-watches.md"
TASK_INBOX   = BASE_DIR / "task-inbox.md"
TOKEN_URL    = "https://oauth2.googleapis.com/token"
GMAIL_BASE   = "https://gmail.googleapis.com/gmail/v1/users/me"


# --- OAuth helpers ---

def load_credentials():
    creds = json.loads(CREDS_FILE.read_text())
    oauth = json.loads(OAUTH_FILE.read_text())
    client = oauth["installed"]
    return creds, client


def refresh_access_token(creds, client):
    data = urllib.parse.urlencode({
        "client_id":     client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        new_token = json.loads(resp.read())
    creds["access_token"] = new_token["access_token"]
    creds["expiry_date"]  = int(time.time() * 1000) + new_token.get("expires_in", 3600) * 1000
    CREDS_FILE.write_text(json.dumps(creds, indent=2))
    return creds


def get_token():
    creds, client = load_credentials()
    expiry = creds.get("expiry_date", 0)
    if int(time.time() * 1000) >= expiry - 60000:
        creds = refresh_access_token(creds, client)
    return creds["access_token"]


# --- Gmail API ---

def gmail_get(path, params=None, token=None):
    url = f"{GMAIL_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Token expired mid-run, refresh and retry once
            token = get_token()
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        raise


def get_message(msg_id, token):
    return gmail_get(f"messages/{msg_id}", {"format": "metadata",
        "metadataHeaders": "From,To,Subject,Date"}, token=token)


def get_message_body(msg_id, token):
    """Get snippet only — enough for task context without loading full body."""
    msg = gmail_get(f"messages/{msg_id}", {"format": "full"}, token=token)
    return msg.get("snippet", "")


def extract_header(msg, name):
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


# --- Watch file parser ---

def parse_watches():
    """
    Parse email-watches.md into list of watch dicts.

    Watch block format:
    ## Watch: <title>
    - From: <pattern>          # optional, supports * wildcard and comma-separated
    - Subject contains: <kw>   # optional, comma-separated keywords (OR logic)
    - Thread ID: <id>           # optional, exact Gmail thread ID (highest priority match)
    - Task: #<N>               # optional, task number to update
    - Action: update|create    # update = append to task notes, create = new task-inbox entry
    - Added: <date>
    """
    if not WATCHES_FILE.exists():
        return []

    watches = []
    current = {}
    for line in WATCHES_FILE.read_text().splitlines():
        if line.startswith("## Watch:"):
            if current.get("title"):
                watches.append(current)
            current = {"title": line[9:].strip(), "action": "update"}
        elif line.startswith("- From:"):
            current["from"] = line[7:].strip()
        elif line.startswith("- Subject contains:"):
            current["subject_kws"] = [k.strip() for k in line[19:].strip().split(",")]
        elif line.startswith("- Thread ID:"):
            current["thread_id"] = line[12:].strip()
        elif line.startswith("- Task:"):
            current["task"] = line[7:].strip()
        elif line.startswith("- Action:"):
            current["action"] = line[9:].strip()
        elif line.startswith("- Added:"):
            current["added"] = line[8:].strip()
        elif line.startswith("- Snoozed until:"):
            current["snoozed_until"] = line[16:].strip()

    if current.get("title"):
        watches.append(current)
    return watches


def match_watch(watch, msg_from, msg_subject, msg_thread_id):
    """Return True if the message matches this watch."""

    # Snoozed watches are skipped
    if "snoozed_until" in watch:
        try:
            snooze_date = datetime.strptime(watch["snoozed_until"], "%Y-%m-%d").date()
            if date.today() <= snooze_date:
                return False
        except ValueError:
            pass

    # Thread ID match — most precise
    if watch.get("thread_id"):
        return msg_thread_id == watch["thread_id"]

    matched_from = True
    matched_subject = True

    # From pattern match (supports * wildcard and comma-separated options)
    if watch.get("from"):
        patterns = [p.strip() for p in watch["from"].split(",")]
        matched_from = any(
            re.search(p.replace("*", ".*"), msg_from, re.IGNORECASE)
            for p in patterns
        )

    # Subject keyword match (OR logic)
    if watch.get("subject_kws"):
        matched_subject = any(
            kw.lower() in msg_subject.lower()
            for kw in watch["subject_kws"]
        )

    # Need at least one matcher defined
    if not watch.get("from") and not watch.get("subject_kws"):
        return False

    return matched_from and matched_subject


# --- State ---

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# --- Output helpers ---

def get_daily_log_path():
    return BASE_DIR / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"


def append_to_daily_log(content):
    log_path = get_daily_log_path()
    if not log_path.exists():
        return
    existing = log_path.read_text()
    if "## 📧 Email Updates" not in existing:
        with open(log_path, "a") as f:
            f.write("\n## 📧 Email Updates\n")
    with open(log_path, "a") as f:
        f.write(content)


def append_to_task_inbox(sender, subject, snippet, watch, msg_id, dt_str):
    existing = TASK_INBOX.read_text() if TASK_INBOX.exists() else ""
    if msg_id in existing:
        return  # already logged

    task_ref = watch.get("task", "")
    action   = watch.get("action", "update")
    watch_title = watch.get("title", "Email")

    with open(TASK_INBOX, "a") as f:
        if not existing:
            f.write("# Slack & Email Task Inbox\n\n")
            f.write("*Potential tasks detected. Review with eng-buddy.*\n\n")
        f.write(f"## [ ] 📧 {sender} — {dt_str}\n")
        f.write(f"**Watch**: {watch_title}\n")
        if task_ref:
            f.write(f"**Linked task**: {task_ref} ({action})\n")
        f.write(f"**Subject**: {subject}\n")
        f.write(f"**Preview**: {snippet[:300]}\n")
        f.write(f"<!-- msg:{msg_id} -->\n\n")


# --- Notifications ---

def notify(title, message):
    """
    Fire two notifications:
    1. Banner to notification center (with sound)
    2. Persistent alert dialog (stays until dismissed)
    """
    # Banner — goes to notification center, plays sound
    banner_script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", banner_script])

    # Persistent alert — detached so poller isn't blocked, stays on screen until OK clicked
    alert_script = f'display alert "{title}" message "{message}" buttons {{"OK"}} default button "OK"'
    subprocess.Popen(["osascript", "-e", alert_script])


# --- Main ---

def main():
    state   = load_state()
    token   = get_token()
    watches = parse_watches()

    if not watches:
        print(f"[{datetime.now().strftime('%H:%M')}] No watches configured. Add entries to email-watches.md")
        return

    # Use last-check timestamp or default to 1 hour ago
    last_check_ts = state.get("last_check_ts")
    if last_check_ts:
        after_epoch = int(last_check_ts)
    else:
        after_epoch = int((datetime.now() - timedelta(hours=1)).timestamp())

    now_ts = int(datetime.now().timestamp())
    already_seen = set(state.get("seen_msg_ids", []))
    new_seen     = set()
    matches_found = []

    # Build Gmail search query — combines all watches
    query_parts = []
    for w in watches:
        if w.get("thread_id"):
            query_parts.append(f"thread:{w['thread_id']}")
        elif w.get("from"):
            froms = [f.strip() for f in w["from"].split(",")]
            for f in froms:
                clean = f.replace("*", "").strip()
                if clean:
                    query_parts.append(f"from:{clean}")
        elif w.get("subject_kws"):
            for kw in w["subject_kws"]:
                query_parts.append(f"subject:{kw}")

    if not query_parts:
        print(f"[{datetime.now().strftime('%H:%M')}] Watches have no queryable fields")
        return

    # De-dupe and run search
    query = f"({' OR '.join(set(query_parts))}) after:{after_epoch} in:inbox"

    result = gmail_get("messages", {"q": query, "maxResults": 30}, token=token)
    messages = result.get("messages", [])

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if msg_id in already_seen:
            continue

        new_seen.add(msg_id)

        msg = get_message(msg_id, token)
        msg_from    = extract_header(msg, "From")
        msg_subject = extract_header(msg, "Subject")
        msg_date    = extract_header(msg, "Date")
        msg_thread  = msg.get("threadId", "")
        snippet     = msg.get("snippet", "")
        _, sender_email = parseaddr(msg_from)

        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Match against all watches
        for watch in watches:
            if match_watch(watch, msg_from, msg_subject, msg_thread):
                matches_found.append({
                    "watch":   watch["title"],
                    "task":    watch.get("task", ""),
                    "action":  watch.get("action", "update"),
                    "from":    msg_from,
                    "subject": msg_subject,
                    "snippet": snippet,
                    "msg_id":  msg_id,
                    "dt":      dt_str,
                })
                append_to_task_inbox(msg_from, msg_subject, snippet, watch, msg_id, dt_str)
                _, sender_name = parseaddr(msg_from)
                notify(
                    title=f"eng-buddy: {watch['title']}",
                    message=f"From: {sender_name or msg_from}\n{msg_subject[:80]}",
                )
                break  # one watch match per message is enough

        time.sleep(0.2)

    # Write to daily log
    if matches_found:
        check_time = datetime.now().strftime("%H:%M")
        lines = [f"\n### Email check {check_time} — {len(matches_found)} matched\n"]
        for m in matches_found:
            task_ref = f" → {m['task']}" if m["task"] else ""
            lines.append(f"- 📧 **{m['watch']}**{task_ref} [{m['dt']}] **{m['from']}**: {m['subject']}\n")
            lines.append(f"  _{m['snippet'][:200]}_\n")
        append_to_daily_log("".join(lines))
        print(f"[{datetime.now().strftime('%H:%M')}] {len(matches_found)} email match(es) logged")
    else:
        print(f"[{datetime.now().strftime('%H:%M')}] No watched emails")

    # Update state
    state["last_check_ts"] = now_ts
    state["seen_msg_ids"]  = list((already_seen | new_seen))[-500:]  # cap at 500
    save_state(state)


if __name__ == "__main__":
    main()
