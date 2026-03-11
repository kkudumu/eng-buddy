import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from contextlib import asynccontextmanager

import ptyprocess
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from migrate import migrate

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"
ENG_BUDDY_DIR = Path.home() / ".claude" / "eng-buddy"
STATIC_DIR = Path(__file__).parent / "static"
TASKS_FILE = ENG_BUDDY_DIR / "tasks" / "active-tasks.md"
AUTOMATION_DRAFTS_FILE = ENG_BUDDY_DIR / "tasks" / "automation-drafts.md"
DAILY_DIR = ENG_BUDDY_DIR / "daily"
KNOWLEDGE_DIR = ENG_BUDDY_DIR / "knowledge"
PATTERNS_DIR = ENG_BUDDY_DIR / "patterns"
STAKEHOLDERS_DIR = ENG_BUDDY_DIR / "stakeholders"
MEMORY_DIR = ENG_BUDDY_DIR / "memory"
RUNTIME_DIR = ENG_BUDDY_DIR / ".runtime"
CLAUDE_SYNC_FILE = RUNTIME_DIR / "claude-sync-events.txt"
LAUNCHER_DIR = RUNTIME_DIR / "launchers"
RESTART_STATUS_FILE = RUNTIME_DIR / "dashboard-restart-status.json"
DEFAULT_TERMINAL_APP = os.environ.get("ENG_BUDDY_TERMINAL", "Terminal")
TERMINAL_APP = DEFAULT_TERMINAL_APP
JIRA_USER = os.environ.get("ENG_BUDDY_JIRA_USER", "kioja.kudumu@klaviyo.com")
JIRA_BOARD_NAME = os.environ.get("ENG_BUDDY_JIRA_BOARD_NAME", "Systems")
JIRA_PROJECT_KEY = os.environ.get("ENG_BUDDY_JIRA_PROJECT_KEY", "ITWORK2")
SUGGESTION_SOURCE = "suggestions"
SUGGESTION_REFRESH_INTERVAL_SECONDS = 1800
SUGGESTION_MAX_ITEMS = 12
SUGGESTION_CATEGORY_ORDER = ("automation", "workflow", "time-saver", "gap")
SUGGESTION_CATEGORY_LABELS = {
    "automation": "Automation",
    "workflow": "Workflow Improvements",
    "time-saver": "Time Savers",
    "gap": "Gaps / Missing Coverage",
}
SUGGESTION_KNOWLEDGE_FILES = (
    KNOWLEDGE_DIR / "runbooks.md",
    PATTERNS_DIR / "documentation-gaps.md",
    PATTERNS_DIR / "failure-patterns.md",
    PATTERNS_DIR / "success-patterns.md",
    PATTERNS_DIR / "recurring-questions.md",
    PATTERNS_DIR / "task-execution.md",
)

# In-memory cache for Jira sprint data
_jira_cache = {"data": None, "fetched_at": 0}
# Source-level stale flags used to emit SSE cache invalidation events.
_stale_sources = set()
_suggestion_refresh_lock = threading.Lock()
_suggestion_worker_started = False
_running_syncs: dict[str, subprocess.Popen] = {}
POLLER_DEFINITIONS = (
    {
        "id": "slack",
        "label": "Slack",
        "launch_label": "com.engbuddy.slackpoller",
        "interval_seconds": 300,
        "state_file": "slack-poller-state.json",
        "log_file": "slack-poller.log",
    },
    {
        "id": "gmail",
        "label": "Gmail",
        "launch_label": "com.engbuddy.gmailpoller",
        "interval_seconds": 600,
        "state_file": "gmail-poller-state.json",
        "log_file": "gmail-poller.log",
    },
    {
        "id": "calendar",
        "label": "Calendar",
        "launch_label": "com.engbuddy.calendarpoller",
        "interval_seconds": 1800,
        "state_file": "calendar-poller-state.json",
        "log_file": "calendar-poller.log",
    },
    {
        "id": "jira",
        "label": "Jira",
        "launch_label": "com.engbuddy.jirapoller",
        "interval_seconds": 300,
        "state_file": "jira-ingestor-state.json",
        "log_file": "jira-poller.log",
    },
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(exist_ok=True)
    migrate()
    _start_suggestion_refresh_worker()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# React dashboard (Wave 1)
REACT_DIR = Path(__file__).parent / "static-react"
if REACT_DIR.exists():
    app.mount("/app-assets", StaticFiles(directory=str(REACT_DIR)), name="react-assets")


def _escape_applescript_text(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def _settings_file() -> Path:
    return ENG_BUDDY_DIR / "dashboard-settings.json"


def _load_restart_status() -> dict:
    default = {"phase": "idle", "message": "", "updated_at": None}
    if not RESTART_STATUS_FILE.exists():
        return default

    try:
        raw = json.loads(RESTART_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

    if not isinstance(raw, dict):
        return default

    return {
        "phase": str(raw.get("phase") or "idle"),
        "message": str(raw.get("message") or ""),
        "updated_at": raw.get("updated_at"),
    }


def _default_settings() -> dict:
    return {
        "terminal": DEFAULT_TERMINAL_APP,
        "macos_notifications": False,
        "theme": "neon-dreams",
        "mode": "dark",
    }


def _load_settings() -> dict:
    settings = _default_settings()
    path = _settings_file()
    if not path.exists():
        return settings

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings

    if isinstance(loaded, dict):
        terminal = loaded.get("terminal")
        if isinstance(terminal, str) and terminal:
            settings["terminal"] = terminal
        settings["macos_notifications"] = bool(loaded.get("macos_notifications", False))
        theme = loaded.get("theme")
        if isinstance(theme, str) and theme in ("midnight-ops", "soft-kitty", "neon-dreams"):
            settings["theme"] = theme
        mode = loaded.get("mode")
        if isinstance(mode, str) and mode in ("dark", "light"):
            settings["mode"] = mode
    return settings


def _save_settings(settings: dict) -> dict:
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _default_settings()
    normalized["terminal"] = settings.get("terminal", normalized["terminal"])
    normalized["macos_notifications"] = bool(
        settings.get("macos_notifications", normalized["macos_notifications"])
    )
    theme = settings.get("theme", normalized["theme"])
    if theme in ("midnight-ops", "soft-kitty", "neon-dreams"):
        normalized["theme"] = theme
    mode = settings.get("mode", normalized["mode"])
    if mode in ("dark", "light"):
        normalized["mode"] = mode
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


TERMINAL_APP = _load_settings()["terminal"]


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


def _run_claude_print(prompt: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_claude_env(),
    )


def _extract_balanced_json(text: str, opening: str):
    """Extract and parse the first balanced JSON object/array from text."""
    if opening not in ("{", "["):
        return None
    closing = "}" if opening == "{" else "]"

    for start, char in enumerate(text):
        if char != opening:
            continue

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            c = text[i]

            if in_string:
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = False
                continue

            if c == '"':
                in_string = True
                continue
            if c == opening:
                depth += 1
                continue
            if c == closing:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def _parse_isoish_datetime(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _calendar_event_looks_like_meeting(event: dict) -> bool:
    start = str(event.get("start") or "").strip()
    if "T" in start:
        return True
    return bool(
        event.get("attendees")
        or event.get("hangout_link")
        or event.get("location")
    )


def _format_briefing_meeting(card: sqlite3.Row, target_date: date):
    try:
        proposed_actions = json.loads(card["proposed_actions"] or "[]")
    except (TypeError, json.JSONDecodeError):
        proposed_actions = []

    event = proposed_actions[0] if proposed_actions else {}
    if not isinstance(event, dict):
        event = {}

    start_value = event.get("start") or card["timestamp"]
    start_dt = _parse_isoish_datetime(start_value)
    if not start_dt:
        return None

    local_dt = start_dt.astimezone() if start_dt.tzinfo else start_dt
    if local_dt.date() != target_date:
        return None
    if not _calendar_event_looks_like_meeting(event):
        return None

    prep = (card["context_notes"] or "").strip()
    meeting = {
        "time": local_dt.strftime("%H:%M") if "T" in str(start_value) else "ALL DAY",
        "title": (event.get("summary") or card["summary"] or "").strip(),
    }
    if prep:
        meeting["prep"] = prep
    return meeting


def _load_briefing_calendar_meetings(conn: sqlite3.Connection, target_date: date):
    rows = conn.execute(
        """SELECT timestamp, summary, context_notes, proposed_actions
           FROM cards
           WHERE source = 'calendar'
           ORDER BY timestamp ASC"""
    ).fetchall()

    meetings = []
    for row in rows:
        meeting = _format_briefing_meeting(row, target_date)
        if meeting:
            meetings.append(meeting)

    meetings.sort(key=lambda meeting: (meeting.get("time") == "ALL DAY", meeting.get("time") or ""))
    return meetings


def _briefing_meeting_signature(meetings):
    signature = []
    for meeting in meetings or []:
        if not isinstance(meeting, dict):
            continue
        signature.append(
            (
                meeting.get("time") or "",
                meeting.get("title") or "",
                meeting.get("prep") or "",
            )
        )
    return signature

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _parse_json_dict(raw_value, default=None):
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return default.copy() if isinstance(default, dict) else (default or {})
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return default.copy() if isinstance(default, dict) else (default or {})


def _suggestion_category_value(raw_value: str = ""):
    normalized = str(raw_value or "").strip().lower().replace("_", "-")
    if normalized in SUGGESTION_CATEGORY_ORDER:
        return normalized
    if "workflow" in normalized:
        return "workflow"
    if "time" in normalized or "save" in normalized:
        return "time-saver"
    if any(token in normalized for token in ("gap", "missing", "doc")):
        return "gap"
    return "automation"


def _card_analysis_metadata(card: dict):
    meta = _parse_json_dict(card.get("analysis_metadata"), {})
    meta["category"] = _suggestion_category_value(meta.get("category", ""))
    evidence = meta.get("evidence")
    meta["evidence"] = evidence if isinstance(evidence, list) else []
    generated_from = meta.get("generated_from")
    meta["generated_from"] = generated_from if isinstance(generated_from, list) else []
    return meta


def _card_actions(card: dict):
    existing_actions = card.get("proposed_actions")
    if isinstance(existing_actions, list):
        return existing_actions
    try:
        actions = json.loads(existing_actions or "[]")
    except (json.JSONDecodeError, TypeError):
        actions = []
    return actions if isinstance(actions, list) else []


def _gmail_card_details(card: dict):
    actions = _card_actions(card)
    primary = next((action for action in actions if isinstance(action, dict)), {})
    summary = str(card.get("summary", "")).strip()
    sender = str(primary.get("to_email") or "").strip()
    subject = str(primary.get("subject") or "").strip()

    if ":" in summary:
        summary_sender, summary_subject = summary.split(":", 1)
        sender = sender or summary_sender.strip()
        subject = subject or summary_subject.strip()
    else:
        sender = sender or summary

    return {
        "sender": sender,
        "subject": subject,
        "thread_id": str(primary.get("thread_id") or "").strip(),
        "message_id": str(primary.get("message_id") or "").strip(),
        "to_email": str(primary.get("to_email") or "").strip(),
    }


def _gmail_duplicate_key(card: dict):
    details = _gmail_card_details(card)
    thread_id = details["thread_id"].strip().lower()
    if thread_id:
        return f"thread:{thread_id}"

    message_id = details["message_id"].strip().lower()
    if message_id:
        return f"message:{message_id}"

    sender = (details["to_email"] or details["sender"]).strip().lower()
    subject = details["subject"].strip().lower()
    if sender and subject:
        return f"sender-subject:{sender}|{subject}"
    return f"card:{card.get('id')}"


def _gmail_card_preference_key(card: dict):
    timestamp = _parse_card_timestamp(card.get("timestamp"))
    timestamp_score = timestamp.timestamp() if timestamp else 0
    has_draft = 1 if str(card.get("draft_response") or "").strip() else 0
    return (
        has_draft,
        timestamp_score,
        int(card.get("id") or 0),
    )


def _collapse_gmail_duplicates(cards: list[dict]):
    grouped = {}
    for card in cards:
        grouped.setdefault(_gmail_duplicate_key(card), []).append(card)

    collapsed = []
    for group in grouped.values():
        representative = max(group, key=_gmail_card_preference_key)
        if len(group) == 1:
            collapsed.append(representative)
            continue

        merged = dict(representative)
        meta = dict(representative.get("analysis_metadata") or {})
        meta["duplicate_count"] = len(group)
        meta["duplicate_card_ids"] = [int(item.get("id") or 0) for item in group]
        merged["analysis_metadata"] = meta
        collapsed.append(merged)

    return sorted(collapsed, key=_gmail_card_preference_key, reverse=True)


def _find_related_gmail_card_ids(conn, card: dict):
    target_key = _gmail_duplicate_key(card)
    if target_key.startswith("card:"):
        return [int(card["id"])]

    rows = conn.execute(
        "SELECT id, summary, proposed_actions FROM cards WHERE source = 'gmail'",
    ).fetchall()
    related_ids = []
    for row in rows:
        candidate = dict(row)
        if _gmail_duplicate_key(candidate) == target_key:
            related_ids.append(int(candidate["id"]))

    return sorted(set(related_ids or [int(card["id"])]))


def _normalize_gmail_label(value: str):
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    cleaned = cleaned.strip("-_/ ")
    return cleaned[:40]


def _normalize_gmail_analysis(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    category = str(payload.get("detected_category", "")).strip().lower().replace("_", "-")
    if not category:
        category = "needs-response"

    labels = payload.get("suggested_labels") if isinstance(payload.get("suggested_labels"), list) else []
    normalized_labels = []
    seen = set()
    for label in labels:
        cleaned = _normalize_gmail_label(label)
        if not cleaned:
            continue
        dedupe_key = cleaned.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_labels.append(cleaned)
        if len(normalized_labels) >= 5:
            break
    if not normalized_labels and category:
        normalized_labels = [category]

    draft = str(payload.get("suggested_draft", "")).strip()
    reasoning = str(payload.get("reasoning", "")).strip()
    return {
        "detected_category": category,
        "suggested_labels": normalized_labels,
        "suggested_draft": draft,
        "reasoning": reasoning,
    }


def _persist_card_analysis(card_id: int, metadata: dict, draft_response: str | None = None):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT analysis_metadata, draft_response FROM cards WHERE id = ?",
            [card_id],
        ).fetchone()
        if not row:
            raise HTTPException(404, "card not found")

        merged = _parse_json_dict(row["analysis_metadata"], {})
        merged.update(metadata)
        if draft_response is None:
            conn.execute(
                "UPDATE cards SET analysis_metadata = ? WHERE id = ?",
                [json.dumps(merged), card_id],
            )
        else:
            conn.execute(
                "UPDATE cards SET analysis_metadata = ?, draft_response = ? WHERE id = ?",
                [json.dumps(merged), draft_response, card_id],
            )
        conn.commit()
        return merged, (draft_response if draft_response is not None else row["draft_response"])
    finally:
        conn.close()


def _build_gmail_analysis_prompt(card: dict, include_labels: bool = True, include_draft: bool = True):
    details = _gmail_card_details(card)
    existing_meta = _card_analysis_metadata(card)
    existing_labels = existing_meta.get("gmail_suggested_labels", [])
    current_draft = str(card.get("draft_response", "")).strip()
    tasks = []
    if include_labels:
        tasks.append("Suggest a compact detected category and 1-4 Gmail label names.")
    if include_draft:
        tasks.append("Suggest a short reply draft only if a reply would be useful.")
    task_text = " ".join(tasks) or "Review the email."
    return (
        "You are triaging a Gmail inbox card for eng-buddy.\n"
        f"{task_text}\n\n"
        f"Summary: {card.get('summary', '')}\n"
        f"Context notes: {card.get('context_notes', '')}\n"
        f"Current classification: {card.get('classification', '')}\n"
        f"Sender: {details['sender']}\n"
        f"Subject: {details['subject']}\n"
        f"Existing draft: {current_draft or '(none)'}\n"
        f"Existing suggested labels: {json.dumps(existing_labels)}\n\n"
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "detected_category": "needs-response|fyi|ops|finance|sales|recruiting|bulk|personal",\n'
        '  "suggested_labels": ["label-one", "label-two"],\n'
        '  "suggested_draft": "optional reply draft",\n'
        '  "reasoning": "one short sentence"\n'
        "}\n"
        "Keep labels concise and human-readable. Use an empty string for suggested_draft if no reply is needed."
    )


def _compute_suggestion_fingerprint(category: str, title: str):
    payload = f"{_suggestion_category_value(category)}::{str(title or '').strip().lower()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _read_optional_text(path: Path, max_chars: int = 2000):
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n..."
    return text


def _load_patterns_memory():
    path = MEMORY_DIR / "patterns.json"
    if not path.exists():
        return {"patterns": [], "automation_opportunities": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("patterns", [])
            payload.setdefault("automation_opportunities", [])
            return payload
    except json.JSONDecodeError:
        pass
    return {"patterns": [], "automation_opportunities": []}


def _build_suggestion_prompt(context_payload: dict):
    return (
        "You are eng-buddy analyzing current work for high-value improvements.\n"
        "Review the provided tasks, inbox cards, learning signals, automation opportunities, and curated knowledge excerpts.\n"
        "Return ONLY JSON with this shape:\n"
        '{'
        '"suggestions": ['
        '{"title":"","category":"automation|workflow|time-saver|gap","priority":"high|medium|low",'
        '"why_now":"","evidence":[""],"generated_from":[""],'
        '"task_draft":{"title":"","priority":"","description":""},'
        '"automation_draft":{"name":"","problem":"","proposal":"","signals":[""],"guardrails":[""]},'
        '"open_session_prompt":"","proposed_actions":[{"type":"","draft":""}]}'
        "]}\n"
        f"Return at most {SUGGESTION_MAX_ITEMS} suggestions total.\n"
        "Use concise titles. Avoid duplicates. Only include suggestions that are actionable now.\n\n"
        f"Context:\n{json.dumps(context_payload, indent=2)}"
    )


def _collect_suggestion_context():
    tasks = _parse_active_tasks()
    patterns = _load_patterns_memory()
    knowledge_docs = []
    for path in SUGGESTION_KNOWLEDGE_FILES:
        text = _read_optional_text(path)
        if text:
            knowledge_docs.append({"path": str(path.relative_to(ENG_BUDDY_DIR)), "content": text})

    fourteen_days_ago = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(sep=" ")
    conn = get_db()
    try:
        card_rows = conn.execute(
            """SELECT source, summary, context_notes, classification, section, COUNT(*) AS count
               FROM cards
               WHERE source != ?
                 AND status = 'pending'
               GROUP BY source, summary, context_notes, classification, section
               ORDER BY source ASC, count DESC, summary ASC
               LIMIT 40""",
            [SUGGESTION_SOURCE],
        ).fetchall()
        learning_rows = conn.execute(
            """SELECT category, title, note, status, created_at
               FROM learning_events
               WHERE datetime(created_at) >= datetime(?)
               ORDER BY datetime(created_at) DESC, id DESC
               LIMIT 30""",
            [fourteen_days_ago],
        ).fetchall()
    except sqlite3.OperationalError:
        card_rows = []
        learning_rows = []
    finally:
        conn.close()

    return {
        "tasks": [
            {
                "number": task.get("number"),
                "title": task.get("title"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "description": task.get("description", "")[:400],
            }
            for task in tasks[:20]
        ],
        "pending_cards": [dict(row) for row in card_rows],
        "learning_events": [dict(row) for row in learning_rows],
        "automation_opportunities": patterns.get("automation_opportunities", [])[:20],
        "patterns": patterns.get("patterns", [])[:20],
        "knowledge": knowledge_docs,
    }


def _normalize_suggestion_candidate(item: dict):
    if not isinstance(item, dict):
        return None
    title = str(item.get("title", "")).strip()
    if not title:
        return None
    category = _suggestion_category_value(item.get("category", ""))
    why_now = str(item.get("why_now", "")).strip()
    priority = str(item.get("priority", "medium")).strip().lower() or "medium"
    evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    evidence = [str(entry).strip() for entry in evidence if str(entry).strip()][:6]
    generated_from = item.get("generated_from") if isinstance(item.get("generated_from"), list) else []
    generated_from = [str(entry).strip() for entry in generated_from if str(entry).strip()][:10]
    proposed_actions = item.get("proposed_actions") if isinstance(item.get("proposed_actions"), list) else []
    normalized_actions = []
    for action in proposed_actions[:6]:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("type", "next-step")).strip() or "next-step"
        draft = str(action.get("draft", "")).strip()
        normalized_actions.append({"type": action_type, "draft": draft})

    task_draft = item.get("task_draft") if isinstance(item.get("task_draft"), dict) else {}
    automation_draft = item.get("automation_draft") if isinstance(item.get("automation_draft"), dict) else {}
    fingerprint = _compute_suggestion_fingerprint(category, title)
    last_analyzed_at = datetime.now(timezone.utc).isoformat()
    return {
        "summary": title,
        "classification": priority,
        "context_notes": why_now,
        "section": category,
        "proposed_actions": normalized_actions,
        "analysis_metadata": {
            "category": category,
            "priority": priority,
            "evidence": evidence,
            "fingerprint": fingerprint,
            "generated_from": generated_from,
            "task_draft": task_draft,
            "automation_draft": automation_draft,
            "open_session_prompt": str(item.get("open_session_prompt", "")).strip(),
            "last_analyzed_at": last_analyzed_at,
        },
    }


def _generate_suggestion_candidates():
    context_payload = _collect_suggestion_context()
    prompt = _build_suggestion_prompt(context_payload)
    result = _run_claude_print(prompt, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:300] or "suggestion generation failed")

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    if not isinstance(parsed, dict):
        raise RuntimeError("suggestion generation returned invalid JSON")

    suggestions = parsed.get("suggestions")
    if not isinstance(suggestions, list):
        raise RuntimeError("suggestion generation returned invalid suggestions payload")

    normalized = []
    seen = set()
    for item in suggestions:
        candidate = _normalize_suggestion_candidate(item)
        if not candidate:
            continue
        fingerprint = candidate["analysis_metadata"]["fingerprint"]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(candidate)
        if len(normalized) >= SUGGESTION_MAX_ITEMS:
            break
    return normalized


def _refresh_suggestions_sync():
    if not _suggestion_refresh_lock.acquire(blocking=False):
        return {"status": "busy"}

    try:
        try:
            generated = _generate_suggestion_candidates()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}
        generated_by_fingerprint = {
            item["analysis_metadata"]["fingerprint"]: item for item in generated
        }
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM cards WHERE source = ? ORDER BY id ASC",
                [SUGGESTION_SOURCE],
            ).fetchall()
            existing = [dict(row) for row in rows]
            existing_by_fingerprint = {}
            for row in existing:
                meta = _card_analysis_metadata(row)
                fingerprint = meta.get("fingerprint")
                if fingerprint:
                    existing_by_fingerprint[fingerprint] = row

            inserted = 0
            updated = 0
            skipped = 0

            for fingerprint, item in generated_by_fingerprint.items():
                existing_row = existing_by_fingerprint.get(fingerprint)
                if existing_row:
                    if existing_row.get("status") in {"held", "completed"}:
                        skipped += 1
                        continue
                    conn.execute(
                        """UPDATE cards
                           SET timestamp = datetime('now'),
                               summary = ?,
                               classification = ?,
                               context_notes = ?,
                               section = ?,
                               proposed_actions = ?,
                               analysis_metadata = ?
                           WHERE id = ?""",
                        [
                            item["summary"],
                            item["classification"],
                            item["context_notes"],
                            item["section"],
                            json.dumps(item["proposed_actions"]),
                            json.dumps(item["analysis_metadata"]),
                            existing_row["id"],
                        ],
                    )
                    updated += 1
                    continue

                conn.execute(
                    """INSERT INTO cards (
                           source, timestamp, summary, classification, status,
                           proposed_actions, execution_status, section, context_notes, analysis_metadata
                       )
                       VALUES (?, datetime('now'), ?, ?, 'pending', ?, 'not_run', ?, ?, ?)""",
                    [
                        SUGGESTION_SOURCE,
                        item["summary"],
                        item["classification"],
                        json.dumps(item["proposed_actions"]),
                        item["section"],
                        item["context_notes"],
                        json.dumps(item["analysis_metadata"]),
                    ],
                )
                inserted += 1

            active_fingerprints = set(generated_by_fingerprint.keys())
            for row in existing:
                meta = _card_analysis_metadata(row)
                fingerprint = meta.get("fingerprint")
                if row.get("status") != "pending" or not fingerprint or fingerprint in active_fingerprints:
                    continue
                decision_count = conn.execute(
                    """SELECT COUNT(*) FROM decision_events
                       WHERE entity_type = 'card' AND entity_id = ?""",
                    [str(row["id"])],
                ).fetchone()[0]
                if decision_count:
                    continue
                conn.execute(
                    "UPDATE cards SET status = 'completed', execution_result = ? WHERE id = ?",
                    ["stale suggestion replaced by newer analysis", row["id"]],
                )

            conn.commit()
        finally:
            conn.close()

        _stale_sources.add(SUGGESTION_SOURCE)
        return {"status": "ok", "inserted": inserted, "updated": updated, "generated": len(generated), "skipped": skipped}
    finally:
        _suggestion_refresh_lock.release()


def _suggestion_refresh_loop():
    while True:
        try:
            _refresh_suggestions_sync()
        except Exception:
            pass
        time.sleep(SUGGESTION_REFRESH_INTERVAL_SECONDS)


def _start_suggestion_refresh_worker():
    global _suggestion_worker_started
    if _suggestion_worker_started or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _suggestion_worker_started = True
    threading.Thread(target=_suggestion_refresh_loop, daemon=True).start()


def _eng_buddy_path(*parts: str) -> Path:
    return ENG_BUDDY_DIR.joinpath(*parts)


def _utc_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _read_json_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_poller_state_timestamp(poller_id: str, state: dict | None) -> datetime | None:
    if not isinstance(state, dict):
        return None

    try:
        if poller_id == "slack":
            raw = state.get("last_check")
            if raw:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)

        if poller_id == "gmail":
            raw = int(state.get("last_check_ts") or 0)
            if raw > 0:
                return datetime.fromtimestamp(raw, tz=timezone.utc)

        if poller_id == "calendar":
            raw = (state.get("last_fetch") or "").strip()
            if raw:
                parsed = datetime.strptime(raw, "%Y-%m-%d-%H-%M")
                return parsed.replace(tzinfo=_local_timezone()).astimezone(timezone.utc)

        if poller_id == "jira":
            raw = (state.get("last_checked") or "").strip()
            if raw:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_local_timezone())
                return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

    return None


