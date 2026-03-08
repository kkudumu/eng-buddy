import pytest
from pathlib import Path
import sqlite3
import subprocess
from httpx import AsyncClient, ASGITransport
import server
from server import app

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_get_cards_returns_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
    assert r.status_code == 200
    data = r.json()
    assert "cards" in data
    assert isinstance(data["cards"], list)

@pytest.mark.asyncio
async def test_card_has_required_fields():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
    data = r.json()
    if data["cards"]:
        card = data["cards"][0]
        for field in ["id", "source", "summary", "classification", "status", "proposed_actions"]:
            assert field in card, f"missing field: {field}"

@pytest.mark.asyncio
async def test_hold_card():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
        cards = r.json()["cards"]
        if not cards:
            pytest.skip("no cards in DB")
        card_id = cards[0]["id"]
        r2 = await client.post(f"/api/cards/{card_id}/hold")
    assert r2.status_code == 200
    assert r2.json()["status"] == "held"


@pytest.mark.asyncio
async def test_inbox_view_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/inbox-view", params={"source": "gmail"})
    assert r.status_code == 200
    data = r.json()
    assert "needs_action" in data
    assert "no_action" in data


@pytest.mark.asyncio
async def test_bulk_approve_guard_rejects():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/approve-all")
    assert r.status_code == 405
    assert "disabled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tasks_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/tasks")
    assert r.status_code == 200
    data = r.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


@pytest.mark.asyncio
async def test_close_task_endpoint_updates_all_matching_blocks(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    tasks_file = tasks_dir / "active-tasks.md"
    tasks_file.write_text(
        """## PENDING TASKS

### #42 - Sample task one
**Status**: pending
**Priority**: high
**Description**: first

## IN PROGRESS TASKS

### #42 - Sample task two
**Status**: in_progress
**Priority**: high
**Description**: second
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "TASKS_FILE", tasks_file)
    monkeypatch.setattr(server, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(
        server,
        "_build_task_daily_log_line",
        lambda task, note="": f"Task #{task['number']} closed",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decision = await client.post(
            "/api/tasks/42/decision",
            json={"action": "close", "decision": "approved", "rationale": "ready"},
        )
        assert decision.status_code == 200
        decision_event_id = decision.json()["decision_event_id"]
        r = await client.post("/api/tasks/42/close", json={"decision_event_id": decision_event_id})

    assert r.status_code == 200
    assert r.json()["updated_blocks"] == 2
    assert "daily_log_file" in r.json()
    updated = tasks_file.read_text(encoding="utf-8")
    assert updated.count("**Status**: completed") == 2


@pytest.mark.asyncio
async def test_task_daily_log_endpoint_appends_entry(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    tasks_file = tasks_dir / "active-tasks.md"
    tasks_file.write_text(
        """## PENDING TASKS

### #7 - Daily log test task
**Status**: pending
**Priority**: medium
**Description**: verify logging
""",
        encoding="utf-8",
    )

    daily_dir = tmp_path / "daily"
    monkeypatch.setattr(server, "TASKS_FILE", tasks_file)
    monkeypatch.setattr(server, "DAILY_DIR", daily_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decision = await client.post(
            "/api/tasks/7/decision",
            json={"action": "daily-log", "decision": "approved", "rationale": "capture update"},
        )
        assert decision.status_code == 200
        decision_event_id = decision.json()["decision_event_id"]
        r = await client.post(
            "/api/tasks/7/daily-log",
            json={"note": "finished setup", "decision_event_id": decision_event_id},
        )

    assert r.status_code == 200
    payload = r.json()
    assert payload["inserted"] is True
    log_path = Path(payload["daily_file"])
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "Task #7 Daily log test task" in text
    assert "finished setup" in text


@pytest.mark.asyncio
async def test_card_refine_persists_chat_history(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            proposed_actions TEXT,
            refinement_history TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO cards (id, source, summary, proposed_actions) VALUES (1, 'slack', 'Sample card', '[]')"
    )
    conn.execute(
        """CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_ingested_message_id INTEGER DEFAULT 0,
            UNIQUE(scope, source_ref)
        )"""
    )
    conn.execute(
        """CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "_trigger_chat_learning", lambda session_id: None)
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="assistant reply", stderr=""
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/1/refine", json={"message": "hello", "history": []})

    assert r.status_code == 200
    assert r.json()["response"] == "assistant reply"

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    rows = check.execute(
        """SELECT m.role, m.content
           FROM chat_messages m
           JOIN chat_sessions s ON s.id = m.session_id
           WHERE s.scope = 'card_refine' AND s.source_ref = '1'
           ORDER BY m.id ASC"""
    ).fetchall()
    check.close()

    assert [dict(rw) for rw in rows] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "assistant reply"},
    ]


