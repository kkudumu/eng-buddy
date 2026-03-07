import asyncio
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path
from contextlib import asynccontextmanager

import ptyprocess
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = Path.home() / ".claude" / "eng-buddy" / "inbox.db"
STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(exist_ok=True)
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
async def get_cards(source: str = None, status: str = "pending"):
    conn = get_db()
    try:
        query = "SELECT * FROM cards WHERE status = ?"
        params = [status]
        if source:
            query += " AND source = ?"
            params.append(source)
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

    return {"response": response_text}

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

    # Open new Terminal window running the launcher script
    script = f'tell application "Terminal"\ndo script "{launcher}"\nactivate\nend tell'
    subprocess.Popen(["osascript", "-e", script])

    return {"status": "opened", "launcher": launcher}

@app.post("/api/notify")
async def notify(body: dict):
    msg = body.get("message", "")[:100]
    title = body.get("title", "eng-buddy")
    script = f'display notification "{msg}" with title "{title}" sound name "Glass"'
    subprocess.Popen(["osascript", "-e", script])
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=7777, reload=True)