def _file_mtime(path: Path) -> datetime | None:
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return None


def _resolve_poller_last_run(poller: dict) -> datetime | None:
    state_path = _eng_buddy_path(poller["state_file"])
    log_path = _eng_buddy_path(poller["log_file"])
    state = _read_json_file(state_path)

    candidates = [
        _parse_poller_state_timestamp(poller["id"], state),
        _file_mtime(state_path),
        _file_mtime(log_path),
    ]
    valid = [candidate for candidate in candidates if candidate]
    return max(valid) if valid else None


def _build_poller_status(poller: dict, now: datetime) -> dict:
    last_run_at = _resolve_poller_last_run(poller)
    interval_seconds = int(poller["interval_seconds"])
    next_run_at = None
    seconds_until_next = None
    health = "unknown"

    if last_run_at:
        next_run_at = last_run_at + timedelta(seconds=interval_seconds)
        if next_run_at <= now:
            missed_intervals = int((now - next_run_at).total_seconds() // interval_seconds) + 1
            next_run_at += timedelta(seconds=missed_intervals * interval_seconds)
        seconds_until_next = max(0, int((next_run_at - now).total_seconds()))
        health = "running" if (now - last_run_at).total_seconds() <= interval_seconds * 2 else "stale"

    return {
        "id": poller["id"],
        "label": poller["label"],
        "launch_label": poller["launch_label"],
        "interval_seconds": interval_seconds,
        "last_run_at": _utc_iso(last_run_at),
        "next_run_at": _utc_iso(next_run_at),
        "seconds_until_next": seconds_until_next,
        "health": health,
    }


def _normalize_action_name(action: str) -> str:
    action = (action or "").strip().lower()
    action = re.sub(r"[^a-z0-9_-]+", "-", action)
    return re.sub(r"-+", "-", action).strip("-") or "action"


def _parse_anchor_date(raw: str = "") -> date:
    value = (raw or "").strip()
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(400, "date must be YYYY-MM-DD") from exc


def _date_range_bounds(anchor: date, range_name: str):
    normalized = (range_name or "day").strip().lower()
    if normalized not in {"day", "week"}:
        raise HTTPException(400, "range must be day or week")
    if normalized == "day":
        start = datetime.combine(anchor, datetime.min.time())
    else:
        start = datetime.combine(anchor - timedelta(days=6), datetime.min.time())
    end = datetime.combine(anchor + timedelta(days=1), datetime.min.time())
    return normalized, start, end


def _ensure_audit_schema():
    conn = get_db()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS action_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS decision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action_step_id INTEGER REFERENCES action_steps(id) ON DELETE SET NULL,
                decision TEXT NOT NULL,
                rationale TEXT,
                actor TEXT NOT NULL DEFAULT 'user',
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS execution_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action_step_id INTEGER REFERENCES action_steps(id) ON DELETE SET NULL,
                action_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                output TEXT,
                error TEXT,
                metadata TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_action_steps_entity ON action_steps(entity_type, entity_id, action_name, updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_events_entity ON decision_events(entity_type, entity_id, decision, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_attempts_entity ON execution_attempts(entity_type, entity_id, action_name, started_at)"
        )
        # Freshservice enrichment pipeline tables
        conn.execute(
            """CREATE TABLE IF NOT EXISTS classification_buckets (
                id TEXT PRIMARY KEY,
                description TEXT,
                knowledge_files TEXT DEFAULT '[]',
                confidence_keywords TEXT DEFAULT '[]',
                ticket_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'emerging',
                created_by_ticket INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS enrichment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER,
                stage TEXT,
                model TEXT,
                duration_ms INTEGER,
                status TEXT,
                response_summary TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        # Add enrichment_status column to cards if missing
        cursor = conn.execute("PRAGMA table_info(cards)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "enrichment_status" not in existing_cols:
            conn.execute(
                "ALTER TABLE cards ADD COLUMN enrichment_status TEXT DEFAULT 'not_enriched'"
            )
        conn.commit()
    finally:
        conn.close()


def _ensure_learning_events_schema():
    conn = get_db()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                hook_event TEXT,
                source TEXT,
                scope TEXT,
                tool_name TEXT,
                category TEXT,
                title TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'captured',
                requires_category_expansion INTEGER NOT NULL DEFAULT 0,
                proposed_category TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_events_session ON learning_events(session_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_events_category ON learning_events(category, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_events_pending ON learning_events(requires_category_expansion, created_at)"
        )
        conn.commit()
    finally:
        conn.close()


def _record_decision(entity_type: str, entity_id: str, action_name: str, decision: str, rationale: str = "", actor: str = "user", metadata=None):
    _ensure_audit_schema()
    entity = (entity_type or "").strip().lower()
    if entity not in {"card", "task"}:
        raise HTTPException(400, "entity_type must be card or task")
    action = _normalize_action_name(action_name)
    normalized_decision = (decision or "").strip().lower()
    if normalized_decision not in {"approved", "rejected", "refined"}:
        raise HTTPException(400, "decision must be approved, rejected, or refined")

    status_map = {
        "approved": "approved",
        "rejected": "rejected",
        "refined": "refined",
    }

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO action_steps (entity_type, entity_id, action_name, status, payload)
               VALUES (?, ?, ?, 'awaiting_approval', ?)""",
            [entity, str(entity_id), action, json.dumps(metadata or {})],
        )
        step_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """UPDATE action_steps
               SET status = ?, updated_at = datetime('now')
               WHERE id = ?""",
            [status_map[normalized_decision], step_id],
        )
        conn.execute(
            """INSERT INTO decision_events (
                   entity_type, entity_id, action_step_id, decision, rationale, actor, metadata
               )
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                entity,
                str(entity_id),
                step_id,
                normalized_decision,
                (rationale or "").strip(),
                actor or "user",
                json.dumps(metadata or {}),
            ],
        )
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if entity == "card":
            try:
                card_row = conn.execute("SELECT * FROM cards WHERE id = ?", [int(entity_id)]).fetchone()
                card = dict(card_row) if card_row else {}
                conn.execute(
                    """INSERT INTO decisions (
                           card_id, action, source, summary, context_notes, draft_response,
                           refinement_history, execution_result, decision_at, tags
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
                    [
                        int(entity_id),
                        action,
                        card.get("source", ""),
                        card.get("summary", ""),
                        card.get("context_notes", ""),
                        card.get("draft_response", ""),
                        card.get("refinement_history", ""),
                        card.get("execution_result", ""),
                        f"{normalized_decision},{action}",
                    ],
                )
            except sqlite3.Error:
                # Keep new workflow tables authoritative even if legacy decisions schema differs.
                pass
        if normalized_decision in {"rejected", "refined"} and (rationale or "").strip():
            try:
                _ensure_learning_events_schema()
                conn.execute(
                    """INSERT INTO learning_events (
                           session_id, hook_event, source, scope, tool_name, category,
                           title, note, status, requires_category_expansion, proposed_category, metadata
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'captured', 0, '', ?)""",
                    [
                        f"{entity}:{entity_id}",
                        "DecisionLoop",
                        "decision-loop",
                        f"{entity}:{action}",
                        action,
                        "failure-pattern",
                        f"{entity} {action} {normalized_decision}",
                        (rationale or "").strip(),
                        json.dumps(metadata or {}),
                    ],
                )
            except sqlite3.Error:
                pass
        conn.commit()
        return {"decision_event_id": event_id, "action_step_id": step_id, "status": status_map[normalized_decision]}
    finally:
        conn.close()


def _require_approved_decision(entity_type: str, entity_id: str, action_name: str, decision_event_id: int):
    _ensure_audit_schema()
    if not decision_event_id:
        raise HTTPException(400, "decision_event_id is required")
    entity = (entity_type or "").strip().lower()
    action = _normalize_action_name(action_name)

    conn = get_db()
    try:
        row = conn.execute(
            """SELECT de.id AS decision_event_id,
                      de.decision,
                      de.action_step_id,
                      s.action_name,
                      s.entity_type,
                      s.entity_id
               FROM decision_events de
               LEFT JOIN action_steps s ON s.id = de.action_step_id
               WHERE de.id = ?""",
            [int(decision_event_id)],
        ).fetchone()
        if not row:
            raise HTTPException(400, "decision_event_id not found")
        if str(row["entity_type"]) != entity or str(row["entity_id"]) != str(entity_id):
            raise HTTPException(400, "decision_event_id does not match target entity")
        if (row["decision"] or "").lower() != "approved":
            raise HTTPException(400, "decision_event_id is not an approved decision")
        if _normalize_action_name(row["action_name"] or "") != action:
            raise HTTPException(400, "approved decision is for a different action")
        return int(row["action_step_id"])
    finally:
        conn.close()


def _mark_action_step_status(action_step_id: int, status: str, payload=None):
    if not action_step_id:
        return
    _ensure_audit_schema()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE action_steps
               SET status = ?, payload = COALESCE(?, payload), updated_at = datetime('now')
               WHERE id = ?""",
            [status, json.dumps(payload) if payload is not None else None, int(action_step_id)],
        )
        conn.commit()
    finally:
        conn.close()


def _start_execution_attempt(entity_type: str, entity_id: str, action_name: str, action_step_id: int = None, metadata=None):
    _ensure_audit_schema()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO execution_attempts (
                   entity_type, entity_id, action_step_id, action_name, status, metadata
               )
               VALUES (?, ?, ?, ?, 'running', ?)""",
            [
                (entity_type or "").strip().lower(),
                str(entity_id),
                action_step_id,
                _normalize_action_name(action_name),
                json.dumps(metadata or {}),
            ],
        )
        attempt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return int(attempt_id)
    finally:
        conn.close()


def _finish_execution_attempt(attempt_id: int, status: str, output: str = "", error: str = ""):
    if not attempt_id:
        return
    _ensure_audit_schema()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE execution_attempts
               SET status = ?, output = ?, error = ?, finished_at = datetime('now')
               WHERE id = ?""",
            [status, output or "", error or "", int(attempt_id)],
        )
        conn.commit()
    finally:
        conn.close()


def _card_jira_keys(card: dict):
    parts = [
        str(card.get("summary", "")),
        str(card.get("context_notes", "")),
        str(card.get("draft_response", "")),
    ]
    try:
        parts.append(json.dumps(json.loads(card.get("proposed_actions") or "[]")))
    except json.JSONDecodeError:
        parts.append(str(card.get("proposed_actions") or ""))
    haystack = "\n".join(parts)
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", haystack)))


def _knowledge_roots():
    return {
        "knowledge": KNOWLEDGE_DIR,
        "patterns": PATTERNS_DIR,
        "stakeholders": STAKEHOLDERS_DIR,
        "memory": MEMORY_DIR,
    }


def _is_under_root(path: Path, root: Path):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_knowledge_path(path_str: str):
    requested = (path_str or "").strip()
    if not requested:
        raise HTTPException(400, "path is required")
    candidate = Path(requested).expanduser()
    if not candidate.is_absolute():
        candidate = (ENG_BUDDY_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    allowed = _knowledge_roots()
    for _group, root in allowed.items():
        if _is_under_root(candidate, root):
            if not candidate.exists() or not candidate.is_file():
                raise HTTPException(404, "document not found")
            return candidate
    raise HTTPException(400, "path is outside allowed read-only knowledge roots")


def _get_or_create_chat_session(scope: str, source: str, source_ref: str, title: str = ""):
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT id FROM chat_sessions
               WHERE scope = ? AND source_ref = ?""",
            [scope, source_ref],
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = datetime('now') WHERE id = ?",
                [row["id"]],
            )
            conn.commit()
            return row["id"]

        conn.execute(
            """INSERT INTO chat_sessions (scope, source, source_ref, title)
               VALUES (?, ?, ?, ?)""",
            [scope, source, source_ref, title],
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def _append_chat_message(session_id: int, role: str, content: str, metadata: dict = None):
    if not content or not content.strip():
        return None
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO chat_messages (session_id, role, content, metadata)
               VALUES (?, ?, ?, ?)""",
            [session_id, role, content.strip(), json.dumps(metadata or {})],
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = datetime('now') WHERE id = ?",
            [session_id],
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def _fetch_chat_history(session_id: int, limit: int = 200):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, role, content, created_at
               FROM chat_messages
               WHERE session_id = ?
               ORDER BY id ASC
               LIMIT ?""",
            [session_id, limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _history_to_turns(history_rows):
    return [{"role": row.get("role", "user"), "content": row.get("content", "")} for row in history_rows]


def _fetch_chat_session(session_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?",
            [session_id],
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _sync_card_refinement_history(card_id: int, session_id: int):
    history = _fetch_chat_history(session_id)
    compact = [
        {"id": row.get("id"), "role": row.get("role"), "content": row.get("content"), "created_at": row.get("created_at")}
        for row in history
    ]
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET refinement_history = ? WHERE id = ?",
            [json.dumps(compact), card_id],
        )
        conn.commit()
    finally:
        conn.close()


def _mark_chat_learning_ingested(session_id: int, last_message_id: int):
    conn = get_db()
    try:
        conn.execute(
            """UPDATE chat_sessions
               SET last_ingested_message_id = ?, updated_at = datetime('now')
               WHERE id = ?""",
            [last_message_id, session_id],
        )
        conn.commit()
    finally:
        conn.close()


def _ingest_chat_learning(session_id: int):
    """Run learning extraction for newly-added chat messages and route results."""
    try:
        session = _fetch_chat_session(session_id)
        if not session:
            return
        history = _fetch_chat_history(session_id)
        if not history:
            return

        last_ingested = int(session.get("last_ingested_message_id") or 0)
        new_rows = [row for row in history if int(row.get("id", 0)) > last_ingested]
        if not new_rows:
            return

        max_message_id = max(int(row.get("id", 0)) for row in new_rows)
        transcript = "\n".join(
            f"{row.get('role', 'user').upper()}: {row.get('content', '')}" for row in new_rows
        )

        sys_path = ENG_BUDDY_DIR / "bin"
        if str(sys_path) not in sys.path:
            sys.path.insert(0, str(sys_path))
        import brain

        context = brain.build_context_prompt()
        prompt = f"""{context}

Analyze this new chat transcript and emit only incremental learnings.
Source: {session.get('source', 'unknown')}
Scope: {session.get('scope', 'unknown')}
Reference: {session.get('source_ref', '')}
Title: {session.get('title', '')}

Transcript:
{transcript}

Return concise analysis and include JSON blocks for any applicable sections.
"""
        result = _run_claude_print(prompt, timeout=75)
        if result.returncode == 0 and result.stdout.strip():
            brain.parse_learning(result.stdout)

        _mark_chat_learning_ingested(session_id, max_message_id)
    except Exception:
        # Learning extraction should never block primary user actions.
        return


def _trigger_chat_learning(session_id: int):
    thread = threading.Thread(target=_ingest_chat_learning, args=(session_id,), daemon=True)
    thread.start()


def _row_to_card(row):
    card = dict(row)
    try:
        card["proposed_actions"] = json.loads(card.get("proposed_actions") or "[]")
    except (json.JSONDecodeError, TypeError):
        card["proposed_actions"] = []
    card["analysis_metadata"] = _card_analysis_metadata(card)
    card["enrichment_status"] = card.get("enrichment_status", "not_enriched") or "not_enriched"
    return card


def _parse_card_timestamp(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return None

    normalized = value.replace(" ", "T") if "T" not in value and " " in value else value
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _next_business_day_end(local_timestamp: datetime):
    next_day = local_timestamp.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return datetime.combine(next_day, datetime.max.time(), tzinfo=local_timestamp.tzinfo)


def _should_include_in_inbox_view(card: dict, source: str, days: int, now_utc: datetime, now_local: datetime):
    card_timestamp = _parse_card_timestamp(card.get("timestamp"))
    if card_timestamp is None:
        return True

    if card_timestamp >= now_utc - timedelta(days=days):
        return True

    if source != "slack":
        return False

    section = (card.get("section") or "").lower()
    classification = (card.get("classification") or "").lower()
    responded = bool(card.get("responded"))
    status = (card.get("status") or "").lower()
    needs_sections = {"needs-action", "action-needed", "needs_response", "needs-response"}
    no_action_sections = {"no-action", "noise", "responded", "fyi", "alert"}

    is_needs_action = section in needs_sections or (
        classification == "needs-response" and not responded
    )
    is_no_action = (
        section in no_action_sections
        or responded
        or status in {"completed", "failed"}
    ) and not is_needs_action

    if not is_no_action:
        return False

    local_timestamp = card_timestamp.astimezone(now_local.tzinfo or timezone.utc)
    retention_deadline = max(
        local_timestamp + timedelta(days=days),
        _next_business_day_end(local_timestamp),
    )
    return now_local <= retention_deadline

@app.get("/app")
@app.get("/app/{path:path}")
async def serve_react(path: str = ""):
    react_dir = Path(__file__).parent / "static-react"
    if react_dir.exists():
        return FileResponse(str(react_dir / "index.html"))
    return HTMLResponse("<h1>React build not found. Run npm run build in dashboard/frontend/</h1>", status_code=404)

@app.get("/")
async def root():
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/app", status_code=302)

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/restart-status")
async def restart_status():
    return _load_restart_status()


@app.post("/api/debug/send-to-claude")
async def send_debug_log_to_claude(body: dict = Body(default={})):
    log_line = str(body.get("log_line") or "").strip()
    if not log_line:
        raise HTTPException(400, "log_line required")

    level = str(body.get("level") or "error").strip().lower()
    tab = str(body.get("tab") or "UNKNOWN").strip().upper()
    timestamp = str(body.get("timestamp") or "").strip()
    details = body.get("details") or {}
    details_text = json.dumps(details, ensure_ascii=True, sort_keys=True)[:1200] if isinstance(details, dict) else ""

    message = (
        f"Dashboard debug log forwarded to Claude Code. "
        f"tab={tab} level={level} timestamp={timestamp or 'unknown'} line={log_line}"
    )
    if details_text:
        message += f" details={details_text}"

    _queue_claude_sync_event(message)
    _record_stat("debug_logs_forwarded")
    return {"queued": True, "message": message}


@app.get("/api/pollers/status")
async def get_poller_status():
    now = datetime.now(timezone.utc)
    return {
        "pollers": [_build_poller_status(poller, now) for poller in POLLER_DEFINITIONS],
        "generated_at": now.isoformat(),
    }


@app.post("/api/restart")
async def restart_server():
    """Restart the dashboard through its launchd-managed launcher with a fresh-data sync."""
    start_sh = Path(__file__).parent / "start.sh"
    if not start_sh.exists():
        raise HTTPException(500, "start.sh not found")

    try:
        subprocess.Popen(
            ["/bin/bash", str(start_sh), "--restart-fresh"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise HTTPException(500, f"failed to restart dashboard: {exc}") from exc
    return {"status": "restarting", "mode": "fresh", "manager": "launchd"}


@app.get("/api/daily/logs")
async def get_daily_logs():
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(DAILY_DIR.glob("*.md"), reverse=True):
        stat = path.stat()
        stem = path.stem
        day = stem[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", stem) else ""
        try:
            rel_path = str(path.relative_to(ENG_BUDDY_DIR))
        except ValueError:
            rel_path = str(path)
        files.append(
            {
                "date": day,
                "name": path.name,
                "path": rel_path,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return {"logs": files, "count": len(files)}


@app.get("/api/daily/logs/{day}")
async def get_daily_log(day: str):
    anchor = _parse_anchor_date(day).isoformat()
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    primary = DAILY_DIR / f"{anchor}.md"
    candidate = primary
    if not candidate.exists():
        matches = sorted(DAILY_DIR.glob(f"{anchor}*.md"))
        if not matches:
            raise HTTPException(404, f"daily log not found for {anchor}")
        candidate = matches[0]

    content = candidate.read_text(encoding="utf-8", errors="replace")
    sections = []
    current = None
    for line in content.splitlines():
        if line.startswith("#"):
            if current:
                sections.append(current)
            current = {"heading": line.strip(), "lines": []}
        elif current is None:
            current = {"heading": "Body", "lines": [line]}
        else:
            current["lines"].append(line)
    if current:
        sections.append(current)

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT metric, SUM(value) AS total
               FROM stats
               WHERE date = ?
               GROUP BY metric""",
            [anchor],
        ).fetchall()
        stats = {row["metric"]: row["total"] for row in rows}
    finally:
        conn.close()

    return {
        "date": anchor,
        "file": str(candidate),
        "content": content,
        "sections": [{"heading": s["heading"], "content": "\n".join(s["lines"]).strip()} for s in sections],
        "stats": stats,
    }


@app.get("/api/learnings/summary")
async def get_learnings_summary(range: str = "day", date: str = ""):
    _ensure_learning_events_schema()
    anchor = _parse_anchor_date(date)
    range_name, start, end = _date_range_bounds(anchor, range)

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT category,
                      status,
                      COUNT(*) AS count
               FROM learning_events
               WHERE datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               GROUP BY category, status
               ORDER BY count DESC""",
            [start.isoformat(sep=" "), end.isoformat(sep=" ")],
        ).fetchall()
        top_titles = conn.execute(
            """SELECT COALESCE(NULLIF(title, ''), '(untitled)') AS title,
                      COUNT(*) AS count
               FROM learning_events
               WHERE datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               GROUP BY title
               ORDER BY count DESC, title ASC
               LIMIT 10""",
            [start.isoformat(sep=" "), end.isoformat(sep=" ")],
        ).fetchall()
        pending = conn.execute(
            """SELECT COALESCE(NULLIF(proposed_category, ''), 'uncategorized') AS category,
                      COUNT(*) AS count
               FROM learning_events
               WHERE requires_category_expansion = 1
                 AND datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               GROUP BY proposed_category
               ORDER BY count DESC, category ASC""",
            [start.isoformat(sep=" "), end.isoformat(sep=" ")],
        ).fetchall()
    finally:
        conn.close()

    by_bucket = {}
    for row in rows:
        bucket = (row["category"] or "uncategorized").strip() or "uncategorized"
        by_bucket.setdefault(bucket, {"captured": 0, "needs_category_expansion": 0, "total": 0})
        st = (row["status"] or "captured").strip()
        by_bucket[bucket][st] = row["count"]
        by_bucket[bucket]["total"] += row["count"]

    return {
        "range": range_name,
        "anchor_date": anchor.isoformat(),
        "window_start": start.date().isoformat(),
        "window_end_exclusive": end.date().isoformat(),
        "by_bucket": by_bucket,
        "top_titles": [{"title": r["title"], "count": r["count"]} for r in top_titles],
        "pending_category_expansions": [{"category": r["category"], "count": r["count"]} for r in pending],
    }


@app.get("/api/learnings/events")
async def get_learning_events(range: str = "day", date: str = "", limit: int = 200):
    _ensure_learning_events_schema()
    anchor = _parse_anchor_date(date)
    range_name, start, end = _date_range_bounds(anchor, range)
    limit = max(1, min(int(limit), 1000))

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, session_id, hook_event, source, scope, tool_name,
                      category, title, note, status, requires_category_expansion,
                      proposed_category, created_at
               FROM learning_events
               WHERE datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               ORDER BY datetime(created_at) DESC, id DESC
               LIMIT ?""",
            [start.isoformat(sep=" "), end.isoformat(sep=" "), limit],
        ).fetchall()
    finally:
        conn.close()

    return {
        "range": range_name,
        "anchor_date": anchor.isoformat(),
        "events": [dict(r) for r in rows],
    }


@app.get("/api/knowledge/index")
async def get_knowledge_index():
    roots = _knowledge_roots()
    entries = []
    include_ext = {".md", ".txt", ".json"}
    for group, root in roots.items():
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in include_ext:
                continue
            stat = path.stat()
            entries.append(
                {
                    "group": group,
                    "name": path.name,
                    "path": str(path.relative_to(ENG_BUDDY_DIR)),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

    entries.sort(key=lambda item: (item["group"], item["path"]))
    return {"documents": entries, "count": len(entries)}


@app.get("/api/knowledge/doc")
async def get_knowledge_doc(path: str):
    resolved = _resolve_knowledge_path(path)
    content = resolved.read_text(encoding="utf-8", errors="replace")
    try:
        rel_path = str(resolved.relative_to(ENG_BUDDY_DIR))
    except ValueError:
        rel_path = str(resolved)
    return {
        "path": rel_path,
        "absolute_path": str(resolved),
        "name": resolved.name,
        "is_markdown": resolved.suffix.lower() == ".md",
        "content": content,
        "size": resolved.stat().st_size,
        "modified_at": datetime.fromtimestamp(resolved.stat().st_mtime).isoformat(),
    }

@app.get("/api/cards")
async def get_cards(source: str = None, status: str | None = None, section: str = None):
    conn = get_db()
    try:
        query = "SELECT * FROM cards WHERE 1=1"
        params = []
        if status is None:
            status = "all" if source == "calendar" else "pending"
        if status != "all":
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)
        if section:
            query += " AND section = ?"
            params.append(section)
        query += " ORDER BY timestamp DESC"
        rows = conn.execute(query, params).fetchall()
        cards = [_row_to_card(row) for row in rows]
        counts = {}
        for s in ["pending", "held", "approved", "completed", "failed"]:
            counts[s] = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE status = ?", [s]
            ).fetchone()[0]
        return {"cards": cards, "counts": counts}
    finally:
        conn.close()


def _latest_suggestion_analysis_timestamp(cards):
    timestamps = []
    for card in cards:
        meta = card.get("analysis_metadata", {})
        if meta.get("last_analyzed_at"):
            timestamps.append(meta["last_analyzed_at"])
    return max(timestamps) if timestamps else ""


def _group_suggestion_cards(cards):
    groups = {key: [] for key in SUGGESTION_CATEGORY_ORDER}
    held = []
    for card in cards:
        meta = card.get("analysis_metadata", {})
        category = _suggestion_category_value(meta.get("category", card.get("section", "")))
        if card.get("status") == "held":
            held.append(card)
            continue
        if card.get("status") != "pending":
            continue
        groups.setdefault(category, []).append(card)
    return groups, held


@app.get("/api/suggestions")
async def get_suggestions(refresh: bool = False):
    refresh_result = None
    if refresh:
        refresh_result = _refresh_suggestions_sync()

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM cards WHERE source = ? ORDER BY timestamp DESC, id DESC",
            [SUGGESTION_SOURCE],
        ).fetchall()
        cards = [_row_to_card(row) for row in rows]
    finally:
        conn.close()

    groups, held = _group_suggestion_cards(cards)
    return {
        "source": SUGGESTION_SOURCE,
        "sections": [
            {
                "key": key,
                "label": SUGGESTION_CATEGORY_LABELS[key],
                "cards": groups.get(key, []),
                "count": len(groups.get(key, [])),
            }
            for key in SUGGESTION_CATEGORY_ORDER
        ],
        "held": held,
        "held_count": len(held),
        "last_analyzed_at": _latest_suggestion_analysis_timestamp(cards),
        "refresh_result": refresh_result,
    }


@app.post("/api/suggestions/refresh")
async def refresh_suggestions():
    return _refresh_suggestions_sync()


# ========== PLAYBOOK ENGINE ==========

PLAYBOOKS_DIR = os.path.expanduser("~/.claude/eng-buddy/playbooks")
BRAIN_PY = os.path.expanduser("~/.claude/eng-buddy/bin/brain.py")

# Add playbook_engine to import path once at module level (thread-safe)
_PLAYBOOK_ENGINE_PATH = os.path.expanduser("~/.claude/eng-buddy/bin")
if _PLAYBOOK_ENGINE_PATH not in sys.path:
    sys.path.insert(0, _PLAYBOOK_ENGINE_PATH)


def _get_playbook_manager():
    """Get a PlaybookManager instance (lazy import at module level)."""
    from playbook_engine.manager import PlaybookManager
    return PlaybookManager(PLAYBOOKS_DIR)


def _run_brain(args: list, stdin_data: str = None) -> dict:
    """Run brain.py with playbook args and return parsed JSON."""
    cmd = ["python3", BRAIN_PY] + args
    result = subprocess.run(cmd, capture_output=True, text=True, input=stdin_data, timeout=30)
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from brain.py", "raw": result.stdout}


@app.get("/api/playbooks")
async def list_playbooks():
    """List all approved playbooks."""
    return _run_brain(["--playbook-list"])


@app.get("/api/playbooks/drafts")
async def list_draft_playbooks():
    """List all draft playbooks awaiting review."""
    return _run_brain(["--playbook-list-drafts"])


@app.get("/api/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str):
    """Get a specific playbook with full step details."""
    mgr = _get_playbook_manager()
    pb = mgr.get(playbook_id) or mgr.get_draft(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb.to_dict()


@app.post("/api/playbooks/{playbook_id}/promote")
async def promote_playbook(playbook_id: str):
    """Promote a draft playbook to approved."""
    return _run_brain(["--playbook-promote", playbook_id])


@app.delete("/api/playbooks/drafts/{playbook_id}")
async def delete_draft_playbook(playbook_id: str):
    """Delete a draft playbook."""
    mgr = _get_playbook_manager()
    if mgr.delete_draft(playbook_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/playbooks/match")
async def match_playbook(body: dict = Body(...)):
    """Match a ticket against known playbooks."""
    text = body.get("text", "")
    ticket_type = body.get("ticket_type", "")
    source = body.get("source", "freshservice")
    args = ["--playbook-match", text]
    if ticket_type:
        args += ["--playbook-match-type", ticket_type]
    if source:
        args += ["--playbook-match-source", source]
    return _run_brain(args)


@app.post("/api/playbooks/execute")
async def execute_playbook(body: dict = Body(...)):
    """Dispatch a playbook for execution in user's terminal."""
    playbook_id = body.get("playbook_id")
    ticket_context = body.get("ticket_context", {})
    approval = body.get("approval", "approve all")

    mgr = _get_playbook_manager()
    pb = mgr.get(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")

    # Parse approval to determine which steps to execute
    excluded_steps = _parse_approval(approval, len(pb.steps))

    # Build the prompt for Claude Code
    step_list = []
    for step in pb.steps:
        if step.id in excluded_steps:
            step_list.append(f"  {step.id}. [SKIP] {step.name}")
        else:
            tool_label = step.action.tool.split("__")[-1] if "__" in step.action.tool else step.action.tool
            step_list.append(f"  {step.id}. {step.name} -> {tool_label}")

    prompt = f"""Execute playbook: {pb.name} (v{pb.version})
Ticket: {ticket_context.get('title', 'N/A')}

Steps:
{chr(10).join(step_list)}

Approval: {approval}

Use the eng-buddy skill. Execute each non-skipped step using the specified tools.
For human-required steps, open the browser to the right page and wait for user signal.
Report progress after each step."""

    # Launch in user's terminal via osascript (write prompt to temp file to avoid shell injection)
    prompt_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="playbook-", delete=False)
    prompt_file.write(prompt)
    prompt_file.close()
    launch_cmd = [
        "osascript", "-e",
        f'tell application "Terminal" to do script "claude --print \\"$(cat {prompt_file.name})\\"; rm -f {prompt_file.name}"',
    ]

    result = subprocess.run(launch_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return {"status": "dispatched", "playbook_id": playbook_id, "steps": len(pb.steps), "excluded": list(excluded_steps)}
    return {"error": "Failed to launch terminal", "details": result.stderr}


def _parse_approval(approval: str, total_steps: int) -> set:
    """Parse approval string into set of excluded step IDs."""
    excluded = set()
    approval_lower = approval.lower().strip()

    if approval_lower == "approve all":
        return excluded

    # "approve all but #3, #5"
    but_match = re.search(r"but\s+(.+)", approval_lower)
    if but_match:
        nums = re.findall(r"#?(\d+)", but_match.group(1))
        excluded = {int(n) for n in nums if 1 <= int(n) <= total_steps}

    return excluded


# ========== PLAN ENGINE ==========

_PLANNER_PATH = str(Path(__file__).parent.parent / "bin" / "planner")
if _PLANNER_PATH not in sys.path:
    sys.path.insert(0, _PLANNER_PATH)

PLANS_DIR = str(Path.home() / ".claude" / "eng-buddy" / "plans")
REGISTRY_DIR = str(Path(__file__).parent.parent / "playbooks" / "tool-registry")


def _get_plan_store():
    from store import PlanStore
    return PlanStore(PLANS_DIR, str(DB_PATH))


@app.get("/api/cards/{card_id}/plan")
async def get_card_plan(card_id: int):
    store = _get_plan_store()
    plan = store.get(card_id)
    if not plan:
        raise HTTPException(404, "No plan for this card")
    return {"plan": plan.to_dict()}


@app.patch("/api/cards/{card_id}/plan/steps/{step_index}")
async def update_plan_step(card_id: int, step_index: int, body: dict = Body(...)):
    store = _get_plan_store()
    plan = store.get(card_id)
    if not plan:
        raise HTTPException(404, "No plan for this card")
    step = plan.get_step(step_index)
    if not step:
        raise HTTPException(404, f"Step {step_index} not found")
    new_status = body.get("status", step.status)
    new_draft = body.get("draft_content")
    if new_draft is not None and new_draft != step.draft_content:
        step.draft_content = new_draft
        step.status = "edited"
    else:
        step.status = new_status
    store.save(plan)
    _stale_sources.add("plans")
    return {"step": step.to_dict()}


@app.post("/api/cards/{card_id}/plan/approve-remaining")
async def approve_remaining_steps(card_id: int, body: dict = Body(...)):
    store = _get_plan_store()
    plan = store.get(card_id)
    if not plan:
        raise HTTPException(404, "No plan for this card")
    from_index = body.get("from_index", 1)
    approved = 0
    for step in plan.all_steps():
        if step.index >= from_index and step.status == "pending":
            step.status = "approved"
            approved += 1
    store.save(plan)
    _stale_sources.add("plans")
    return {"approved_count": approved, "plan": plan.to_dict()}


@app.post("/api/cards/{card_id}/plan/execute")
async def execute_plan(card_id: int):
    store = _get_plan_store()
    plan = store.get(card_id)
    if not plan:
        raise HTTPException(404, "No plan for this card")
    lines = [f"Execute this plan for card #{card_id}. Follow each step exactly.\n"]
    step_count = 0
    skipped = []
    for phase in plan.phases:
        lines.append(f"\n## Phase: {phase.name}\n")
        for step in phase.steps:
            if step.status == "skipped":
                skipped.append(step.index)
                lines.append(f"Step {step.index}: [SKIPPED] {step.summary}")
                continue
            if step.status not in ("approved", "edited"):
                skipped.append(step.index)
                continue
            step_count += 1
            lines.append(f"Step {step.index}: {step.summary}")
            lines.append(f"  Tool: {step.tool}")
            if step.params:
                lines.append(f"  Params: {json.dumps(step.params)}")
            if step.draft_content:
                lines.append(f"  Content: {step.draft_content}")
            lines.append("")
    prompt_text = "\n".join(lines)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt_text)
        prompt_file = f.name
    plan.status = "executing"
    store.save(plan)
    # Write a shell wrapper to avoid AppleScript string interpolation issues
    import shlex
    wrapper_file = prompt_file + ".sh"
    with open(wrapper_file, "w") as wf:
        wf.write(f"#!/bin/bash\nclaude --print -p - < {shlex.quote(prompt_file)}\n")
    os.chmod(wrapper_file, 0o755)
    script = f'tell application "Terminal"\n    activate\n    do script "{shlex.quote(wrapper_file)}"\nend tell'
    subprocess.Popen(["osascript", "-e", script])
    return {"status": "dispatched", "steps": step_count, "skipped": skipped}


@app.post("/api/cards/{card_id}/plan/regenerate")
async def regenerate_plan(card_id: int, body: dict = Body(...)):
    store = _get_plan_store()
    feedback = body.get("feedback")
    store.delete(card_id)
    # Store feedback so worker can pass it to CardPlanner.regenerate()
    if feedback:
        feedback_path = Path(PLANS_DIR) / f"{card_id}.feedback"
        feedback_path.write_text(feedback)
    _stale_sources.add("plans")
    return {"status": "queued", "feedback": feedback}


@app.post("/api/cards/approve-all")
async def approve_all_cards_guard():
    raise HTTPException(405, "Bulk card approval is disabled. Approve cards one-by-one.")


@app.get("/api/inbox-view")
async def get_inbox_view(source: str, days: int = 3):
    """Return grouped inbox cards for Slack/Gmail across recent activity."""
    if source not in {"slack", "gmail"}:
        raise HTTPException(400, "source must be slack or gmail")
    days = max(1, min(days, 14))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    lookback_days = max(days, 7) if source == "slack" else days
    cutoff = (now_utc - timedelta(days=lookback_days)).isoformat()

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM cards
               WHERE source = ?
                 AND timestamp >= ?
               ORDER BY timestamp DESC""",
            [source, cutoff],
        ).fetchall()
    finally:
        conn.close()

    cards = []
    for row in rows:
        card = _row_to_card(row)
        if not _should_include_in_inbox_view(card, source, days, now_utc, now_local):
            continue
        cards.append(card)

    if source == "gmail":
        cards = _collapse_gmail_duplicates(cards)

    needs_sections = {"needs-action", "action-needed", "needs_response", "needs-response"}
    no_action_sections = {"no-action", "noise", "responded", "fyi", "alert"}
    needs_action = []
    no_action = []

    for card in cards:
        section = (card.get("section") or "").lower()
        classification = (card.get("classification") or "").lower()
        responded = bool(card.get("responded"))
        status = (card.get("status") or "").lower()

        is_needs_action = section in needs_sections or (
            classification == "needs-response" and not responded
        )
        is_no_action = (
            section in no_action_sections
            or responded
            or status in {"completed", "failed"}
        ) and not is_needs_action

        if is_needs_action:
            needs_action.append(card)
        elif is_no_action:
            no_action.append(card)
        else:
            no_action.append(card)

    return {
        "source": source,
        "days": days,
        "needs_action": needs_action,
        "no_action": no_action,
    }


def _parse_active_tasks():
    if not TASKS_FILE.exists():
        return []

    content = TASKS_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    tasks = []
    section = "unknown"
    current = None

    def flush_current():
        if not current:
            return
        description = "\n".join(current.get("description_lines", [])).strip()
        current["description"] = description
        current.pop("description_lines", None)
        tasks.append(current.copy())

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower().replace(" ", "-")
            continue

        task_match = re.match(r"^###\s+#(\d+)\s*-\s*(.+)$", line)
        if task_match:
            flush_current()
            current = {
                "number": int(task_match.group(1)),
                "title": task_match.group(2).strip(),
                "status": "unknown",
                "priority": "unknown",
                "section": section,
                "description_lines": [],
            }
            continue

        if not current:
            continue

        status_match = re.match(r"^\*\*Status\*\*:\s*(.+)$", line)
        if status_match:
            current["status"] = status_match.group(1).strip()
            continue

        priority_match = re.match(r"^\*\*Priority\*\*:\s*(.+)$", line)
        if priority_match:
            current["priority"] = priority_match.group(1).strip()
            continue

        description_match = re.match(r"^\*\*Description\*\*:\s*(.*)$", line)
        if description_match:
            desc_start = description_match.group(1).strip()
            if desc_start:
                current["description_lines"].append(desc_start)
            continue

        if line.startswith("### "):
            flush_current()
            current = None
            continue

        if line and (line.startswith("-") or current.get("description_lines")):
            current["description_lines"].append(line)

    flush_current()
    return tasks


def _next_task_number():
    tasks = _parse_active_tasks()
    numbers = [int(task.get("number", 0)) for task in tasks if str(task.get("number", "")).isdigit()]
    return (max(numbers) if numbers else 0) + 1


def _append_task_from_suggestion(card: dict, metadata: dict):
    task_number = _next_task_number()
    task_draft = metadata.get("task_draft") if isinstance(metadata.get("task_draft"), dict) else {}
    title = str(task_draft.get("title", "")).strip() or str(card.get("summary", "")).strip()
    priority = str(task_draft.get("priority", "")).strip() or str(metadata.get("priority", "medium")).strip()
    description = str(task_draft.get("description", "")).strip() or str(card.get("context_notes", "")).strip()
    evidence = metadata.get("evidence") if isinstance(metadata.get("evidence"), list) else []
    source_lines = metadata.get("generated_from") if isinstance(metadata.get("generated_from"), list) else []

    block_lines = [
        f"### #{task_number} - {title}",
        "**Status**: pending",
        f"**Priority**: {priority}",
        f"**Description**: {description or 'Follow up on approved dashboard suggestion.'}",
    ]
    if evidence:
        block_lines.append("**Evidence**:")
        block_lines.extend([f"- {str(item).strip()}" for item in evidence if str(item).strip()])
    if source_lines:
        block_lines.append("**Generated From**:")
        block_lines.extend([f"- {str(item).strip()}" for item in source_lines if str(item).strip()])

    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    block_text = "\n".join(block_lines).rstrip() + "\n"
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text("## PENDING TASKS\n\n" + block_text, encoding="utf-8")
        return task_number

    content = TASKS_FILE.read_text(encoding="utf-8")
    pending_match = re.search(r"^##\s+PENDING TASKS\s*$", content, flags=re.MULTILINE)
    if pending_match:
        insert_at = pending_match.end()
        updated = content[:insert_at] + "\n\n" + block_text + content[insert_at:]
    else:
        separator = "\n\n" if content.strip() else ""
        updated = content.rstrip() + f"{separator}## PENDING TASKS\n\n" + block_text
    TASKS_FILE.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return task_number


def _append_automation_draft(card: dict, metadata: dict, task_number: int):
    automation_draft = metadata.get("automation_draft") if isinstance(metadata.get("automation_draft"), dict) else {}
    name = str(automation_draft.get("name", "")).strip() or str(card.get("summary", "")).strip()
    problem = str(automation_draft.get("problem", "")).strip() or str(card.get("context_notes", "")).strip()
    proposal = str(automation_draft.get("proposal", "")).strip() or "Implement the approved automation suggestion."
    signals = automation_draft.get("signals") if isinstance(automation_draft.get("signals"), list) else []
    guardrails = automation_draft.get("guardrails") if isinstance(automation_draft.get("guardrails"), list) else []

    AUTOMATION_DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## Task #{task_number} - {name}",
        f"- Card ID: {card.get('id')}",
        f"- Category: {metadata.get('category', 'automation')}",
        f"- Problem: {problem}",
        f"- Proposal: {proposal}",
    ]
    if signals:
        lines.append("- Signals:")
        lines.extend([f"  - {str(item).strip()}" for item in signals if str(item).strip()])
    if guardrails:
        lines.append("- Guardrails:")
        lines.extend([f"  - {str(item).strip()}" for item in guardrails if str(item).strip()])

    draft_block = "\n".join(lines).rstrip() + "\n\n"
    if AUTOMATION_DRAFTS_FILE.exists():
        existing = AUTOMATION_DRAFTS_FILE.read_text(encoding="utf-8")
    else:
        existing = "# Automation Drafts\n\n"
    AUTOMATION_DRAFTS_FILE.write_text(existing.rstrip() + "\n\n" + draft_block, encoding="utf-8")
    return str(AUTOMATION_DRAFTS_FILE)


def _task_jira_keys(task: dict):
    search_text = f"{task.get('title', '')}\n{task.get('description', '')}"
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", search_text)))


def _get_task_by_number(task_number: int):
    for task in _parse_active_tasks():
        if task.get("number") == task_number:
            return task
    return None


def _upsert_task_metadata_line(block: str, label: str, value: str):
    pattern = rf"^\*\*{re.escape(label)}\*\*:\s*.*$"
    replacement = f"**{label}**: {value}"
    if re.search(pattern, block, flags=re.MULTILINE):
        return re.sub(pattern, replacement, block, count=1, flags=re.MULTILINE)

    lines = block.splitlines()
    insert_at = len(lines)
    for idx, line in enumerate(lines[1:], start=1):
        if line.startswith("**Description**:"):
            insert_at = idx
            break
    lines.insert(insert_at, replacement)
    return "\n".join(lines)


def _set_task_status(task_number: int, new_status: str, completion_note: str = ""):
    """Update matching task blocks and move completed ones into the completed section."""
    if not TASKS_FILE.exists():
        return 0

    content = TASKS_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^###\s+#{task_number}\s*-\s*.+?)(?=^###\s+#\d+\s*-|^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    matches = list(pattern.finditer(content))
    if not matches:
        return 0

    updated_blocks = []

    for match in matches:
        block = match.group(1).rstrip()
        if re.search(r"^\*\*Status\*\*:\s*.+$", block, flags=re.MULTILINE):
            block = re.sub(
                r"^\*\*Status\*\*:\s*.+$",
                f"**Status**: {new_status}",
                block,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            lines = block.splitlines()
            if lines:
                block = "\n".join([lines[0], f"**Status**: {new_status}", *lines[1:]])

        if completion_note:
            block = _upsert_task_metadata_line(block, "Completion Note", completion_note)

        updated_blocks.append(block)

    updated = pattern.sub("", content).rstrip()
    completed_heading = "## COMPLETED TASKS"
    completed_match = re.search(r"^##\s+COMPLETED TASKS\s*$", updated, flags=re.MULTILINE)
    blocks_text = "\n\n".join(updated_blocks)

    if completed_match:
        head = updated[:completed_match.end()].rstrip("\n")
        tail = updated[completed_match.end():].lstrip("\n")
        pieces = [head, "", blocks_text]
        if tail.strip():
            pieces.extend(["", tail.rstrip()])
        updated = "\n".join(pieces)
    else:
        pieces = [updated] if updated else []
        pieces.extend([completed_heading, "", blocks_text])
        updated = "\n\n".join(piece for piece in pieces if piece != "")

    TASKS_FILE.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return len(updated_blocks)


def _append_daily_log_completed(entry: str):
    """Append an entry under today's completed section, creating file if needed."""
    completed_heading = "## \u2705 Completed"
    today = date.today()
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    daily_file = DAILY_DIR / f"{today.isoformat()}.md"

    if not daily_file.exists():
        weekday = today.strftime("%A")
        template = (
            f"# Daily Log - {today.isoformat()} ({weekday})\n\n"
            f"{completed_heading}\n\n"
        )
        daily_file.write_text(template, encoding="utf-8")

    content = daily_file.read_text(encoding="utf-8")
    if entry in content:
        return daily_file, False

    lines = content.splitlines()
    heading_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip() in {completed_heading, "## Completed"}
        ),
        None,
    )

    if heading_idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([completed_heading, entry])
    else:
        insert_at = heading_idx + 1
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines.insert(insert_at, entry)

    daily_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return daily_file, True


def _queue_claude_sync_event(message: str):
    text = (message or "").strip()
    if not text:
        return
    CLAUDE_SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CLAUDE_SYNC_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{timestamp}] {text}\n")


def _build_task_daily_log_line(task: dict, close_note: str = ""):
    """Use Claude to draft a concise daily-log line for a completed task."""
    jira_keys = ", ".join(_task_jira_keys(task)) or "none"
    prompt = (
        "You are preparing a single line for an engineering daily log.\n"
        "Return ONLY one plain text sentence fragment (no bullets, no markdown, no timestamp).\n"
        "Keep it concise and specific.\n\n"
        f"Task #{task.get('number')}: {task.get('title', '')}\n"
        f"Status: {task.get('status', 'unknown')}\n"
        f"Priority: {task.get('priority', 'unknown')}\n"
        f"Jira keys: {jira_keys}\n"
        f"Description:\n{task.get('description', '')}\n\n"
        f"Close note: {close_note or '(none)'}\n"
    )
    result = _run_claude_print(prompt, timeout=45)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200] or "claude daily-log generation failed")

    line = (result.stdout or "").strip().splitlines()[0].strip()
    if not line:
        raise RuntimeError("empty daily-log line from claude")
    return line


def _related_cards_for_task(conn, task):
    title = task.get("title", "")
    description = task.get("description", "")
    search_text = f"{title}\n{description}"
    jira_keys = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", search_text)))

    queries = []
    params = []
    for key in jira_keys:
        queries.append("summary LIKE ?")
        params.append(f"%{key}%")

    if not queries:
        core_terms = [w for w in re.findall(r"[A-Za-z0-9]{4,}", title)[:4]]
        for term in core_terms:
            queries.append("summary LIKE ?")
            params.append(f"%{term}%")

    if not queries:
        return []

    sql = (
        "SELECT id, source, summary, status, timestamp "
        "FROM cards WHERE (" + " OR ".join(queries) + ") "
        "ORDER BY timestamp DESC LIMIT 8"
    )
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/tasks")
async def get_tasks():
    tasks = _parse_active_tasks()
    conn = get_db()
    try:
        enriched = []
        for task in tasks:
            related = _related_cards_for_task(conn, task)
            task_copy = dict(task)
            task_copy["jira_keys"] = _task_jira_keys(task_copy)
            task_copy["related_cards"] = related
            enriched.append(task_copy)
    finally:
        conn.close()

    return {
        "tasks": enriched,
        "count": len(enriched),
        "file": str(TASKS_FILE),
    }


@app.post("/api/tasks/{task_number}/decision")
async def record_task_decision(task_number: int, body: dict = Body(...)):
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")
    action = body.get("action", "")
    decision = body.get("decision", "")
    rationale = body.get("rationale", "")
    metadata = {"task_number": task_number, "title": task.get("title", "")}
    result = _record_decision("task", str(task_number), action, decision, rationale=rationale, metadata=metadata)
    return {
        "task_number": task_number,
        "action": _normalize_action_name(action),
        "decision": (decision or "").strip().lower(),
        **result,
    }


@app.get("/api/tasks/{task_number}/timeline")
async def get_task_timeline(task_number: int, limit: int = 500):
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")
    limit = max(1, min(int(limit), 2000))
    entity_id = str(task_number)
    _ensure_audit_schema()
    conn = get_db()
    try:
        chat_rows = conn.execute(
            """SELECT m.id AS item_id,
                      'chat' AS kind,
                      m.created_at AS happened_at,
                      s.scope AS scope,
                      m.role AS role,
                      m.content AS content
               FROM chat_messages m
               JOIN chat_sessions s ON s.id = m.session_id
               WHERE s.source_ref = ?
                 AND s.scope LIKE 'task_%'
               ORDER BY m.id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
        decision_rows = conn.execute(
            """SELECT de.id AS item_id,
                      'decision' AS kind,
                      de.created_at AS happened_at,
                      s.action_name AS action_name,
                      de.decision AS decision,
                      de.rationale AS rationale
               FROM decision_events de
               LEFT JOIN action_steps s ON s.id = de.action_step_id
               WHERE de.entity_type = 'task' AND de.entity_id = ?
               ORDER BY de.id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
        attempt_rows = conn.execute(
            """SELECT id AS item_id,
                      'execution' AS kind,
                      started_at AS happened_at,
                      action_name,
                      status,
                      output,
                      error,
                      finished_at
               FROM execution_attempts
               WHERE entity_type = 'task' AND entity_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
    finally:
        conn.close()

    combined = [dict(r) for r in chat_rows] + [dict(r) for r in decision_rows] + [dict(r) for r in attempt_rows]
    combined.sort(key=lambda item: (item.get("happened_at") or "", item.get("item_id") or 0), reverse=True)
    return {"task_number": task_number, "timeline": combined[:limit]}


@app.post("/api/tasks/{task_number}/open-session")
async def open_task_session(task_number: int):
    """Spawn a full interactive claude session for a task."""
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")

    context = (
        f"eng-buddy task from tasks tab\n"
        f"Task #{task['number']}: {task.get('title', '')}\n"
        f"Status: {task.get('status', 'unknown')}\n"
        f"Priority: {task.get('priority', 'unknown')}\n"
        f"Section: {task.get('section', 'unknown')}\n"
        f"Description:\n{task.get('description', '')}\n\n"
        f"Work through this task with the user step by step."
    )

    session_id = _get_or_create_chat_session(
        scope="task_terminal_session",
        source="tasks",
        source_ref=str(task_number),
        title=task.get("title", ""),
    )
    launcher = _launch_terminal_session(
        context,
        launcher_prefix="open-task-session-",
        chat_session_id=session_id,
    )
    return {
        "status": "opened",
        "terminal": TERMINAL_APP,
        "launcher": launcher,
        "chat_session_id": session_id,
    }


@app.post("/api/tasks/{task_number}/refine")
async def refine_task(task_number: int, body: dict = Body(...)):
    """Single-turn refinement for an active task."""
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")

    user_message = (body.get("message") or "").strip()
    history = body.get("history")
    if not user_message:
        raise HTTPException(400, "message is required")

    session_id = _get_or_create_chat_session(
        scope="task_refine",
        source="tasks",
        source_ref=str(task_number),
        title=task.get("title", ""),
    )
    if isinstance(history, list) and history:
        history_turns = history
    else:
        history_turns = _history_to_turns(_fetch_chat_history(session_id))

    context = (
        f"You are eng-buddy helping refine a tracked task before execution.\n\n"
        f"Task #{task['number']}: {task.get('title', '')}\n"
        f"Status: {task.get('status', 'unknown')}\n"
        f"Priority: {task.get('priority', 'unknown')}\n"
        f"Jira keys: {', '.join(_task_jira_keys(task)) or 'none'}\n\n"
        f"Description:\n{task.get('description', '')}\n\n"
        "Give practical next steps, suggest concrete edits, and call out missing info."
    )

    conversation = context + "\n\n"
    for turn in history_turns:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        conversation += f"{role.upper()}: {content}\n"
    conversation += f"USER: {user_message}\n"

    result = _run_claude_print(conversation, timeout=60)
    if result.returncode != 0:
        raise HTTPException(502, f"task refine failed: {result.stderr[:200]}")
    response = result.stdout.strip()

    _append_chat_message(
        session_id,
        "user",
        user_message,
        metadata={"task_number": task_number, "source": "tasks"},
    )
    _append_chat_message(
        session_id,
        "assistant",
        response,
        metadata={"task_number": task_number, "source": "tasks"},
    )
    try:
        _record_decision(
            "task",
            str(task_number),
            "refine",
            "refined",
            rationale=user_message,
            metadata={"task_number": task_number},
        )
    except HTTPException:
        pass
    _trigger_chat_learning(session_id)
    return {"response": response}


@app.get("/api/tasks/{task_number}/chat-history")
async def get_task_chat_history(task_number: int):
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")
    session_id = _get_or_create_chat_session(
        scope="task_refine",
        source="tasks",
        source_ref=str(task_number),
        title=task.get("title", ""),
    )
    return {"task_number": task_number, "messages": _fetch_chat_history(session_id)}


@app.post("/api/tasks/{task_number}/close")
async def close_task(task_number: int, body: dict = Body(default={})):
    """Mark a task as completed in active-tasks.md."""
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("task", str(task_number), "close", decision_event_id)
    attempt_id = _start_execution_attempt(
        "task",
        str(task_number),
        "close",
        action_step_id=action_step_id,
        metadata={"task_number": task_number},
    )

    close_date = date.today().isoformat()
    new_status = f"completed ({close_date})"
    note = (body.get("note") or "").strip()
    updated_blocks = _set_task_status(task_number, new_status, completion_note=note)
    if not updated_blocks:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="task block not found")
        raise HTTPException(404, f"task #{task_number} block not found in active file")

    updated_task = _get_task_by_number(task_number) or task
    timestamp = datetime.now().strftime("%H:%M")
    try:
        summary_line = _build_task_daily_log_line(updated_task, note)
        entry = f"- {timestamp} | {summary_line}"
    except Exception:
        fallback_detail = note or f"status set to {new_status}"
        entry = (
            f"- {timestamp} | Task #{updated_task.get('number')} "
            f"{updated_task.get('title', '')} — {fallback_detail}"
        )
    daily_file, daily_inserted = _append_daily_log_completed(entry)
    sync_message = (
        f"Dashboard closed Task #{task_number} as {new_status}. "
        f"Re-read ~/.claude/eng-buddy/tasks/active-tasks.md and do not treat it as active."
    )
    if note:
        sync_message += f" Close note: {note}"
    _queue_claude_sync_event(sync_message)

    _record_stat("tasks_closed")
    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"updated_blocks": updated_blocks, "daily_log_file": str(daily_file)},
    )
    _finish_execution_attempt(attempt_id, "completed", output=entry)
    return {
        "task_number": task_number,
        "status": new_status,
        "updated_blocks": updated_blocks,
        "note": note,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
        "daily_log_file": str(daily_file),
        "daily_log_entry": entry,
        "daily_log_inserted": daily_inserted,
    }


@app.post("/api/tasks/{task_number}/write-jira")
async def write_task_to_jira(task_number: int, body: dict = Body(default={})):
    """Post a task update to Jira using the first linked key unless overridden."""
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("task", str(task_number), "write-jira", decision_event_id)
    attempt_id = _start_execution_attempt(
        "task",
        str(task_number),
        "write-jira",
        action_step_id=action_step_id,
        metadata={"task_number": task_number},
    )

    jira_keys = _task_jira_keys(task)
    if not jira_keys:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="no Jira key found")
        raise HTTPException(400, "no Jira key found in task title/description")

    requested_key = (body.get("issue_key") or "").strip().upper()
    issue_key = requested_key if requested_key else jira_keys[0]
    if issue_key not in jira_keys:
        jira_keys_csv = ", ".join(jira_keys)
        raise HTTPException(400, f"issue_key must be one of: {jira_keys_csv}")

    note = (body.get("note") or "").strip()
    prompt = (
        "Use Atlassian MCP jira_add_comment.\n"
        f"Issue key: {issue_key}\n"
        "Create a concise status update comment from this task context.\n"
        "If user_note is present, include it directly.\n"
        "Comment format: status, progress, blockers, next step.\n\n"
        f"Task #{task['number']}: {task.get('title', '')}\n"
        f"Task status: {task.get('status', 'unknown')}\n"
        f"Priority: {task.get('priority', 'unknown')}\n"
        f"Description:\n{task.get('description', '')}\n\n"
        f"user_note: {note or '(none)'}\n\n"
        'Return ONLY JSON: {"issue_key":"...", "comment":"...", "result":"posted"}'
    )

    result = _run_claude_print(prompt, timeout=75)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Jira write failed: {result.stderr[:200]}")

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    payload = parsed if isinstance(parsed, dict) else {"raw": result.stdout.strip()[:500]}
    _record_stat("tasks_jira_updates")
    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"issue_key": issue_key, "result": payload},
    )
    _finish_execution_attempt(attempt_id, "completed", output=json.dumps(payload))
    return {
        "task_number": task_number,
        "issue_key": issue_key,
        "output": payload,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/tasks/{task_number}/daily-log")
async def save_task_to_daily_log(task_number: int, body: dict = Body(default={})):
    """Append a task update to today's daily log file."""
    task = _get_task_by_number(task_number)
    if not task:
        raise HTTPException(404, f"task #{task_number} not found")

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("task", str(task_number), "daily-log", decision_event_id)
    attempt_id = _start_execution_attempt(
        "task",
        str(task_number),
        "daily-log",
        action_step_id=action_step_id,
        metadata={"task_number": task_number},
    )

    now = datetime.now()
    note = (body.get("note") or "").strip()
    detail = note if note else f"status: {task.get('status', 'unknown')}"
    entry = (
        f"- {now.strftime('%H:%M')} | "
        f"Task #{task['number']} {task.get('title', '')} — {detail}"
    )

    daily_file, inserted = _append_daily_log_completed(entry)
    _record_stat("tasks_logged_daily")
    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"daily_file": str(daily_file), "inserted": inserted},
    )
    _finish_execution_attempt(attempt_id, "completed", output=entry)
    return {
        "task_number": task_number,
        "daily_file": str(daily_file),
        "entry": entry,
        "inserted": inserted,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }

@app.post("/api/cards/{card_id}/hold")
async def hold_card(card_id: int):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET status = 'held' WHERE id = ?", [card_id]
        )
        conn.commit()
        return {"id": card_id, "status": "held"}
    finally:
        conn.close()

@app.post("/api/cards/{card_id}/status")
async def update_card_status(card_id: int, body: dict):
    allowed = {"pending", "held", "approved", "completed", "failed"}
    new_status = body.get("status")
    if new_status not in allowed:
        raise HTTPException(400, f"status must be one of {allowed}")
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET status = ? WHERE id = ?", [new_status, card_id]
        )
        conn.commit()
        return {"id": card_id, "status": new_status}
    finally:
        conn.close()


