import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

import ptyprocess
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from migrate import migrate

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"
STATIC_DIR = Path(__file__).parent / "static"
TERMINAL_APP = os.environ.get("ENG_BUDDY_TERMINAL", "Terminal")
JIRA_USER = os.environ.get("ENG_BUDDY_JIRA_USER", "")
JIRA_BOARD = os.environ.get("ENG_BUDDY_JIRA_BOARD", "Systems")

# In-memory cache for Jira sprint data
_jira_cache = {"data": None, "fetched_at": 0}


def _escape_applescript_text(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(exist_ok=True)
    migrate()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/cards")
async def get_cards(source: str = None, status: str = "pending", section: str = None):
    conn = get_db()
    try:
        query = "SELECT * FROM cards WHERE status = ?"
        params = [status]
        if source:
            query += " AND source = ?"
            params.append(source)
        if section:
            query += " AND section = ?"
            params.append(section)
        query += " ORDER BY timestamp DESC"
        rows = conn.execute(query, params).fetchall()
        cards = []
        for row in rows:
            card = dict(row)
            try:
                card["proposed_actions"] = json.loads(card["proposed_actions"] or "[]")
            except (json.JSONDecodeError, TypeError):
                card["proposed_actions"] = []
            cards.append(card)
        counts = {}
        for s in ["pending", "held", "approved", "completed", "failed"]:
            counts[s] = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE status = ?", [s]
            ).fetchone()[0]
        return {"cards": cards, "counts": counts}
    finally:
        conn.close()

@app.post("/api/cards/{card_id}/hold")
async def hold_card(card_id: int):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET status = 'held' WHERE id = ?", [card_id]
        )
        conn.commit()
    finally:
        conn.close()
    _log_decision(card_id, "held")
    return {"id": card_id, "status": "held"}

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
    finally:
        conn.close()
    _log_decision(card_id, new_status)
    return {"id": card_id, "status": new_status}

@app.post("/api/cards/{card_id}/send-slack")
async def send_slack_draft(card_id: int):
    """Send the draft response to Slack via MCP."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    draft = card.get("draft_response", "")
    if not draft:
        raise HTTPException(400, "no draft response")

    actions = json.loads(card.get("proposed_actions") or "[]")
    channel = ""
    thread_ts = ""
    for a in actions:
        channel = a.get("channel_id", channel)
        thread_ts = a.get("thread_ts", thread_ts)

    if not channel:
        raise HTTPException(400, "no channel info in card")

    prompt = (
        f"Use the Slack MCP slack_reply_to_thread tool. "
        f"Channel: {channel}, thread_ts: {thread_ts}, "
        f"text: {json.dumps(draft)}"
    )
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise HTTPException(502, f"slack send failed: {result.stderr[:200]}")

    conn = get_db()
    conn.execute(
        "UPDATE cards SET status = 'completed', responded = 1, section = 'no-action' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    _record_stat("drafts_sent")
    _log_decision(card_id, "sent-slack")
    return {"status": "sent", "output": result.stdout[:500]}


@app.post("/api/cards/{card_id}/send-email")
async def send_email_draft(card_id: int):
    """Send the draft email response via Gmail MCP."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
        if not row:
            raise HTTPException(404, "card not found")
        card = dict(row)
    finally:
        conn.close()

    draft = card.get("draft_response", "")
    if not draft:
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
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise HTTPException(502, f"email send failed: {result.stderr[:200]}")

    conn = get_db()
    conn.execute(
        "UPDATE cards SET status = 'completed', responded = 1, section = 'no-action' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    _record_stat("drafts_sent")
    _log_decision(card_id, "sent-email")
    return {"status": "sent", "output": result.stdout[:500]}


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
                card = dict(row)
                try:
                    card["proposed_actions"] = json.loads(card["proposed_actions"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    card["proposed_actions"] = []
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
        dimensions=(50, 220)
    )

    # Mark card as running
    conn = get_db()
    conn.execute(
        "UPDATE cards SET execution_status = 'running', status = 'approved' WHERE id = ?",
        [card_id]
    )
    conn.commit()
    conn.close()

    output_chunks = []

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

        _log_decision(card_id, "executed")

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
    history = body.get("history", [])

    proposed = card.get("proposed_actions") or "[]"
    summary = card.get("summary", "")
    source = card.get("source", "")

    system_context = (
        f"You are eng-buddy helping to refine a task before execution.\n\n"
        f"Source: {source}\nSummary: {summary}\n"
        f"Current proposed actions:\n{proposed}\n\n"
        f"The user wants to refine or adjust these actions. "
        f"When they are satisfied, they will click Approve to execute."
    )

    conversation = system_context + "\n\n"
    for turn in history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        conversation += f"{role.upper()}: {content}\n"
    conversation += f"USER: {user_message}\n"

    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", conversation],
        capture_output=True,
        text=True,
        timeout=60
    )

    response_text = result.stdout.strip()

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

    # Persist refinement history on the card
    full_history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response_text},
    ]
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cards SET refinement_history = ? WHERE id = ?",
            [json.dumps(full_history), card_id]
        )
        conn.commit()
    finally:
        conn.close()

    _log_decision(card_id, "refined")

    return {"response": response_text}

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

    # Write a self-contained launcher script with heredoc (no escaping issues)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False,
                                     dir=Path.home() / ".claude" / "eng-buddy") as f:
        # Use heredoc with a unique delimiter to avoid any content conflicts
        f.write("#!/bin/bash\n")
        f.write("export PATH=\"/opt/homebrew/bin:/usr/local/bin:$PATH\"\n")
        f.write("PROMPT=$(cat <<'ENGBUDDY_EOF'\n")
        f.write(context)
        f.write("\nENGBUDDY_EOF\n)\n")
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

    return {"status": "opened", "terminal": TERMINAL_APP, "launcher": launcher}