@pytest.mark.asyncio
async def test_ingest_transcript_endpoint_persists_message(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_ingested_message_id INTEGER DEFAULT 0,
            UNIQUE(scope, source_ref)
        )"""
    )
    conn.execute(
        """CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute(
        "INSERT INTO chat_sessions (scope, source, source_ref, title) VALUES ('card_terminal_session', 'slack', '22', 'Test')"
    )
    conn.commit()
    conn.close()

    transcript = tmp_path / "session.log"
    transcript.write_text("USER: hi\nASSISTANT: hello\n", encoding="utf-8")

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "_trigger_chat_learning", lambda session_id: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/chat-sessions/1/ingest-transcript",
            json={"path": str(transcript), "cleanup": True},
        )

    assert r.status_code == 200
    assert transcript.exists() is False
    check = sqlite3.connect(db_path)
    row = check.execute(
        "SELECT role, content FROM chat_messages WHERE session_id = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    check.close()
    assert row[0] == "assistant"
    assert "USER: hi" in row[1]


@pytest.mark.asyncio
async def test_open_session_creates_chat_session(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            proposed_actions TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO cards (id, source, summary, proposed_actions) VALUES (5, 'gmail', 'Session card', '[]')"
    )
    conn.execute(
        """CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_ingested_message_id INTEGER DEFAULT 0,
            UNIQUE(scope, source_ref)
        )"""
    )
    conn.execute(
        """CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_launch_terminal_session",
        lambda context, launcher_prefix="open-session-", chat_session_id=None: "/tmp/fake-launcher.sh",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/5/open-session")

    assert r.status_code == 200
    payload = r.json()
    assert payload["chat_session_id"] == 1
    assert payload["launcher"] == "/tmp/fake-launcher.sh"


@pytest.mark.asyncio
async def test_daily_log_readonly_endpoints(tmp_path, monkeypatch):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    sample = daily_dir / "2026-03-08.md"
    sample.write_text("# Daily Log - 2026-03-08\n\n## ✅ Completed\n- 10:00 | shipped thing\n", encoding="utf-8")
    monkeypatch.setattr(server, "DAILY_DIR", daily_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_r = await client.get("/api/daily/logs")
        detail_r = await client.get("/api/daily/logs/2026-03-08")

    assert list_r.status_code == 200
    assert list_r.json()["count"] >= 1
    assert detail_r.status_code == 200
    assert "shipped thing" in detail_r.json()["content"]


@pytest.mark.asyncio
async def test_knowledge_readonly_index_and_doc(tmp_path, monkeypatch):
    knowledge_dir = tmp_path / "knowledge"
    patterns_dir = tmp_path / "patterns"
    stakeholders_dir = tmp_path / "stakeholders"
    memory_dir = tmp_path / "memory"
    for folder in [knowledge_dir, patterns_dir, stakeholders_dir, memory_dir]:
        folder.mkdir(parents=True, exist_ok=True)
    doc = knowledge_dir / "runbooks.md"
    doc.write_text("# Runbooks\n\nHello", encoding="utf-8")

    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(server, "PATTERNS_DIR", patterns_dir)
    monkeypatch.setattr(server, "STAKEHOLDERS_DIR", stakeholders_dir)
    monkeypatch.setattr(server, "MEMORY_DIR", memory_dir)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        idx = await client.get("/api/knowledge/index")
        assert idx.status_code == 200
        assert idx.json()["count"] >= 1

        doc_r = await client.get("/api/knowledge/doc", params={"path": "knowledge/runbooks.md"})
        assert doc_r.status_code == 200
        assert "Hello" in doc_r.json()["content"]

        blocked = await client.get("/api/knowledge/doc", params={"path": "../secrets.txt"})
        assert blocked.status_code == 400


@pytest.mark.asyncio
async def test_learnings_readonly_summary_and_events(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE learning_events (
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
        """INSERT INTO learning_events
           (category, title, note, status, created_at)
           VALUES ('troubleshooting', 'cache bug', 'fixed cache invalidation', 'captured', datetime('now'))"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "DB_PATH", db_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = await client.get("/api/learnings/summary", params={"range": "day"})
        events = await client.get("/api/learnings/events", params={"range": "day"})

    assert summary.status_code == 200
    assert "by_bucket" in summary.json()
    assert events.status_code == 200
    assert isinstance(events.json().get("events"), list)


@pytest.mark.asyncio
async def test_card_close_requires_approved_decision(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            context_notes TEXT,
            draft_response TEXT,
            proposed_actions TEXT,
            status TEXT,
            section TEXT,
            execution_result TEXT,
            refinement_history TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO cards (id, source, summary, proposed_actions, status, section) VALUES (1, 'jira', 'CARD-1 close me', '[]', 'pending', 'needs-action')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "DAILY_DIR", tmp_path / "daily")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.post("/api/cards/1/close", json={"note": "done"})
        assert blocked.status_code == 400

        decision = await client.post(
            "/api/cards/1/decision",
            json={"action": "close", "decision": "approved", "rationale": "ship it"},
        )
        assert decision.status_code == 200
        decision_event_id = decision.json()["decision_event_id"]

        ok = await client.post(
            "/api/cards/1/close",
            json={"note": "done", "decision_event_id": decision_event_id},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "completed"