@app.post("/api/cards/{card_id}/decision")
async def record_card_decision(card_id: int, body: dict = Body(...)):
    conn = get_db()
    try:
        row = conn.execute("SELECT id, source, summary FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    action = body.get("action", "")
    decision = body.get("decision", "")
    rationale = body.get("rationale", "")
    metadata = {
        "card_id": card_id,
        "source": card.get("source", ""),
        "summary": card.get("summary", ""),
    }
    result = _record_decision("card", str(card_id), action, decision, rationale=rationale, metadata=metadata)
    return {
        "card_id": card_id,
        "action": _normalize_action_name(action),
        "decision": (decision or "").strip().lower(),
        **result,
    }


@app.post("/api/suggestions/{card_id}/deny")
async def deny_suggestion(card_id: int, body: dict = Body(default={})):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
        if card.get("source") != SUGGESTION_SOURCE:
            raise HTTPException(400, "card is not a suggestion")
        if card.get("status") != "pending":
            raise HTTPException(400, "only pending suggestions can be denied")
        conn.execute("UPDATE cards SET status = 'held' WHERE id = ?", [card_id])
        conn.commit()
    finally:
        conn.close()

    _stale_sources.add(SUGGESTION_SOURCE)
    return {"card_id": card_id, "status": "held"}


@app.post("/api/suggestions/{card_id}/approve")
async def approve_suggestion(card_id: int, body: dict = Body(default={})):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
        if card.get("source") != SUGGESTION_SOURCE:
            raise HTTPException(400, "card is not a suggestion")
        if card.get("status") != "pending":
            raise HTTPException(400, "only pending suggestions can be approved")
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "approve-suggestion", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "approve-suggestion",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": SUGGESTION_SOURCE},
    )

    metadata = _card_analysis_metadata(card)
    try:
        task_number = _append_task_from_suggestion(card, metadata)
        automation_draft_file = None
        if metadata.get("category") == "automation":
            automation_draft_file = _append_automation_draft(card, metadata, task_number)

        sync_message = (
            f"Dashboard approved suggestion #{card_id} and created Task #{task_number}. "
            f"Re-read ~/.claude/eng-buddy/tasks/active-tasks.md before planning further work."
        )
        if automation_draft_file:
            sync_message += f" Automation draft saved to {automation_draft_file}."
        _queue_claude_sync_event(sync_message)

        conn = get_db()
        try:
            execution_result = {
                "task_number": task_number,
                "automation_draft_file": automation_draft_file,
            }
            conn.execute(
                """UPDATE cards
                   SET status = 'completed',
                       section = 'no-action',
                       execution_status = 'completed',
                       execution_result = ?,
                       executed_at = datetime('now')
                   WHERE id = ?""",
                [json.dumps(execution_result), card_id],
            )
            conn.commit()
        finally:
            conn.close()
        _mark_action_step_status(
            action_step_id,
            "executed",
            payload={"task_number": task_number, "automation_draft_file": automation_draft_file},
        )
        _finish_execution_attempt(
            attempt_id,
            "completed",
            output=json.dumps({"task_number": task_number, "automation_draft_file": automation_draft_file}),
        )
        _record_stat("suggestions_approved")
        _stale_sources.add(SUGGESTION_SOURCE)
        return {
            "card_id": card_id,
            "status": "completed",
            "task_number": task_number,
            "automation_draft_file": automation_draft_file,
            "decision_event_id": decision_event_id,
            "action_step_id": action_step_id,
        }
    except Exception as exc:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=str(exc))
        raise