def _classify_jira_status(status_str, status_category=None):
    """Map a Jira status string to a board column (todo/in_progress/done).

    Uses status_category if the LLM returned it, otherwise falls back to
    keyword matching against common Jira status names.
    """
    if status_category:
        cat = status_category.lower().replace(" ", "_")
        if cat in ("to_do", "to do"):
            return "todo"
        if cat == "done":
            return "done"
        if cat in ("in_progress", "in progress"):
            return "in_progress"

    s = (status_str or "").lower()
    done_keywords = ("done", "closed", "resolved", "complete", "released", "cancelled")
    todo_keywords = ("to do", "todo", "open", "new", "backlog", "selected for development",
                     "waiting for support", "waiting for customer", "pending")
    if any(k in s for k in done_keywords):
        return "done"
    if any(k in s for k in todo_keywords):
        return "todo"
    return "in_progress"


@app.get("/api/jira/sprint")
async def jira_sprint(refresh: bool = False):
    """Fetch current sprint tasks via claude CLI + Atlassian MCP."""
    import time

    # Return cached data if fresh (< 2 min) and no forced refresh
    if not refresh and _jira_cache["data"] and (time.time() - _jira_cache["fetched_at"]) < 120:
        return _jira_cache["data"]

    user_clause = f'assignee = "{JIRA_USER}"' if JIRA_USER else "assignee = currentUser()"

    prompt = (
        f"Use the Atlassian MCP tools to find my current sprint tasks:\n"
        f"1. Call jira_get_agile_boards with board_name='{JIRA_BOARD}'.\n"
        f"2. Call jira_get_sprints_from_board with that board's ID, state='active'.\n"
        f"3. If multiple active sprints, pick the one whose name starts with 'SYSTEMS'.\n"
        f"4. Call jira_search with JQL: {user_clause} AND sprint = <sprint_id> ORDER BY priority DESC, status ASC\n"
        f"   Fields: summary,status,priority,issuetype,labels,updated. Limit: 30.\n"
        f"Return ONLY a JSON array of objects with keys: "
        f"key, summary, status (string), status_category (the Jira statusCategory: 'To Do', 'In Progress', or 'Done'), "
        f"priority, issue_type, labels (array), updated. "
        f"For status_category, use the statusCategory.name from the Jira issue status object. "
        f"No prose, just the JSON array. Empty array [] if no issues found."
    )

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout.strip()
        match = re.search(r'\[.*\]', output, re.DOTALL)
        if match:
            issues = json.loads(match.group(0))
        else:
            issues = []
    except Exception as e:
        raise HTTPException(500, f"Jira fetch failed: {e}")

    # Group by status category for board view with robust fallback mapping
    board = {"todo": [], "in_progress": [], "done": []}
    for issue in issues:
        col = _classify_jira_status(
            issue.get("status"),
            issue.get("status_category"),
        )
        board[col].append(issue)

    response = {"issues": issues, "board": board, "total": len(issues)}
    _jira_cache["data"] = response
    _jira_cache["fetched_at"] = time.time()
    return response

