#!/usr/bin/env python3
"""
eng-buddy Gmail Poller (smart rewrite)
Scans ALL inbox emails from last 3 days via Gmail OAuth.
Claude CLI classifies each email: action-needed, alert, or noise.
Writes classified cards to inbox.db with draft responses and context notes.
Tracks ignored senders for adaptive filter suggestions.
Injects brain context and parses learning from Claude responses.
"""

import json
import os
import re
import sqlite3
import sys
import time
import subprocess
from datetime import datetime, date, timezone
from pathlib import Path
from email.utils import parseaddr
import urllib.request
import urllib.parse
import urllib.error

# --- brain import ---
sys.path.insert(0, str(Path(__file__).parent))
import brain

# --- Config ---
CREDS_FILE = Path.home() / ".gmail-mcp" / "credentials.json"
OAUTH_FILE = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
BASE_DIR   = Path.home() / ".claude" / "eng-buddy"
STATE_FILE = BASE_DIR / "gmail-poller-state.json"
DB_PATH    = BASE_DIR / "inbox.db"
SETTINGS_FILE = BASE_DIR / "dashboard-settings.json"
TOKEN_URL  = "https://oauth2.googleapis.com/token"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
DASHBOARD_INVALIDATE_URL = "http://127.0.0.1:7777/api/cache-invalidate"
USER_EMAIL = os.environ.get("ENG_BUDDY_USER_EMAIL", "kioja.kudumu@klaviyo.com")

# How many noise hits before we surface a filter suggestion
FILTER_SUGGEST_THRESHOLD = 10


# ---------------------------------------------------------------------------
# OAuth helpers (unchanged)
# ---------------------------------------------------------------------------

def load_credentials():
    creds  = json.loads(CREDS_FILE.read_text())
    oauth  = json.loads(OAUTH_FILE.read_text())
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


# ---------------------------------------------------------------------------
# Gmail API helpers (unchanged)
# ---------------------------------------------------------------------------

def gmail_get(path, params=None, token=None):
    url = f"{GMAIL_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            token = get_token()
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        raise


def get_message(msg_id, token):
    return gmail_get(
        f"messages/{msg_id}",
        {
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Subject", "Date"],
        },
        token=token,
    )