@app.get("/api/cards/{card_id}/timeline")
async def get_card_timeline(card_id: int, limit: int = 500):
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
    finally:
        conn.close()

    limit = max(1, min(int(limit), 2000))
    entity_id = str(card_id)
    _ensure_audit_schema()
    conn = get_db()
    try:
        chat_rows = conn.execute(
            """SELECT m.id AS item_id,
                      'chat' AS kind,
                      m.created_at AS happened_at,
                      s.scope AS scope,
                      m.role AS role,
                      m.content AS content
               FROM chat_messages m
               JOIN chat_sessions s ON s.id = m.session_id
               WHERE s.source_ref = ?
                 AND s.scope LIKE 'card_%'
               ORDER BY m.id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
        decision_rows = conn.execute(
            """SELECT de.id AS item_id,
                      'decision' AS kind,
                      de.created_at AS happened_at,
                      s.action_name AS action_name,
                      de.decision AS decision,
                      de.rationale AS rationale
               FROM decision_events de
               LEFT JOIN action_steps s ON s.id = de.action_step_id
               WHERE de.entity_type = 'card' AND de.entity_id = ?
               ORDER BY de.id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
        attempt_rows = conn.execute(
            """SELECT id AS item_id,
                      'execution' AS kind,
                      started_at AS happened_at,
                      action_name,
                      status,
                      output,
                      error,
                      finished_at
               FROM execution_attempts
               WHERE entity_type = 'card' AND entity_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            [entity_id, limit],
        ).fetchall()
    finally:
        conn.close()

    combined = [dict(r) for r in chat_rows] + [dict(r) for r in decision_rows] + [dict(r) for r in attempt_rows]
    combined.sort(key=lambda item: (item.get("happened_at") or "", item.get("item_id") or 0), reverse=True)
    return {"card_id": card_id, "timeline": combined[:limit]}


@app.post("/api/cards/{card_id}/close")
async def close_card(card_id: int, body: dict = Body(default={})):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "close", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "close",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": card.get("source", "")},
    )

    note = (body.get("note") or "").strip()
    close_text = note or "closed from dashboard card"
    timestamp = datetime.now().strftime("%H:%M")
    entry = f"- {timestamp} | Card #{card_id} [{card.get('source', '')}] {card.get('summary', '')} — {close_text}"
    daily_file, inserted = _append_daily_log_completed(entry)

    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET status = 'completed', section = 'no-action' WHERE id = ?",
            [card_id],
        )
        conn.commit()
    finally:
        conn.close()

    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"daily_file": str(daily_file), "inserted": inserted},
    )
    _finish_execution_attempt(attempt_id, "completed", output=entry)
    return {
        "card_id": card_id,
        "status": "completed",
        "daily_file": str(daily_file),
        "entry": entry,
        "inserted": inserted,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/cards/{card_id}/write-jira")
async def write_card_to_jira(card_id: int, body: dict = Body(default={})):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "write-jira", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "write-jira",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": card.get("source", "")},
    )

    jira_keys = _card_jira_keys(card)
    if not jira_keys:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="no Jira key found")
        raise HTTPException(400, "no Jira key found in card summary/context/actions")

    issue_key = ((body.get("issue_key") or "").strip().upper() or jira_keys[0])
    if issue_key not in jira_keys:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="issue key mismatch")
        raise HTTPException(400, f"issue_key must be one of: {', '.join(jira_keys)}")

    note = (body.get("note") or "").strip()
    prompt = (
        "Use Atlassian MCP jira_add_comment.\n"
        f"Issue key: {issue_key}\n"
        "Create a concise status update from this card context.\n"
        "If user_note is present, include it directly.\n"
        "Comment format: status, progress, blockers, next step.\n\n"
        f"Card #{card_id}\n"
        f"Source: {card.get('source', '')}\n"
        f"Summary: {card.get('summary', '')}\n"
        f"Context: {card.get('context_notes', '')}\n"
        f"Draft response: {card.get('draft_response', '')}\n\n"
        f"user_note: {note or '(none)'}\n\n"
        'Return ONLY JSON: {"issue_key":"...", "comment":"...", "result":"posted"}'
    )
    result = _run_claude_print(prompt, timeout=75)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Jira write failed: {result.stderr[:200]}")

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    payload = parsed if isinstance(parsed, dict) else {"raw": result.stdout.strip()[:500]}
    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"issue_key": issue_key, "result": payload},
    )
    _finish_execution_attempt(attempt_id, "completed", output=json.dumps(payload))
    return {
        "card_id": card_id,
        "issue_key": issue_key,
        "output": payload,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/cards/{card_id}/daily-log")
async def save_card_to_daily_log(card_id: int, body: dict = Body(default={})):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "daily-log", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "daily-log",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": card.get("source", "")},
    )

    note = (body.get("note") or "").strip()
    timestamp = datetime.now().strftime("%H:%M")
    entry = (
        f"- {timestamp} | Card #{card_id} [{card.get('source', '')}] "
        f"{card.get('summary', '')} — {note or 'logged from card'}"
    )
    daily_file, inserted = _append_daily_log_completed(entry)
    _mark_action_step_status(
        action_step_id,
        "executed",
        payload={"daily_file": str(daily_file), "inserted": inserted},
    )
    _finish_execution_attempt(attempt_id, "completed", output=entry)
    return {
        "card_id": card_id,
        "daily_file": str(daily_file),
        "entry": entry,
        "inserted": inserted,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }

@app.post("/api/cards/{card_id}/send-slack")
async def send_slack_draft(card_id: int, body: dict = Body(default={})):
    """Send the draft response to Slack via MCP."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "send-draft", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "send-draft",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": "slack"},
    )

    draft = card.get("draft_response", "")
    if not draft:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="no draft response")
        raise HTTPException(400, "no draft response")

    actions = json.loads(card.get("proposed_actions") or "[]")
    channel = ""
    thread_ts = ""
    for a in actions:
        channel = a.get("channel_id", channel)
        thread_ts = a.get("thread_ts", thread_ts)

    if not channel:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="no channel info in card")
        raise HTTPException(400, "no channel info in card")

    prompt = (
        f"Use the Slack MCP slack_reply_to_thread tool. "
        f"Channel: {channel}, thread_ts: {thread_ts}, "
        f"text: {json.dumps(draft)}"
    )
    result = _run_claude_print(prompt, timeout=30)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Slack send failed: {result.stderr[:200]}")

    conn = get_db()
    conn.execute(
        "UPDATE cards SET status = 'completed', responded = 1, section = 'no-action' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    _record_stat("drafts_sent")
    _mark_action_step_status(action_step_id, "executed")
    _finish_execution_attempt(attempt_id, "completed", output=result.stdout[:2000])
    return {
        "status": "sent",
        "output": result.stdout[:500],
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/cards/{card_id}/send-email")
async def send_email_draft(card_id: int, body: dict = Body(default={})):
    """Send the draft email response via Gmail MCP."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "send-draft", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "send-draft",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": "gmail"},
    )

    draft = card.get("draft_response", "")
    if not draft:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="no draft response")
        raise HTTPException(400, "no draft response")

    actions = json.loads(card.get("proposed_actions") or "[]")
    thread_id = ""
    to_email = ""
    subject = ""
    for a in actions:
        thread_id = a.get("thread_id", thread_id)
        to_email = a.get("to_email", to_email)
        subject = a.get("subject", subject)

    prompt = (
        f"Use the Gmail MCP send_email tool to reply. "
        f"To: {to_email}, Subject: Re: {subject}, "
        f"Body: {json.dumps(draft)}, "
        f"threadId: {thread_id}"
    )
    result = _run_claude_print(prompt, timeout=30)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Email send failed: {result.stderr[:200]}")

    conn = get_db()
    conn.execute(
        "UPDATE cards SET status = 'completed', responded = 1, section = 'no-action' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    _record_stat("drafts_sent")
    _mark_action_step_status(action_step_id, "executed")
    _finish_execution_attempt(attempt_id, "completed", output=result.stdout[:2000])
    return {
        "status": "sent",
        "output": result.stdout[:500],
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/cards/{card_id}/gmail-analyze")
async def analyze_gmail_card(card_id: int, body: dict = Body(default={})):
    """Generate Gmail-specific category, label, and draft suggestions."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    include_labels = bool(body.get("include_labels", True))
    include_draft = bool(body.get("include_draft", True))
    replace_draft = bool(body.get("replace_draft", False))

    prompt = _build_gmail_analysis_prompt(card, include_labels=include_labels, include_draft=include_draft)
    result = _run_claude_print(prompt, timeout=60)
    if result.returncode != 0:
        raise HTTPException(502, f"Gmail analysis failed: {result.stderr[:200]}")

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    normalized = _normalize_gmail_analysis(parsed)
    metadata = _card_analysis_metadata(card)

    if not include_labels:
        normalized["suggested_labels"] = metadata.get("gmail_suggested_labels", [])
        normalized["detected_category"] = metadata.get("gmail_detected_category", normalized["detected_category"])
        normalized["reasoning"] = normalized["reasoning"] or str(metadata.get("gmail_label_reasoning", "")).strip()
    if not include_draft:
        normalized["suggested_draft"] = str(card.get("draft_response", "")).strip()

    new_metadata = {
        "gmail_detected_category": normalized["detected_category"],
        "gmail_suggested_labels": normalized["suggested_labels"],
        "gmail_label_reasoning": normalized["reasoning"],
        "gmail_last_analyzed_at": datetime.now(timezone.utc).isoformat(),
    }

    existing_draft = str(card.get("draft_response", "")).strip()
    draft_to_store = None
    if include_draft and normalized["suggested_draft"]:
        if replace_draft or not existing_draft:
            draft_to_store = normalized["suggested_draft"]
        else:
            normalized["suggested_draft"] = existing_draft
    else:
        normalized["suggested_draft"] = existing_draft

    persisted_meta, persisted_draft = _persist_card_analysis(card_id, new_metadata, draft_response=draft_to_store)
    return {
        "card_id": card_id,
        "detected_category": persisted_meta.get("gmail_detected_category", normalized["detected_category"]),
        "suggested_labels": persisted_meta.get("gmail_suggested_labels", normalized["suggested_labels"]),
        "reasoning": persisted_meta.get("gmail_label_reasoning", normalized["reasoning"]),
        "draft_response": persisted_draft or "",
    }


@app.post("/api/cards/{card_id}/gmail-auto-label")
async def auto_label_gmail_card(card_id: int, body: dict = Body(default={})):
    """Use Gmail MCP to create/apply suggested labels to the email."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "gmail-auto-label", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "gmail-auto-label",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": "gmail"},
    )

    meta = _card_analysis_metadata(card)
    labels = meta.get("gmail_suggested_labels", [])
    if not labels:
        prompt = _build_gmail_analysis_prompt(card, include_labels=True, include_draft=False)
        analysis_result = _run_claude_print(prompt, timeout=60)
        if analysis_result.returncode != 0:
            _mark_action_step_status(action_step_id, "failed")
            _finish_execution_attempt(attempt_id, "failed", error=analysis_result.stderr[:500])
            raise HTTPException(502, f"Gmail analysis failed: {analysis_result.stderr[:200]}")
        parsed = _extract_balanced_json(analysis_result.stdout.strip(), "{")
        analysis = _normalize_gmail_analysis(parsed)
        labels = analysis["suggested_labels"]
        meta, _ = _persist_card_analysis(
            card_id,
            {
                "gmail_detected_category": analysis["detected_category"],
                "gmail_suggested_labels": labels,
                "gmail_label_reasoning": analysis["reasoning"],
                "gmail_last_analyzed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    details = _gmail_card_details(card)
    label_json = json.dumps(labels)
    search_query = f'from:{details["to_email"] or details["sender"]} subject:"{details["subject"]}" newer_than:30d'
    prompt = (
        "Use the Gmail MCP to create and apply Gmail labels to a message.\n"
        f"Labels to apply: {label_json}\n"
        f"Sender: {details['sender']}\n"
        f"Subject: {details['subject']}\n"
        f"Known message_id: {details['message_id'] or '(none)'}\n"
        f"Known thread_id: {details['thread_id'] or '(none)'}\n\n"
        "Steps:\n"
        "1. Call get_or_create_label for each label and collect the label IDs.\n"
        "2. If message_id is available, call modify_email on that message_id with addLabelIds set to those IDs.\n"
        f"3. Otherwise, call search_emails with query {json.dumps(search_query)} and pick the most relevant recent message.\n"
        "4. Call modify_email on the chosen message_id with addLabelIds set to those IDs.\n"
        'Return ONLY JSON: {"status":"labeled","labels":["..."],"message_id":"..."}'
    )
    result = _run_claude_print(prompt, timeout=60)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Gmail auto-label failed: {result.stderr[:200]}")

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    payload = parsed if isinstance(parsed, dict) else {"status": "unknown", "raw": result.stdout[:500]}
    applied_labels = payload.get("labels") if isinstance(payload.get("labels"), list) else labels
    _persist_card_analysis(
        card_id,
        {
            "gmail_applied_labels": applied_labels,
            "gmail_last_labeled_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    _record_stat("gmail_labels_applied")
    _mark_action_step_status(action_step_id, "executed", payload=payload)
    _finish_execution_attempt(attempt_id, "completed", output=json.dumps(payload))
    return {
        "card_id": card_id,
        "status": payload.get("status", "labeled"),
        "labels": applied_labels,
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


@app.post("/api/cards/{card_id}/archive-email")
async def archive_gmail_card(card_id: int, body: dict = Body(default={})):
    """Archive a Gmail card by removing the INBOX label on the matching message."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "archive-email", decision_event_id)
    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "archive-email",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": "gmail"},
    )

    details = _gmail_card_details(card)
    search_query = f'from:{details["to_email"] or details["sender"]} subject:"{details["subject"]}" newer_than:30d'
    prompt = (
        "Use the Gmail MCP to archive a Gmail conversation by removing the INBOX label.\n"
        f"Sender: {details['sender']}\n"
        f"Subject: {details['subject']}\n"
        f"Known message_id: {details['message_id'] or '(none)'}\n"
        f"Known thread_id: {details['thread_id'] or '(none)'}\n\n"
        "Prefer archiving the whole visible thread, not just one message.\n"
        "If thread_id is available, call search_emails with the query below, collect the matching recent inbox message ids for this conversation, "
        "and call batch_modify_emails with removeLabelIds ['INBOX'] for all of them.\n"
        "If you only find one matching message, archive that one.\n"
        f"If thread_id is unavailable, call search_emails with query {json.dumps(search_query)} and archive the best recent match.\n"
        'Return ONLY JSON: {"status":"archived","message_id":"...","message_ids":["..."]}'
    )
    result = _run_claude_print(prompt, timeout=45)
    if result.returncode != 0:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error=result.stderr[:500])
        raise HTTPException(502, f"Gmail archive failed: {result.stderr[:200]}")

    conn = get_db()
    try:
        related_ids = _find_related_gmail_card_ids(conn, card)
        placeholders = ",".join("?" for _ in related_ids)
        conn.execute(
            f"UPDATE cards SET status = 'completed', section = 'no-action' WHERE id IN ({placeholders})",
            related_ids,
        )
        conn.commit()
    finally:
        conn.close()

    parsed = _extract_balanced_json(result.stdout.strip(), "{")
    payload = parsed if isinstance(parsed, dict) else {"status": "archived", "raw": result.stdout[:500]}
    _record_stat("gmail_archived")
    _mark_action_step_status(action_step_id, "executed", payload=payload)
    _finish_execution_attempt(attempt_id, "completed", output=json.dumps(payload))
    return {
        "card_id": card_id,
        "status": payload.get("status", "archived"),
        "decision_event_id": decision_event_id,
        "action_step_id": action_step_id,
    }