@app.get("/api/decisions/search")
async def search_decisions(q: str = "", source: str = None, action: str = None, limit: int = 20):
    """Search past decisions using FTS5 or LIKE fallback."""
    limit = min(limit, 100)
    conn = get_db()
    try:
        if q:
            # Try FTS5 first (sanitize by quoting each term)
            try:
                safe_q = " ".join(f'"{w}"' for w in q.split() if w) or '""'
                query = """
                    SELECT d.* FROM decisions d
                    JOIN decisions_fts fts ON d.id = fts.rowid
                    WHERE decisions_fts MATCH ?
                """
                params = [safe_q]
                if source:
                    query += " AND d.source = ?"
                    params.append(source)
                if action:
                    query += " AND d.action = ?"
                    params.append(action)
                query += " ORDER BY d.decision_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(query, params).fetchall()
            except sqlite3.OperationalError:
                # FTS not available, fallback to LIKE
                like = f"%{q}%"
                query = """
                    SELECT * FROM decisions
                    WHERE (summary LIKE ? OR context_notes LIKE ?
                           OR draft_response LIKE ? OR execution_result LIKE ?
                           OR tags LIKE ?)
                """
                params = [like, like, like, like, like]
                if source:
                    query += " AND source = ?"
                    params.append(source)
                if action:
                    query += " AND action = ?"
                    params.append(action)
                query += " ORDER BY decision_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(query, params).fetchall()
        else:
            query = "SELECT * FROM decisions WHERE 1=1"
            params = []
            if source:
                query += " AND source = ?"
                params.append(source)
            if action:
                query += " AND action = ?"
                params.append(action)
            query += " ORDER BY decision_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()

        decisions = []
        for row in rows:
            d = dict(row)
            for field in ("refinement_history", "tags"):
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            decisions.append(d)
        return {"decisions": decisions, "total": len(decisions)}
    finally:
        conn.close()


@app.post("/api/notify")
async def notify(body: dict):
    msg = _escape_applescript_text(body.get("message", "")[:100])
    title = _escape_applescript_text(body.get("title", "eng-buddy"))
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

    # Build briefing prompt — summarize cards to keep prompt small
    sys_path = Path(__file__).parent.parent / "bin"
    sys.path.insert(0, str(sys_path))
    from brain import build_context_prompt

    # Group cards by source for a compact summary
    by_source = {}
    for c in cards_data:
        src = c.get("source", "unknown")
        by_source.setdefault(src, []).append(c.get("summary", "?")[:80])
    cards_summary = ""
    for src, summaries in by_source.items():
        cards_summary += f"\n{src} ({len(summaries)} pending):\n"
        for s in summaries[:5]:
            cards_summary += f"  - {s}\n"
        if len(summaries) > 5:
            cards_summary += f"  ... and {len(summaries) - 5} more\n"

    context = build_context_prompt()
    prompt = f"""{context}

Generate a morning briefing for today ({today}). You have:

PENDING CARDS SUMMARY:
{cards_summary}

YESTERDAY'S STATS:
{json.dumps(stats_data)}

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
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", prompt],
            capture_output=True, text=True, timeout=60
        )
        match = re.search(r'\{.*\}', result.stdout, re.DOTALL)
        if match:
            briefing = json.loads(match.group(0))
        else:
            briefing = {"error": "Failed to generate briefing", "raw": result.stdout[:500]}
    except Exception as e:
        briefing = {"error": str(e)}

    # Only cache successful briefings
    if "error" not in briefing:
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
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", prompt],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise HTTPException(502, f"filter creation failed: {result.stderr[:200]}")

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
async def dismiss_card(card_id: int):
    """Move card to no-action section."""
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
    finally:
        conn.close()

    _log_decision(card_id, "dismissed")
    return {"id": card_id, "section": "no-action"}


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


def _log_decision(card_id, action, extra_fields=None):
    """Log a decision to the decisions table. Captures full card context.
    Never raises — logging failures must not break primary operations."""
    try:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", [card_id]).fetchone()
            if not row:
                return
            card = dict(row)

            summary = card.get("summary", "") or ""
            context = card.get("context_notes", "") or ""

            fields = {
                "card_id": card_id,
                "action": action,
                "source": card.get("source"),
                "summary": summary,
                "context_notes": context,
                "draft_response": card.get("draft_response"),
                "refinement_history": card.get("refinement_history"),
                "execution_result": card.get("execution_result"),
                "decision_at": datetime.now().isoformat(),
                "tags": None,
            }
            if extra_fields:
                fields.update(extra_fields)

            conn.execute(
                """INSERT INTO decisions
                   (card_id, action, source, summary, context_notes, draft_response,
                    refinement_history, execution_result, decision_at, tags)
                   VALUES (:card_id, :action, :source, :summary, :context_notes,
                           :draft_response, :refinement_history, :execution_result,
                           :decision_at, :tags)""",
                fields
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"Decision log warning: {e}")


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=7777, reload=True)