def extract_header(msg, name):
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def extract_received_at(msg):
    """Prefer Gmail's internal delivery timestamp when available."""
    internal_date = msg.get("internalDate")
    try:
        if internal_date:
            return datetime.fromtimestamp(
                int(internal_date) / 1000,
                tz=timezone.utc,
            ).isoformat()
    except (TypeError, ValueError):
        pass
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def invalidate_dashboard_cache(source="gmail"):
    payload = json.dumps({"source": source}).encode("utf-8")
    request = urllib.request.Request(
        DASHBOARD_INVALIDATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            return
    except (urllib.error.URLError, TimeoutError, OSError):
        return


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def get_daily_log_path():
    return BASE_DIR / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"


def append_to_daily_log(content):
    log_path = get_daily_log_path()
    if not log_path.exists():
        return
    existing = log_path.read_text()
    if "## Email Updates" not in existing:
        with open(log_path, "a") as f:
            f.write("\n## Email Updates\n")
    with open(log_path, "a") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def macos_notifications_enabled():
    if not SETTINGS_FILE.exists():
        return False
    try:
        settings = json.loads(SETTINGS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(settings.get("macos_notifications", False))


def notify(title, message):
    """Fire a banner notification and a persistent alert dialog."""
    if not macos_notifications_enabled():
        return
    safe_title = str(title).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    safe_message = str(message).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    banner_script = f'display notification "{safe_message}" with title "{safe_title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", banner_script])

    alert_script = f'display alert "{safe_title}" message "{safe_message}" buttons {{"OK"}} default button "OK"'
    subprocess.Popen(["osascript", "-e", alert_script])


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def db_connect():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH)


def build_card_summary(item):
    sender = (item.get("from") or item.get("sender_email") or "Unknown sender").strip()
    subject = (item.get("subject") or "(no subject)").strip()
    return f"{sender}: {subject}"


def ensure_unique_summary(conn, summary, item):
    exists = conn.execute(
        "SELECT 1 FROM cards WHERE source = 'gmail' AND summary = ?",
        (summary,),
    ).fetchone()
    if not exists:
        return summary

    received_at = item.get("received_at") or datetime.now(timezone.utc).isoformat()
    try:
        received_label = datetime.fromisoformat(
            received_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        received_label = "duplicate"

    msg_tail = (item.get("id") or "")[-6:]
    suffix = f" [{received_label}"
    if msg_tail:
        suffix += f" {msg_tail}"
    suffix += "]"

    candidate = f"{summary}{suffix}"
    counter = 2
    while conn.execute(
        "SELECT 1 FROM cards WHERE source = 'gmail' AND summary = ?",
        (candidate,),
    ).fetchone():
        candidate = f"{summary}{suffix} #{counter}"
        counter += 1
    return candidate


def write_card_to_db(conn, item, classification_result):
    """Insert one classified email card into inbox.db."""
    if conn is None:
        return False

    section        = classification_result.get("section", "noise")
    classification = classification_result.get("classification", "unknown")
    draft_response = classification_result.get("draft_response")
    context_notes  = classification_result.get("context_notes")
    summary = ensure_unique_summary(conn, build_card_summary(item), item)

    proposed_actions = json.dumps([{
        "type":      "reply_to_email",
        "draft":     draft_response or f"Review and respond to email from {item['from']}: {item['subject']}",
        "source":    "gmail",
        "message_id": item.get("id", ""),
        "thread_id": item.get("thread_id", ""),
        "to_email":  item.get("sender_email", ""),
        "subject":   item.get("subject", ""),
    }])

    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO cards
           (source, timestamp, summary, classification, section, draft_response,
            context_notes, status, proposed_actions, execution_status)
           VALUES ('gmail', ?, ?, ?, ?, ?, ?, 'pending', ?, 'not_run')""",
        (
            item.get("received_at") or datetime.now(timezone.utc).isoformat(),
            summary,
            classification,
            section,
            draft_response,
            context_notes,
            proposed_actions,
        ),
    )
    return conn.total_changes > before


def update_filter_suggestions(conn, noise_items):
    """
    For each noise-classified item, increment ignore_count for the sender pattern.
    When ignore_count reaches FILTER_SUGGEST_THRESHOLD, mark as ready to suggest.
    """
    if conn is None or not noise_items:
        return

    for item in noise_items:
        # Derive a pattern: strip subaddressing and use the domain+local part
        sender_email = item.get("sender_email", "")
        if not sender_email:
            continue

        # Build a coarse pattern: local@domain (no subaddress)
        local, _, domain = sender_email.partition("@")
        local_clean = re.sub(r"\+.*", "", local)  # strip +tag
        pattern = f"{local_clean}@{domain}".lower() if domain else sender_email.lower()

        row = conn.execute(
            "SELECT id, ignore_count FROM filter_suggestions WHERE source='gmail' AND pattern=?",
            (pattern,),
        ).fetchone()

        if row:
            row_id, count = row
            new_count = count + 1
            if new_count >= FILTER_SUGGEST_THRESHOLD:
                conn.execute(
                    """UPDATE filter_suggestions
                       SET ignore_count=?, suggested_at=?, status='suggest'
                       WHERE id=?""",
                    (new_count, datetime.now(timezone.utc).isoformat(), row_id),
                )
            else:
                conn.execute(
                    "UPDATE filter_suggestions SET ignore_count=? WHERE id=?",
                    (new_count, row_id),
                )
        else:
            conn.execute(
                "INSERT INTO filter_suggestions (source, pattern, ignore_count, status) VALUES ('gmail', ?, 1, 'tracking')",
                (pattern,),
            )


# ---------------------------------------------------------------------------
# Response sweep — detect user replies in threads
# ---------------------------------------------------------------------------

def sweep_responded_cards(token):
    """
    Check unresolved Gmail cards for user replies in the thread.
    If the user has replied, mark the card as responded.
    """
    conn = db_connect()
    if conn is None:
        return 0, []

    try:
        rows = conn.execute(
            """SELECT id, summary, proposed_actions, timestamp
               FROM cards
               WHERE source = 'gmail'
                 AND responded = 0
                 AND section IN ('action-needed', 'needs-action', 'needs-response')
                 AND status = 'pending'""",
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return 0, []

    if not rows:
        conn.close()
        return 0, []

    resolved_count = 0
    resolved_ids = []

    for row in rows:
        card_id = row[0]
        proposed_actions_raw = row[2] or "[]"
        card_timestamp = row[3] or ""

        try:
            actions = json.loads(proposed_actions_raw)
        except (json.JSONDecodeError, TypeError):
            actions = []

        thread_id = ""
        for action in actions:
            thread_id = action.get("thread_id", "")
            if thread_id:
                break

        if not thread_id:
            continue

        # Fetch thread messages from Gmail API
        try:
            thread_data = gmail_get(
                f"threads/{thread_id}",
                {"format": "metadata", "metadataHeaders": ["From"]},
                token=token,
            )
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M')}] Thread fetch failed for {thread_id}: {exc}")
            continue

        thread_messages = thread_data.get("messages", [])

        # Check if any message in the thread is from the user (sent after card timestamp)
        user_replied = False
        for msg in thread_messages:
            msg_from = ""
            for h in msg.get("payload", {}).get("headers", []):
                if h["name"].lower() == "from":
                    msg_from = h["value"]
                    break

            _, from_email = parseaddr(msg_from)
            if not from_email:
                continue

            # Check if this is from the user's own email
            if from_email.lower() == USER_EMAIL.lower():
                # Verify it was sent after the card was created
                msg_internal = msg.get("internalDate", "0")
                msg_ts = int(msg_internal) / 1000 if msg_internal else 0

                try:
                    card_dt = datetime.fromisoformat(card_timestamp.replace("Z", "+00:00"))
                    card_ts = card_dt.timestamp()
                except (ValueError, TypeError):
                    card_ts = 0

                if msg_ts > card_ts:
                    user_replied = True
                    break

        if user_replied:
            conn.execute(
                """UPDATE cards
                   SET responded = 1, section = 'no-action', classification = 'responded'
                   WHERE id = ?""",
                (card_id,),
            )
            resolved_count += 1
            resolved_ids.append(card_id)

        time.sleep(0.15)  # rate limiting

    if resolved_count:
        conn.commit()
    conn.close()

    return resolved_count, resolved_ids


# ---------------------------------------------------------------------------
# Claude CLI classification
# ---------------------------------------------------------------------------

def classify_with_claude(batch_items):
    """
    Send batch_items to Claude CLI for classification.
    Returns list of dicts: {id, section, classification, draft_response, context_notes}
    Falls back to empty list on any error.
    """
    if not batch_items:
        return []

    context_prompt = brain.build_context_prompt(batch_items)

    prompt = f"""{context_prompt}

Classify each email below as:
- section: "action-needed", "alert", or "noise"
- classification: more specific label (e.g., "needs-response", "offboarding-fyi", "security-alert", "marketing-spam")
- draft_response: For action-needed emails that need a reply, draft one. null otherwise.
- context_notes: Brief context. For alerts, a one-line summary. null for noise.

Emails:
{json.dumps(batch_items, indent=2)}

Return ONLY a JSON array. No prose."""

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()

        # Parse learning sections from the full response before extracting JSON
        brain.parse_learning(output)

        # Extract the JSON array — Claude should return only JSON, but strip any
        # markdown fences or surrounding text just in case.
        json_match = re.search(r"\[.*\]", output, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        print(f"[{datetime.now().strftime('%H:%M')}] Claude returned no parseable JSON array")
        return []

    except subprocess.TimeoutExpired:
        print(f"[{datetime.now().strftime('%H:%M')}] Claude CLI timed out during classification")
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[{datetime.now().strftime('%H:%M')}] JSON parse error from Claude: {exc}")
        return []
    except Exception as exc:
        print(f"[{datetime.now().strftime('%H:%M')}] Claude CLI error: {exc}")
        return []


def build_classification_map(results, batch_items):
    """
    Map Claude results back to batch items by index or by id field.
    Returns dict keyed by msg_id.
    """
    id_map = {}
    for i, res in enumerate(results):
        # Claude may return an 'id' field or results in order
        msg_id = res.get("id")
        if not msg_id and i < len(batch_items):
            msg_id = batch_items[i].get("id")
        if msg_id:
            id_map[msg_id] = res
    return id_map


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    state        = load_state()
    token        = get_token()
    refresh_now  = "--refresh-now" in sys.argv[1:]
    already_seen = set() if refresh_now else set(state.get("seen_msg_ids", []))
    processed_seen = set()

    # Scan inbox emails from the last 3 days.
    query = "in:inbox newer_than:3d"
    result = gmail_get("messages", {"q": query, "maxResults": 50}, token=token)
    messages = result.get("messages", [])

    if not messages:
        print(f"[{datetime.now().strftime('%H:%M')}] No emails in last 3 days")
        state["last_check_ts"] = int(datetime.now().timestamp())
        save_state(state)
        return

    # Fetch metadata for unseen messages only
    batch_items = []
    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if msg_id in already_seen:
            continue

        try:
            msg = get_message(msg_id, token)
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M')}] Failed to fetch {msg_id}: {exc}")
            continue

        msg_from    = extract_header(msg, "From")
        msg_to      = extract_header(msg, "To")
        msg_subject = extract_header(msg, "Subject")
        msg_thread  = msg.get("threadId", "")
        snippet     = msg.get("snippet", "")
        labels      = msg.get("labelIds", [])
        _, sender_email = parseaddr(msg_from)

        batch_items.append({
            "id":           msg_id,
            "from":         msg_from,
            "sender_email": sender_email,
            "to":           msg_to,
            "subject":      msg_subject,
            "snippet":      snippet[:500],
            "labels":       labels,
            "thread_id":    msg_thread,
            "received_at":  extract_received_at(msg),
        })

        time.sleep(0.15)  # gentle rate limiting

    if not batch_items:
        print(f"[{datetime.now().strftime('%H:%M')}] No new emails (all already seen)")
        state["last_check_ts"] = int(datetime.now().timestamp())
        state["seen_msg_ids"]  = list(already_seen)[-500:]
        save_state(state)
        return

    print(f"[{datetime.now().strftime('%H:%M')}] Classifying {len(batch_items)} new email(s) via Claude...")

    # Classify via Claude CLI
    classification_results = classify_with_claude(batch_items)
    classification_map     = build_classification_map(classification_results, batch_items)

    # Write to DB and collect metrics
    conn = db_connect()
    action_needed = []
    alerts        = []
    noise_items   = []
    db_changed    = False

    if conn:
        for item in batch_items:
            msg_id   = item["id"]
            cl_result = classification_map.get(msg_id, {
                "section":        "noise",
                "classification": "unclassified",
                "draft_response": None,
                "context_notes":  None,
            })

            if write_card_to_db(conn, item, cl_result):
                processed_seen.add(msg_id)
                db_changed = True

            section = cl_result.get("section", "noise")
            if section == "action-needed":
                action_needed.append((item, cl_result))
            elif section == "alert":
                alerts.append((item, cl_result))
            else:
                noise_items.append(item)

        # Update adaptive filter suggestions for noise senders
        update_filter_suggestions(conn, noise_items)
        conn.commit()
        conn.close()
    else:
        print(f"[{datetime.now().strftime('%H:%M')}] inbox.db not found — skipping DB writes")
        # Still categorize for logging/notifications
        for item in batch_items:
            msg_id    = item["id"]
            cl_result = classification_map.get(msg_id, {"section": "noise"})
            section   = cl_result.get("section", "noise")
            if section == "action-needed":
                action_needed.append((item, cl_result))
            elif section == "alert":
                alerts.append((item, cl_result))
            else:
                noise_items.append(item)
            processed_seen.add(msg_id)

    # Notifications for action-needed emails
    for item, cl_result in action_needed:
        _, display_name = parseaddr(item["from"])
        notify(
            title=f"eng-buddy: Action needed",
            message=f"From: {display_name or item['from']}\n{item['subject'][:80]}",
        )

    # Notifications for alerts (single batch notification if multiple)
    if alerts:
        if len(alerts) == 1:
            item, cl_result = alerts[0]
            _, display_name = parseaddr(item["from"])
            notify(
                title="eng-buddy: Alert",
                message=f"From: {display_name or item['from']}\n{item['subject'][:80]}",
            )
        else:
            notify(
                title="eng-buddy: Alerts",
                message=f"{len(alerts)} alert email(s) in your inbox",
            )

    # Write to daily log
    total = len(batch_items)
    check_time = datetime.now().strftime("%H:%M")
    log_lines  = [f"\n### Email check {check_time} — {total} new ({len(action_needed)} action, {len(alerts)} alert, {len(noise_items)} noise)\n"]

    for item, cl_result in action_needed:
        classification = cl_result.get("classification", "needs-response")
        log_lines.append(f"- ACTION [{classification}] **{item['from']}**: {item['subject']}\n")
        if cl_result.get("context_notes"):
            log_lines.append(f"  _{cl_result['context_notes']}_\n")

    for item, cl_result in alerts:
        classification = cl_result.get("classification", "alert")
        log_lines.append(f"- ALERT [{classification}] **{item['from']}**: {item['subject']}\n")
        if cl_result.get("context_notes"):
            log_lines.append(f"  _{cl_result['context_notes']}_\n")

    append_to_daily_log("".join(log_lines))

    # Console summary
    print(f"[{datetime.now().strftime('%H:%M')}] {total} email(s): "
          f"{len(action_needed)} action-needed, {len(alerts)} alert, {len(noise_items)} noise")

    # Update state
    state["last_check_ts"] = int(datetime.now().timestamp())
    state["seen_msg_ids"]  = list((already_seen | processed_seen))[-500:]
    save_state(state)

    if db_changed:
        invalidate_dashboard_cache("gmail")

    # Response sweep: check if user replied to any pending Gmail cards
    token_for_sweep = get_token()
    sweep_count, sweep_ids = sweep_responded_cards(token_for_sweep)
    if sweep_count:
        print(f"[{datetime.now().strftime('%H:%M')}] Response sweep: resolved {sweep_count} card(s)")
        invalidate_dashboard_cache("gmail")
        # Trigger cross-channel resolution for each resolved card
        for cid in sweep_ids:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:7777/api/cards/{cid}/resolve-related",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception as exc:
                print(f"[{datetime.now().strftime('%H:%M')}] Cross-channel resolve failed for card {cid}: {exc}")


if __name__ == "__main__":
    main()