async def card_event_generator():
    """Yield new cards as SSE events with optional source cache invalidation."""
    conn = get_db()
    try:
        row = conn.execute("SELECT MAX(id) FROM cards").fetchone()[0]
        last_id = row or 0
    finally:
        conn.close()

    while True:
        await asyncio.sleep(10)

        # Flush explicit stale-source notifications (triggered by pollers).
        if _stale_sources:
            sources = list(_stale_sources)
            _stale_sources.clear()
            for src in sources:
                yield f"event: cache-invalidate\ndata: {json.dumps({'source': src})}\n\n"

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM cards WHERE id > ? ORDER BY id ASC", [last_id]
            ).fetchall()
            seen_sources = set()
            for row in rows:
                card = _row_to_card(row)
                last_id = card["id"]
                seen_sources.add(card.get("source", ""))
                yield f"data: {json.dumps(card)}\n\n"
            for src in seen_sources:
                yield f"event: cache-invalidate\ndata: {json.dumps({'source': src})}\n\n"
        finally:
            conn.close()

@app.get("/api/events")
async def card_events():
    return StreamingResponse(
        card_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@app.websocket("/ws/execute/{card_id}")
async def execute_card(websocket: WebSocket, card_id: int):
    await websocket.accept()
    decision_event_id = int(websocket.query_params.get("decision_event_id", "0") or "0")

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            await websocket.send_text("ERROR: card not found")
            await websocket.close()
            return
        card = dict(row)
    finally:
        conn.close()

    try:
        action_step_id = _require_approved_decision("card", str(card_id), "execute", decision_event_id)
    except HTTPException as exc:
        await websocket.send_text(f"ERROR: {exc.detail}")
        await websocket.close()
        return

    # Build context prompt
    proposed = card.get("proposed_actions") or "[]"
    summary = card.get("summary", "")
    source = card.get("source", "")
    metadata = _card_analysis_metadata(card)
    prompt = (
        f"You are eng-buddy executing a task from the queue.\n\n"
        f"Source: {source}\n"
        f"Summary: {summary}\n\n"
        f"Execute these proposed actions:\n{proposed}\n\n"
        f"Use the available MCPs. Report each action as you complete it. "
        f"If an action would send a message to a user, show the full text first "
        f"and wait for confirmation before sending."
    )

    # Write prompt to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    # Spawn claude in PTY
    proc = ptyprocess.PtyProcess.spawn(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        dimensions=(50, 220),
        env=_claude_env(),
    )

    # Mark card as running
    conn = get_db()
    conn.execute(
        "UPDATE cards SET execution_status = 'running', status = 'approved' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    attempt_id = _start_execution_attempt(
        "card",
        str(card_id),
        "execute",
        action_step_id=action_step_id,
        metadata={"card_id": card_id, "source": source or "unknown"},
    )
    _mark_action_step_status(action_step_id, "approved")

    output_chunks = []
    user_inputs = []

    # Read PTY output and stream over WebSocket
    loop = asyncio.get_event_loop()

    def read_pty():
        while True:
            try:
                data = proc.read(1024)
                output_chunks.append(data.decode("utf-8", errors="replace"))
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(data.decode("utf-8", errors="replace")),
                    loop
                )
            except EOFError:
                break
            except Exception:
                break

    thread = threading.Thread(target=read_pty, daemon=True)
    thread.start()

    # Handle input from browser -> PTY (for interactive sessions)
    try:
        while proc.isalive():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                if msg and msg.strip():
                    user_inputs.append(msg.strip())
                proc.write(msg.encode())
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
    finally:
        thread.join(timeout=2)
        proc.close()
        os.unlink(prompt_file)

        # Save execution result
        full_output = "".join(output_chunks)
        conn = get_db()
        conn.execute(
            """UPDATE cards SET
               execution_status = 'completed',
               execution_result = ?,
               executed_at = datetime('now')
               WHERE id = ?""",
            [full_output, card_id]
        )
        conn.commit()
        conn.close()

        exec_session_id = _get_or_create_chat_session(
            scope="card_execute",
            source=source or "unknown",
            source_ref=str(card_id),
            title=summary,
        )
        if user_inputs:
            _append_chat_message(
                exec_session_id,
                "user",
                "\n".join(user_inputs),
                metadata={"card_id": card_id, "source": source or "unknown", "execution": True},
            )
        _append_chat_message(
            exec_session_id,
            "assistant",
            full_output,
            metadata={"card_id": card_id, "source": source or "unknown", "execution": True},
        )
        _trigger_chat_learning(exec_session_id)
        _mark_action_step_status(action_step_id, "executed")
        _finish_execution_attempt(attempt_id, "completed", output=full_output[:20000])

        await websocket.send_text("\n\n[EXECUTION COMPLETE]")
        await websocket.close()

