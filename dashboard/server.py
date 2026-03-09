import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
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
DAILY_DIR = ENG_BUDDY_DIR / "daily"
KNOWLEDGE_DIR = ENG_BUDDY_DIR / "knowledge"
PATTERNS_DIR = ENG_BUDDY_DIR / "patterns"
STAKEHOLDERS_DIR = ENG_BUDDY_DIR / "stakeholders"
MEMORY_DIR = ENG_BUDDY_DIR / "memory"
RUNTIME_DIR = ENG_BUDDY_DIR / ".runtime"
LAUNCHER_DIR = RUNTIME_DIR / "launchers"
TERMINAL_APP = os.environ.get("ENG_BUDDY_TERMINAL", "Terminal")
JIRA_USER = os.environ.get("ENG_BUDDY_JIRA_USER", "")

# In-memory cache for Jira sprint data
_jira_cache = {"data": None, "fetched_at": 0}

@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(exist_ok=True)
    migrate()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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

@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/api/health")
async def health():
    return {"status": "ok"}


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
async def get_cards(source: str = None, status: str = "pending", section: str = None):
    conn = get_db()
    try:
        query = "SELECT * FROM cards WHERE 1=1"
        params = []
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

    needs_sections = {"needs-action", "action-needed", "needs_response", "needs-response"}
    no_action_sections = {"no-action", "noise", "responded", "fyi", "alert"}
    needs_action = []
    no_action = []

    for row in rows:
        card = _row_to_card(row)
        if not _should_include_in_inbox_view(card, source, days, now_utc, now_local):
            continue
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


def _task_jira_keys(task: dict):
    search_text = f"{task.get('title', '')}\n{task.get('description', '')}"
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", search_text)))


def _get_task_by_number(task_number: int):
    for task in _parse_active_tasks():
        if task.get("number") == task_number:
            return task
    return None


def _set_task_status(task_number: int, new_status: str):
    """Update status in every matching task block by task number."""
    if not TASKS_FILE.exists():
        return 0

    content = TASKS_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^###\s+#{task_number}\s*-\s*.+?)(?=^###\s+#\d+\s*-|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    updated_count = 0

    def replace_status(match):
        nonlocal updated_count
        updated_count += 1
        block = match.group(1)

        if re.search(r"^\*\*Status\*\*:\s*.+$", block, flags=re.MULTILINE):
            return re.sub(
                r"^\*\*Status\*\*:\s*.+$",
                f"**Status**: {new_status}",
                block,
                count=1,
                flags=re.MULTILINE,
            )

        lines = block.splitlines()
        if not lines:
            return block
        return "\n".join([lines[0], f"**Status**: {new_status}", *lines[1:]])

    updated = pattern.sub(replace_status, content)
    if updated_count:
        TASKS_FILE.write_text(updated, encoding="utf-8")
    return updated_count


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
    updated_blocks = _set_task_status(task_number, new_status)
    if not updated_blocks:
        _mark_action_step_status(action_step_id, "failed")
        _finish_execution_attempt(attempt_id, "failed", error="task block not found")
        raise HTTPException(404, f"task #{task_number} block not found in active file")

    note = (body.get("note") or "").strip()
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


async def card_event_generator():
    """Yield new cards as SSE events."""
    conn = get_db()
    try:
        row = conn.execute("SELECT MAX(id) FROM cards").fetchone()[0]
        last_id = row or 0
    finally:
        conn.close()

    while True:
        await asyncio.sleep(10)
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM cards WHERE id > ? ORDER BY id ASC", [last_id]
            ).fetchall()
            for row in rows:
                card = _row_to_card(row)
                last_id = card["id"]
                yield f"data: {json.dumps(card)}\n\n"
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
    return {"terminal": TERMINAL_APP}

@app.post("/api/settings")
async def update_settings(body: dict):
    global TERMINAL_APP
    if "terminal" in body:
        allowed = {"Terminal", "Warp", "iTerm", "Alacritty", "kitty"}
        if body["terminal"] not in allowed:
            raise HTTPException(400, f"terminal must be one of {allowed}")
        TERMINAL_APP = body["terminal"]
    return {"terminal": TERMINAL_APP}


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


@app.get("/api/jira/sprint")
async def jira_sprint(refresh: bool = False):
    """Fetch current sprint tasks via Claude CLI + Atlassian MCP."""
    import time

    if not refresh and _jira_cache["data"] and (time.time() - _jira_cache["fetched_at"]) < 120:
        return _jira_cache["data"]

    user_clause = f'assignee = "{JIRA_USER}" AND ' if JIRA_USER else "assignee = currentUser() AND "
    jql = f"{user_clause}sprint in openSprints() ORDER BY status ASC, priority DESC"
    prompt = (
        "Use Atlassian MCP jira_search.\n"
        f"JQL: {jql}\n"
        "Fields: key,summary,status,priority,issuetype,labels,updated\n"
        "Return ONLY a JSON array. "
        "Each object must have: key, summary, status, status_category, priority, issue_type, labels, updated. "
        "status_category must match Jira's statusCategory.name if available."
    )

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
    msg = body.get("message", "")[:100]
    title = body.get("title", "eng-buddy")
    script = f'display notification "{msg}" with title "{title}" sound name "Glass"'
    subprocess.Popen(["osascript", "-e", script])
    return {"ok": True}

@app.get("/api/briefing")
async def get_briefing(regenerate: bool = False):
    """Generate or return cached morning briefing."""
    from datetime import date, timedelta
    today = date.today().isoformat()

    conn = get_db()
    try:
        # Check cache
        if not regenerate:
            row = conn.execute(
                "SELECT content FROM briefings WHERE date = ?", [today]
            ).fetchone()
            if row:
                return json.loads(row[0])

        # Gather data for briefing
        pending_cards = conn.execute(
            "SELECT source, section, summary, context_notes, draft_response FROM cards WHERE status = 'pending' ORDER BY timestamp DESC LIMIT 30"
        ).fetchall()

        # Get yesterday's stats
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        stats = conn.execute(
            "SELECT metric, SUM(value) FROM stats WHERE date = ? GROUP BY metric", [yesterday]
        ).fetchall()
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

    # Cache it
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO briefings (date, content, generated_at) VALUES (?, ?, ?)",
            [today, json.dumps(briefing), datetime.now().isoformat()]
        )
        conn.commit()
    finally:
        conn.close()

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


def _record_stat(metric, value=1, details=None):
    """Record a stat to the stats table."""
    from datetime import date
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO stats (date, metric, value, details) VALUES (?, ?, ?, ?)",
            [date.today().isoformat(), metric, value, details]
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=7777, reload=True)