@app.post("/api/cards/{card_id}/refine")
async def refine_card(card_id: int, body: dict = Body(...)):
    """Single-turn chat about a card. Returns Claude's response."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    user_message = body.get("message", "")
    history = body.get("history")

    proposed = card.get("proposed_actions") or "[]"
    summary = card.get("summary", "")
    source = card.get("source", "")
    session_id = _get_or_create_chat_session(
        scope="card_refine",
        source=source or "unknown",
        source_ref=str(card_id),
        title=summary,
    )
    if isinstance(history, list) and history:
        history_turns = history
    else:
        history_turns = _history_to_turns(_fetch_chat_history(session_id))

    if source == SUGGESTION_SOURCE:
        system_context = (
            f"You are eng-buddy helping refine a dashboard suggestion before approval.\n\n"
            f"Source: {source}\nSummary: {summary}\n"
            f"Category: {metadata.get('category', 'unknown')}\n"
            f"Why now: {card.get('context_notes', '')}\n"
            f"Current proposed actions:\n{proposed}\n\n"
            f"Help sharpen the recommendation, evidence, and next step. "
            f"When the user is satisfied, they will approve it to create follow-up artifacts."
        )
    else:
        system_context = (
            f"You are eng-buddy helping to refine a task before execution.\n\n"
            f"Source: {source}\nSummary: {summary}\n"
            f"Current proposed actions:\n{proposed}\n\n"
            f"The user wants to refine or adjust these actions. "
            f"When they are satisfied, they will click Approve to execute."
        )

    conversation = system_context + "\n\n"
    for turn in history_turns:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        conversation += f"{role.upper()}: {content}\n"
    conversation += f"USER: {user_message}\n"

    result = _run_claude_print(conversation, timeout=60)

    response_text = result.stdout.strip()

    _append_chat_message(
        session_id,
        "user",
        user_message,
        metadata={"card_id": card_id, "source": source or "unknown"},
    )
    _append_chat_message(
        session_id,
        "assistant",
        response_text,
        metadata={"card_id": card_id, "source": source or "unknown"},
    )
    try:
        _record_decision(
            "card",
            str(card_id),
            "refine",
            "refined",
            rationale=user_message,
            metadata={"card_id": card_id, "source": source or "unknown"},
        )
    except HTTPException:
        pass
    _sync_card_refinement_history(card_id, session_id)
    _trigger_chat_learning(session_id)

    # If Claude updated proposed actions, parse and save them
    json_match = re.search(r'```json\n(\[.*?\])\n```', response_text, re.DOTALL)
    if json_match:
        try:
            new_actions = json.loads(json_match.group(1))
            conn = get_db()
            conn.execute(
                "UPDATE cards SET proposed_actions = ? WHERE id = ?",
                [json.dumps(new_actions), card_id]
            )
            conn.commit()
            conn.close()
        except json.JSONDecodeError:
            pass

    return {"response": response_text}


@app.get("/api/cards/{card_id}/chat-history")
async def get_card_chat_history(card_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT id, source, summary FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    session_id = _get_or_create_chat_session(
        scope="card_refine",
        source=card.get("source", "unknown"),
        source_ref=str(card_id),
        title=card.get("summary", ""),
    )
    return {"card_id": card_id, "messages": _fetch_chat_history(session_id)}


@app.post("/api/chat-sessions/{session_id}/ingest-transcript")
async def ingest_chat_session_transcript(session_id: int, body: dict = Body(...)):
    """Ingest a terminal transcript file into a persisted chat session."""
    session = _fetch_chat_session(session_id)
    if not session:
        raise HTTPException(404, "chat session not found")

    transcript_path = (body.get("path") or "").strip()
    cleanup = bool(body.get("cleanup", False))
    if not transcript_path:
        raise HTTPException(400, "path is required")

    path = Path(transcript_path).expanduser()
    if not path.exists():
        raise HTTPException(404, "transcript file not found")

    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = False
    max_chars = 250000
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    if text.strip():
        _append_chat_message(
            session_id,
            "assistant",
            text,
            metadata={
                "source": session.get("source", "unknown"),
                "scope": session.get("scope", "unknown"),
                "transcript": True,
                "path": str(path),
                "truncated": truncated,
            },
        )
        _trigger_chat_learning(session_id)

    if cleanup:
        try:
            path.unlink()
        except OSError:
            pass

    return {
        "session_id": session_id,
        "ingested_chars": len(text),
        "truncated": truncated,
        "cleanup": cleanup,
    }

@app.get("/api/settings")
async def get_settings():
    global TERMINAL_APP
    settings = _load_settings()
    TERMINAL_APP = settings["terminal"]
    return settings

@app.post("/api/settings")
async def update_settings(body: dict):
    global TERMINAL_APP
    settings = _load_settings()
    if "terminal" in body:
        allowed = {"Terminal", "Warp", "iTerm", "Alacritty", "kitty"}
        if body["terminal"] not in allowed:
            raise HTTPException(400, f"terminal must be one of {allowed}")
        settings["terminal"] = body["terminal"]
    if "macos_notifications" in body:
        settings["macos_notifications"] = bool(body["macos_notifications"])
    if "theme" in body:
        allowed_themes = {"midnight-ops", "soft-kitty", "neon-dreams"}
        if body["theme"] not in allowed_themes:
            raise HTTPException(400, f"theme must be one of {allowed_themes}")
        settings["theme"] = body["theme"]
    if "mode" in body:
        allowed_modes = {"dark", "light"}
        if body["mode"] not in allowed_modes:
            raise HTTPException(400, f"mode must be one of {allowed_modes}")
        settings["mode"] = body["mode"]
    settings = _save_settings(settings)
    TERMINAL_APP = settings["terminal"]
    return settings


def _launch_terminal_session(
    context: str,
    launcher_prefix: str = "open-session-",
    chat_session_id: int = None,
):
    """Create a launcher script and open a terminal with an interactive Claude session."""
    # Isolate launcher scripts so startup/task restore logic cannot confuse them
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    for stale in LAUNCHER_DIR.glob(f"{launcher_prefix}*.sh"):
        try:
            if (datetime.now() - datetime.fromtimestamp(stale.stat().st_mtime)).days >= 1:
                stale.unlink()
        except OSError:
            pass

    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=launcher_prefix,
        suffix=".sh",
        delete=False,
        dir=LAUNCHER_DIR,
    ) as f:
        f.write("#!/bin/bash\n")
        f.write("set +e\n")
        f.write("unset CLAUDECODE\n")
        f.write("export PATH=\"/opt/homebrew/bin:/usr/local/bin:$PATH\"\n")
        f.write("PROMPT=$(cat <<'ENGBUDDY_EOF'\n")
        f.write(context)
        f.write("\nENGBUDDY_EOF\n)\n")
        if chat_session_id is not None:
            transcript_dir = RUNTIME_DIR / "transcripts"
            transcript_dir.mkdir(parents=True, exist_ok=True)
            transcript_file = transcript_dir / (
                f"session-{launcher_prefix.rstrip('-')}-{chat_session_id}-{int(datetime.now().timestamp())}.log"
            )
            f.write(f'TRANSCRIPT_FILE="{transcript_file}"\n')
            f.write('script -q "$TRANSCRIPT_FILE" claude --dangerously-skip-permissions "$PROMPT"\n')
            f.write("python3 - \"$TRANSCRIPT_FILE\" <<'ENGBUDDY_INGEST_PY'\n")
            f.write("import json, sys, urllib.request\n")
            f.write(f"session_id = {int(chat_session_id)}\n")
            f.write("path = sys.argv[1]\n")
            f.write("payload = json.dumps({'path': path, 'cleanup': True}).encode('utf-8')\n")
            f.write("url = f'http://127.0.0.1:7777/api/chat-sessions/{session_id}/ingest-transcript'\n")
            f.write("req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')\n")
            f.write("try:\n")
            f.write("    urllib.request.urlopen(req, timeout=20).read()\n")
            f.write("except Exception:\n")
            f.write("    pass\n")
            f.write("ENGBUDDY_INGEST_PY\n")
        else:
            f.write('claude --dangerously-skip-permissions "$PROMPT"\n')
        launcher = f.name

    os.chmod(launcher, 0o755)

    # Open in configured terminal
    if TERMINAL_APP == "Warp":
        subprocess.Popen(["open", "-a", "Warp", launcher])
    elif TERMINAL_APP == "iTerm":
        script = (
            f'tell application "iTerm"\n'
            f'create window with default profile command "{launcher}"\n'
            f'activate\nend tell'
        )
        subprocess.Popen(["osascript", "-e", script])
    elif TERMINAL_APP in ("Alacritty", "kitty"):
        subprocess.Popen(["open", "-a", TERMINAL_APP, "--args", "-e", launcher])
    else:
        script = f'tell application "Terminal"\ndo script "{launcher}"\nactivate\nend tell'
        subprocess.Popen(["osascript", "-e", script])

    return launcher

@app.post("/api/cards/{card_id}/open-session")
async def open_session(card_id: int):
    """Spawn a full interactive claude session in a new terminal window."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    proposed = card.get("proposed_actions") or "[]"
    summary = card.get("summary", "")
    source = card.get("source", "")
    metadata = _card_analysis_metadata(card)
    open_session_prompt = str(metadata.get("open_session_prompt", "")).strip()

    if source == SUGGESTION_SOURCE and open_session_prompt:
        context = (
            f"eng-buddy suggestion review\n"
            f"Source: {source}\nSummary: {summary}\n"
            f"Suggestion category: {metadata.get('category', 'unknown')}\n"
            f"Why now: {card.get('context_notes', '')}\n"
            f"Evidence: {json.dumps(metadata.get('evidence', []), indent=2)}\n\n"
            f"{open_session_prompt}\n"
        )
    else:
        context = (
            f"eng-buddy task\n"
            f"Source: {source}\nSummary: {summary}\n"
            f"Proposed actions:\n{proposed}\n\n"
            f"Work through this task with the user step by step."
        )
    session_id = _get_or_create_chat_session(
        scope="card_terminal_session",
        source=source or "unknown",
        source_ref=str(card_id),
        title=summary,
    )
    launcher = _launch_terminal_session(
        context,
        launcher_prefix="open-session-",
        chat_session_id=session_id,
    )

    return {
        "status": "opened",
        "terminal": TERMINAL_APP,
        "launcher": launcher,
        "chat_session_id": session_id,
    }

def _jira_lane_for_status(status: str, status_category: str = ""):
    category = (status_category or "").strip().lower().replace(" ", "_")
    if category in {"done"}:
        return "done"
    if category in {"to_do", "todo"}:
        return "todo"
    if category in {"in_progress", "inprogress"}:
        return "in_progress"

    s = (status or "").strip().lower()
    if any(k in s for k in ("done", "closed", "resolved", "complete", "cancelled", "released")):
        return "done"
    if any(k in s for k in ("to do", "todo", "open", "backlog", "selected", "queued", "pending")):
        return "todo"
    return "in_progress"


def _build_jira_sprint_prompt():
    assignee = JIRA_USER or "currentUser()"
    return (
        "Use Atlassian MCP to fetch the active sprint issues for the Systems board in Jira.\n"
        f"1. Call jira_get_agile_boards with board_name='{JIRA_BOARD_NAME}' and project_key='{JIRA_PROJECT_KEY}'.\n"
        f"2. From the returned boards, choose the board that best matches project '{JIRA_PROJECT_KEY}' and the Systems sprint workflow.\n"
        "3. Call jira_get_sprints_from_board with that board's ID and state='active'.\n"
        f"4. If multiple active sprints exist, prefer the sprint whose name contains '{JIRA_PROJECT_KEY}' or starts with 'SYSTEMS'.\n"
        f"5. Call jira_search with JQL: assignee = \"{assignee}\" AND project = {JIRA_PROJECT_KEY} AND sprint = <selected_sprint_id> ORDER BY status ASC, priority DESC.\n"
        "6. Request fields: key,summary,status,priority,issuetype,labels,updated.\n"
        "Return ONLY a JSON array. Each object must have: key, summary, status, status_category, priority, issue_type, labels, updated. "
        "status_category must match Jira's statusCategory.name if available."
    )


@app.get("/api/jira/sprint")
async def jira_sprint(refresh: bool = False):
    """Fetch current sprint tasks via Claude CLI + Atlassian MCP."""
    import time

    if not refresh and _jira_cache["data"] and (time.time() - _jira_cache["fetched_at"]) < 120:
        return _jira_cache["data"]

    prompt = _build_jira_sprint_prompt()

    try:
        result = _run_claude_print(prompt, timeout=75)
        if result.returncode != 0:
            raise HTTPException(502, f"Jira fetch failed: {result.stderr[:200]}")
        parsed = _extract_balanced_json(result.stdout.strip(), "[")
        issues = parsed if isinstance(parsed, list) else []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Jira fetch failed: {e}")

    board = {"todo": [], "in_progress": [], "done": []}
    by_status = {}
    for issue in issues:
        status = issue.get("status") or "Unknown"
        lane = _jira_lane_for_status(status, issue.get("status_category", ""))
        board[lane].append(issue)
        by_status.setdefault(status, []).append(issue)

    status_order = sorted(
        by_status.keys(),
        key=lambda s: (
            {"todo": 0, "in_progress": 1, "done": 2}.get(
                _jira_lane_for_status(s, by_status[s][0].get("status_category", "")), 3
            ),
            s.lower(),
        ),
    )

    response = {
        "issues": issues,
        "board": board,
        "by_status": by_status,
        "status_order": status_order,
        "total": len(issues),
    }
    _jira_cache["data"] = response
    _jira_cache["fetched_at"] = time.time()
    return response

@app.post("/api/notify")
async def notify(body: dict):
    settings = _load_settings()
    if not settings.get("macos_notifications", False):
        return {"ok": True, "notified": False, "reason": "disabled"}
    msg = _escape_applescript_text(body.get("message", "")[:100])
    title = _escape_applescript_text(body.get("title", "eng-buddy"))
    script = f'display notification "{msg}" with title "{title}" sound name "Glass"'
    subprocess.Popen(["osascript", "-e", script])
    return {"ok": True, "notified": True}


@app.post("/api/cache-invalidate")
async def cache_invalidate(body: dict):
    """Allow pollers to notify the dashboard that a source cache is stale."""
    source = body.get("source")
    if source:
        _stale_sources.add(source)
    return {"ok": True}


@app.post("/api/pollers/{poller_id}/sync")
async def force_sync_poller(poller_id: str):
    """Trigger an immediate poller sync."""
    poller = None
    for p in POLLER_DEFINITIONS:
        if p["id"] == poller_id:
            poller = p
            break
    if not poller:
        raise HTTPException(404, f"unknown poller: {poller_id}")

    # Check if already running
    existing = _running_syncs.get(poller_id)
    if existing and existing.poll() is None:
        return {"status": "already_syncing", "poller": poller_id}

    script_map = {
        "slack": "slack-poller.py",
        "gmail": "gmail-poller.py",
        "calendar": "calendar-poller.py",
        "jira": "jira-poller.py",
    }
    script_name = script_map.get(poller_id)
    if not script_name:
        raise HTTPException(400, f"no script for poller: {poller_id}")

    script_path = ENG_BUDDY_DIR / "bin" / script_name
    if not script_path.exists():
        script_path = RUNTIME_DIR / "bin" / script_name
    if not script_path.exists():
        raise HTTPException(500, f"poller script not found: {script_name}")

    # Clean up finished syncs to avoid accumulating dead Popen objects
    for pid, p in list(_running_syncs.items()):
        if p.poll() is not None:
            del _running_syncs[pid]

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(ENG_BUDDY_DIR),
    )
    _running_syncs[poller_id] = proc

    return {"status": "syncing", "poller": poller_id}


@app.get("/api/briefing")
async def get_briefing(regenerate: bool = False):
    """Generate or return cached morning briefing."""
    from datetime import date, timedelta
    today_date = date.today()
    today = today_date.isoformat()

    try:
        conn = get_db()
    except sqlite3.OperationalError as e:
        return {"error": f"Database unavailable: {e}", "date": today}

    try:
        calendar_meetings = _load_briefing_calendar_meetings(conn, today_date)

        # Check cache
        if not regenerate:
            row = conn.execute(
                "SELECT content FROM briefings WHERE date = ?", [today]
            ).fetchone()
            if row:
                cached = json.loads(row[0])
                if _briefing_meeting_signature(cached.get("meetings")) == _briefing_meeting_signature(calendar_meetings):
                    return cached

        # Gather data for briefing
        pending_cards = conn.execute(
            "SELECT source, section, summary, context_notes, draft_response FROM cards WHERE status = 'pending' ORDER BY timestamp DESC LIMIT 30"
        ).fetchall()

        # Get yesterday's stats
        yesterday = (today_date - timedelta(days=1)).isoformat()
        stats = conn.execute(
            "SELECT metric, SUM(value) FROM stats WHERE date = ? GROUP BY metric", [yesterday]
        ).fetchall()
    except sqlite3.OperationalError as e:
        return {"error": f"Database busy: {e}", "date": today}
    finally:
        conn.close()

    cards_data = [dict(r) for r in pending_cards]
    stats_data = {r[0]: r[1] for r in stats} if stats else {}

    # Build briefing prompt
    sys_path = Path(__file__).parent.parent / "bin"
    sys.path.insert(0, str(sys_path))
    from brain import build_context_prompt

    context = build_context_prompt()
    prompt = f"""{context}

Generate a morning briefing for today ({today}). You have:

PENDING CARDS:
{json.dumps(cards_data, indent=2)}

TODAY'S CALENDAR MEETINGS:
{json.dumps(calendar_meetings, indent=2)}

YESTERDAY'S STATS:
{json.dumps(stats_data, indent=2)}

Return a JSON object with these sections:
{{
  "date": "{today}",
  "meetings": [{{  "time": "HH:MM", "title": "...", "prep": "..." }}],
  "needs_response": [{{"source": "slack|gmail", "summary": "...", "age": "...", "has_draft": true}}],
  "alerts": [{{"summary": "...", "urgency": "high|medium|low"}}],
  "sprint_status": {{"in_progress": 0, "todo": 0, "done": 0, "blockers": []}},
  "cognitive_load": {{"level": "LOW|MODERATE|HIGH|OVERLOADED", "meeting_count": 0, "action_count": 0, "deep_work_window": "HH:MM-HH:MM", "heaviest_block": "HH:MM-HH:MM"}},
  "stats": {{"drafts_sent": 0, "cards_triaged": 0, "time_saved_min": 0, "week_total_triaged": 0}},
  "heads_up": ["stakeholder waiting...", "SLA deadline...", ...],
  "pep_talk": "Personalized encouragement based on workload and recent velocity."
}}

Return ONLY the JSON. No prose."""

    try:
        result = _run_claude_print(prompt, timeout=60)
        if result.returncode != 0:
            briefing = {"error": "Failed to generate briefing", "raw": result.stderr[:500]}
        else:
            parsed = _extract_balanced_json(result.stdout, "{")
            if isinstance(parsed, dict):
                briefing = parsed
            else:
                briefing = {"error": "Failed to generate briefing", "raw": result.stdout[:500]}
    except Exception as e:
        briefing = {"error": str(e)}

    if not briefing.get("error"):
        briefing["date"] = today
        briefing["meetings"] = calendar_meetings
        cognitive_load = briefing.get("cognitive_load")
        if not isinstance(cognitive_load, dict):
            cognitive_load = {}
            briefing["cognitive_load"] = cognitive_load
        cognitive_load["meeting_count"] = len(calendar_meetings)

    # Cache it (non-fatal if DB is busy)
    try:
        conn = get_db()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO briefings (date, content, generated_at) VALUES (?, ?, ?)",
                [today, json.dumps(briefing), datetime.now().isoformat()]
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        pass  # Cache miss is acceptable, briefing still returned

    return briefing


@app.get("/api/filters/suggestions")
async def get_filter_suggestions():
    """Return pending filter suggestions."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM filter_suggestions WHERE status = 'suggest' ORDER BY ignore_count DESC"
        ).fetchall()
        return {"suggestions": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/filters/create")
async def create_gmail_filter(body: dict):
    """Create a Gmail filter via MCP and record it."""
    pattern = body.get("pattern", "")
    label_name = body.get("label", "")
    suggestion_id = body.get("suggestion_id")

    if not pattern or not label_name:
        raise HTTPException(400, "pattern and label required")

    prompt = (
        f"Use the Gmail MCP. First, use get_or_create_label to ensure label '{label_name}' exists. "
        f"Then use create_filter with criteria matching from:{pattern}, "
        f"and action to add label '{label_name}' and skip inbox (removeLabelIds: ['INBOX']). "
        f"Return the filter ID."
    )
    result = _run_claude_print(prompt, timeout=30)

    if suggestion_id:
        conn = get_db()
        conn.execute(
            "UPDATE filter_suggestions SET status = 'created' WHERE id = ?",
            [suggestion_id]
        )
        conn.commit()
        conn.close()

    _record_stat("filters_created")
    return {"status": "created", "output": result.stdout[:500]}


@app.post("/api/filters/dismiss")
async def dismiss_filter_suggestion(body: dict):
    """Dismiss a filter suggestion."""
    suggestion_id = body.get("suggestion_id")
    permanent = body.get("permanent", False)
    conn = get_db()
    status = "never" if permanent else "dismissed"
    conn.execute(
        "UPDATE filter_suggestions SET status = ? WHERE id = ?",
        [status, suggestion_id]
    )
    conn.commit()
    conn.close()
    return {"status": status}


@app.post("/api/cards/{card_id}/dismiss")
async def dismiss_card(card_id: int, body: dict = Body(default={})):
    """Move card to no-action section."""
    decision_event_id = int(body.get("decision_event_id") or 0)
    action_step_id = _require_approved_decision("card", str(card_id), "dismiss", decision_event_id)
    attempt_id = _start_execution_attempt("card", str(card_id), "dismiss", action_step_id=action_step_id)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET section = 'no-action' WHERE id = ?", [card_id]
        )
        conn.commit()

        # Track for adaptive filtering
        row = conn.execute("SELECT source, summary FROM cards WHERE id = ?", [card_id]).fetchone()
        if row and row[0] == "gmail":
            _track_ignored_pattern(conn, row[1])
        _mark_action_step_status(action_step_id, "executed")
        _finish_execution_attempt(attempt_id, "completed", output="dismissed to no-action")
        return {"id": card_id, "section": "no-action"}
    finally:
        conn.close()


def _track_ignored_pattern(conn, summary):
    """Increment ignore count for sender pattern."""
    # Extract sender from summary (format: "Sender: Subject")
    sender = summary.split(":")[0].strip() if ":" in summary else summary[:50]
    row = conn.execute(
        "SELECT id, ignore_count FROM filter_suggestions WHERE pattern = ? AND status IN ('tracking', 'suggest')",
        [sender]
    ).fetchone()
    if row:
        new_count = row[1] + 1
        status = "suggest" if new_count >= 10 else "tracking"
        conn.execute(
            "UPDATE filter_suggestions SET ignore_count = ?, status = ?, suggested_at = CASE WHEN ? = 'suggest' THEN datetime('now') ELSE suggested_at END WHERE id = ?",
            [new_count, status, status, row[0]]
        )
    else:
        conn.execute(
            "INSERT INTO filter_suggestions (source, pattern, ignore_count, status) VALUES ('gmail', ?, 1, 'tracking')",
            [sender]
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Cross-channel resolution helpers
# ---------------------------------------------------------------------------

def _extract_person_name(card: dict) -> str:
    """Extract person name from card summary and proposed_actions."""
    summary = card.get("summary", "")
    # Gmail format: "Name <email>: Subject"
    email_match = re.match(r"^(.+?)\s*<[^>]+>", summary)
    if email_match:
        return email_match.group(1).strip()
    # Slack format: "Name via #channel: text"
    slack_match = re.match(r"^(.+?)\s+via\s+", summary)
    if slack_match:
        return slack_match.group(1).strip()
    # Try proposed_actions for sender info
    actions = card.get("proposed_actions")
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except (json.JSONDecodeError, TypeError):
            actions = []
    if isinstance(actions, list):
        for a in actions:
            sender = a.get("sender", "") or a.get("to_email", "")
            if sender:
                name_match = re.match(r"^(.+?)\s*<", sender)
                if name_match:
                    return name_match.group(1).strip()
                if "@" in sender:
                    return sender.split("@")[0].replace(".", " ").title()
                return sender
    return ""


def _extract_topic_words(card: dict) -> set:
    """Extract meaningful topic words from card summary and context_notes."""
    text = f"{card.get('summary', '')} {card.get('context_notes', '')}"
    text = re.sub(r"<[^>]+>", " ", text)  # remove emails in angle brackets
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)  # remove times
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)  # remove dates
    words = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
    stop = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
            "her", "was", "one", "our", "out", "has", "have", "from", "this", "that",
            "with", "they", "been", "said", "each", "which", "their", "will", "way",
            "about", "many", "then", "them", "would", "like", "into", "just", "than",
            "some", "could", "other", "gmail", "slack", "via", "needs", "response",
            "action", "needed", "noise", "pending", "card"}
    return words - stop


def _person_similarity(name_a: str, name_b: str) -> float:
    """Fuzzy match two person names. Returns 0.0-1.0."""
    if not name_a or not name_b:
        return 0.0
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def _topic_similarity(words_a: set, words_b: set) -> float:
    """Jaccard similarity on word sets. Returns 0.0-1.0."""
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


@app.post("/api/cards/{card_id}/resolve-related")
async def resolve_related_cards(card_id: int):
    """Find and auto-resolve cross-channel cards matching person + topic."""
    conn = get_db()
    try:
        source_row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not source_row:
            raise HTTPException(404, "card not found")
        source_card = _row_to_card(source_row)

        if not source_card.get("responded"):
            return {"resolved": 0, "cards": []}

        source_name = _extract_person_name(source_card)
        source_topics = _extract_topic_words(source_card)
        source_source = source_card.get("source", "")

        if not source_name:
            return {"resolved": 0, "cards": [], "reason": "no person name extracted"}

        needs_sections = ("needs-action", "action-needed", "needs-response", "needs_response")
        placeholders = ",".join("?" for _ in needs_sections)
        candidates = conn.execute(
            f"""SELECT * FROM cards
                WHERE source != ?
                  AND responded = 0
                  AND section IN ({placeholders})
                  AND status = 'pending'""",
            [source_source, *needs_sections],
        ).fetchall()

        resolved = []
        affected_sources = set()

        for row in candidates:
            candidate = _row_to_card(row)
            cand_name = _extract_person_name(candidate)
            cand_topics = _extract_topic_words(candidate)

            person_score = _person_similarity(source_name, cand_name)
            topic_score = _topic_similarity(source_topics, cand_topics)

            if person_score >= 0.8 and topic_score >= 0.3:
                existing_notes = candidate.get("context_notes", "") or ""
                new_notes = f"{existing_notes}\nAuto-resolved: responded via {source_source}".strip()
                conn.execute(
                    """UPDATE cards
                       SET responded = 1, section = 'no-action', classification = 'responded',
                           context_notes = ?
                       WHERE id = ?""",
                    [new_notes, candidate["id"]],
                )
                resolved.append({
                    "id": candidate["id"],
                    "source": candidate.get("source"),
                    "summary": candidate.get("summary", "")[:100],
                    "person_score": round(person_score, 2),
                    "topic_score": round(topic_score, 2),
                })
                affected_sources.add(candidate.get("source", ""))

        if resolved:
            conn.commit()
            for src in affected_sources:
                _stale_sources.add(src)

    finally:
        conn.close()

    return {"resolved": len(resolved), "cards": resolved}


def _record_stat(metric, value=1, details=None):
    """Record a stat to the stats table."""
    from datetime import date
    conn = get_db()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL DEFAULT 0,
                details TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO stats (date, metric, value, details) VALUES (?, ?, ?, ?)",
            [date.today().isoformat(), metric, value, details]
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    reload_enabled = os.environ.get("ENG_BUDDY_DASHBOARD_RELOAD", "").strip().lower() in {"1", "true", "yes"}
    uvicorn.run("server:app", host="127.0.0.1", port=7777, reload=reload_enabled)
