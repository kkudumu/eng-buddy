import json
import pytest
from pathlib import Path
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
import migrate as migrate_module
import server
from server import app

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_restart_uses_launchd_managed_start_script(monkeypatch):
    captured = {}

    def fake_popen(args, start_new_session, stdout, stderr):
        captured["args"] = args
        captured["start_new_session"] = start_new_session
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        return object()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/restart")

    assert r.status_code == 200
    assert r.json() == {"status": "restarting", "manager": "launchd"}
    assert captured["args"][0] == "/bin/bash"
    assert captured["args"][1].endswith("/dashboard/start.sh")
    assert captured["args"][2] == "--restart"
    assert captured["start_new_session"] is True


@pytest.mark.asyncio
async def test_settings_defaults_disable_macos_notifications(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings")

    assert r.status_code == 200
    assert r.json() == {
        "terminal": server.DEFAULT_TERMINAL_APP,
        "macos_notifications": False,
    }


@pytest.mark.asyncio
async def test_update_settings_persists_notification_preference(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/settings",
            json={"terminal": "Warp", "macos_notifications": True},
        )

    assert r.status_code == 200
    assert r.json() == {"terminal": "Warp", "macos_notifications": True}
    settings_file = tmp_path / "dashboard-settings.json"
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "terminal": "Warp",
        "macos_notifications": True,
    }


@pytest.mark.asyncio
async def test_notify_is_noop_when_macos_notifications_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)
    called = False

    def fake_popen(*args, **kwargs):
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/notify", json={"title": "eng-buddy", "message": "hello"})

    assert r.status_code == 200
    assert r.json() == {"ok": True, "notified": False, "reason": "disabled"}
    assert called is False


@pytest.mark.asyncio
async def test_notify_calls_osascript_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)
    (tmp_path / "dashboard-settings.json").write_text(
        json.dumps({"terminal": "Terminal", "macos_notifications": True}),
        encoding="utf-8",
    )
    captured = {}

    def fake_popen(args):
        captured["args"] = args
        return object()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/notify", json={"title": "eng-buddy", "message": "hello"})

    assert r.status_code == 200
    assert r.json() == {"ok": True, "notified": True}
    assert captured["args"][0] == "osascript"
    assert captured["args"][1] == "-e"
    assert 'display notification "hello"' in captured["args"][2]


@pytest.mark.asyncio
async def test_send_debug_log_to_claude_queues_sync_event(tmp_path, monkeypatch):
    sync_file = tmp_path / ".runtime" / "claude-sync-events.txt"
    monkeypatch.setattr(server, "CLAUDE_SYNC_FILE", sync_file)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/debug/send-to-claude",
            json={
                "log_line": "Failed to load TASKS view: boom",
                "level": "error",
                "tab": "TASKS",
                "timestamp": "2026-03-09T10:15:00Z",
                "details": {"origin": "view-load"},
            },
        )

    assert r.status_code == 200
    payload = r.json()
    assert payload["queued"] is True
    text = sync_file.read_text(encoding="utf-8")
    assert "Dashboard debug log forwarded to Claude Code" in text
    assert "tab=TASKS" in text
    assert "Failed to load TASKS view: boom" in text


@pytest.mark.asyncio
async def test_get_poller_status_returns_poller_timing(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(server, "ENG_BUDDY_DIR", tmp_path)

    (tmp_path / "slack-poller-state.json").write_text(
        json.dumps({"last_check": str(now.timestamp() - 120)}),
        encoding="utf-8",
    )
    (tmp_path / "gmail-poller-state.json").write_text(
        json.dumps({"last_check_ts": int(now.timestamp() - 45)}),
        encoding="utf-8",
    )
    (tmp_path / "calendar-poller-state.json").write_text(
        json.dumps({"last_fetch": now.astimezone().strftime("%Y-%m-%d-%H-%M")}),
        encoding="utf-8",
    )
    (tmp_path / "jira-ingestor-state.json").write_text(
        json.dumps({"last_checked": (now - timedelta(seconds=30)).isoformat()}),
        encoding="utf-8",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/pollers/status")

    assert r.status_code == 200
    payload = r.json()
    assert "generated_at" in payload
    assert len(payload["pollers"]) == 4

    slack = next(item for item in payload["pollers"] if item["id"] == "slack")
    assert slack["interval_seconds"] == 300
    assert slack["last_run_at"] is not None
    assert slack["next_run_at"] is not None
    assert slack["health"] in {"running", "stale", "unknown"}

@pytest.mark.asyncio
async def test_get_cards_returns_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
    assert r.status_code == 200
    data = r.json()
    assert "cards" in data
    assert isinstance(data["cards"], list)

@pytest.mark.asyncio
async def test_get_cards_calendar_defaults_to_all_statuses(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            draft_response TEXT,
            context_notes TEXT,
            responded INTEGER
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, responded)
           VALUES (1, 'calendar', '2026-03-09T14:30:00+00:00', 'Held meeting', 'normal', 'held', '[]', 'needs-action', 0)"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, responded)
           VALUES (2, 'calendar', '2026-03-09T15:30:00+00:00', 'Pending meeting', 'normal', 'pending', '[]', 'needs-action', 0)"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards", params={"source": "calendar"})

    assert r.status_code == 200
    cards = r.json()["cards"]
    assert [card["summary"] for card in cards] == ["Pending meeting", "Held meeting"]


@pytest.mark.asyncio
async def test_get_briefing_uses_calendar_cards_for_meetings(tmp_path, monkeypatch):
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            draft_response TEXT,
            context_notes TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE briefings (
            date TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            generated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE stats (
            date TEXT NOT NULL,
            metric TEXT NOT NULL,
            value INTEGER NOT NULL
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, draft_response, context_notes)
           VALUES (?, 'calendar', ?, 'Sprint Planning', 'normal', 'pending', ?, 'needs-action', '', ?)""",
        (
            1,
            f"{today.isoformat()}T14:30:00+00:00",
            json.dumps(
                [
                    {
                        "summary": "Sprint Planning",
                        "start": f"{today.isoformat()}T07:30:00-07:00",
                        "end": f"{today.isoformat()}T08:00:00-07:00",
                        "attendees": ["team@example.com"],
                        "hangout_link": "https://meet.example.com/abc",
                    }
                ]
            ),
            "Review blockers before kickoff",
        ),
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, draft_response, context_notes)
           VALUES (?, 'calendar', ?, 'Home', 'normal', 'pending', ?, 'no-action', '', '')""",
        (
            2,
            f"{today.isoformat()}T00:00:00+00:00",
            json.dumps(
                [
                    {
                        "summary": "Home",
                        "start": today.isoformat(),
                        "end": tomorrow.isoformat(),
                        "attendees": [],
                    }
                ]
            ),
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setitem(sys.modules, "brain", types.SimpleNamespace(build_context_prompt=lambda: "CTX"))
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps(
                {
                    "date": today.isoformat(),
                    "meetings": [],
                    "needs_response": [],
                    "alerts": [],
                    "cognitive_load": {"level": "MODERATE", "meeting_count": 0, "action_count": 1},
                    "stats": {},
                    "heads_up": [],
                }
            ),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/briefing?regenerate=true")

    assert r.status_code == 200
    payload = r.json()
    assert payload["meetings"] == [
        {
            "time": "07:30",
            "title": "Sprint Planning",
            "prep": "Review blockers before kickoff",
        }
    ]
    assert payload["cognitive_load"]["meeting_count"] == 1

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
async def test_inbox_view_keeps_slack_no_action_through_monday_eod(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            draft_response TEXT,
            context_notes TEXT,
            responded INTEGER
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, responded)
           VALUES (1, 'slack', '2026-03-06T13:47:00+00:00', 'Nik via DM: Friday check-in', 'fyi', 'completed', '[]', 'no-action', 1)"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, responded)
           VALUES (2, 'slack', '2026-03-03T13:47:00+00:00', 'Old slack item', 'fyi', 'completed', '[]', 'no-action', 1)"""
    )
    conn.commit()
    conn.close()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 3, 9, 18, 0, 0, tzinfo=timezone.utc)
            if tz is None:
                return current.replace(tzinfo=None)
            return current.astimezone(tz)

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "datetime", FrozenDateTime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/inbox-view", params={"source": "slack", "days": 3})

    assert r.status_code == 200
    data = r.json()
    assert [card["summary"] for card in data["no_action"]] == ["Nik via DM: Friday check-in"]


@pytest.mark.asyncio
async def test_inbox_view_drops_slack_no_action_after_monday_eod(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            draft_response TEXT,
            context_notes TEXT,
            responded INTEGER
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, responded)
           VALUES (1, 'slack', '2026-03-06T13:47:00+00:00', 'Nik via DM: Friday check-in', 'fyi', 'completed', '[]', 'no-action', 1)"""
    )
    conn.commit()
    conn.close()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 3, 10, 8, 30, 0, tzinfo=timezone.utc)
            if tz is None:
                return current.replace(tzinfo=None)
            return current.astimezone(tz)

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "datetime", FrozenDateTime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/inbox-view", params={"source": "slack", "days": 3})

    assert r.status_code == 200
    data = r.json()
    assert data["no_action"] == []


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
    monkeypatch.setattr(server, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(server, "CLAUDE_SYNC_FILE", tmp_path / ".runtime" / "claude-sync-events.txt")
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
        r = await client.post(
            "/api/tasks/42/close",
            json={"note": "finished setup", "decision_event_id": decision_event_id},
        )

    assert r.status_code == 200
    assert r.json()["updated_blocks"] == 2
    assert "daily_log_file" in r.json()
    updated = tasks_file.read_text(encoding="utf-8")
    assert updated.count("**Status**: completed") == 2
    assert "## COMPLETED TASKS" in updated
    assert updated.count("**Completion Note**: finished setup") == 2
    assert "## PENDING TASKS\n\n### #42" not in updated
    assert "## IN PROGRESS TASKS\n\n### #42" not in updated
    sync_text = server.CLAUDE_SYNC_FILE.read_text(encoding="utf-8")
    assert "Dashboard closed Task #42" in sync_text
    assert "finished setup" in sync_text


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
async def test_gmail_analyze_persists_detected_labels_and_draft(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            classification TEXT,
            context_notes TEXT,
            draft_response TEXT,
            proposed_actions TEXT,
            analysis_metadata TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, summary, classification, context_notes, draft_response, proposed_actions, analysis_metadata)
           VALUES (
             11,
             'gmail',
             'ceo@example.com: Need rollout status',
             'needs-response',
             'Executive follow-up',
             '',
             ?,
             '{}'
           )""",
        [json.dumps([{"to_email": "ceo@example.com", "subject": "Need rollout status", "thread_id": "t-1"}])],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps(
                {
                    "detected_category": "ops",
                    "suggested_labels": ["Leadership", "Rollout"],
                    "suggested_draft": "We are on track and I will send a fuller update by 3pm.",
                    "reasoning": "Leadership follow-up on an ongoing rollout.",
                }
            ),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/11/gmail-analyze", json={"include_labels": True, "include_draft": True})

    assert r.status_code == 200
    payload = r.json()
    assert payload["detected_category"] == "ops"
    assert payload["suggested_labels"] == ["Leadership", "Rollout"]
    assert "on track" in payload["draft_response"]

    check = sqlite3.connect(db_path)
    row = check.execute(
        "SELECT draft_response, analysis_metadata FROM cards WHERE id = 11"
    ).fetchone()
    check.close()
    meta = json.loads(row[1])
    assert "on track" in row[0]
    assert meta["gmail_detected_category"] == "ops"
    assert meta["gmail_suggested_labels"] == ["Leadership", "Rollout"]


@pytest.mark.asyncio
async def test_gmail_auto_label_requires_decision_and_records_labels(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            draft_response TEXT,
            proposed_actions TEXT,
            analysis_metadata TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, summary, draft_response, proposed_actions, analysis_metadata)
           VALUES (
             12,
             'gmail',
             'alerts@example.com: Billing alert',
             '',
             ?,
             ?
           )""",
        [
            json.dumps([{"message_id": "msg-12", "to_email": "alerts@example.com", "subject": "Billing alert"}]),
            json.dumps({"gmail_suggested_labels": ["Finance", "Urgent"]}),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps({"status": "labeled", "labels": ["Finance", "Urgent"], "message_id": "msg-12"}),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.post("/api/cards/12/gmail-auto-label", json={})
        assert blocked.status_code == 400

        decision = await client.post(
            "/api/cards/12/decision",
            json={"action": "gmail-auto-label", "decision": "approved", "rationale": "apply the triage labels"},
        )
        assert decision.status_code == 200

        ok = await client.post(
            "/api/cards/12/gmail-auto-label",
            json={"decision_event_id": decision.json()["decision_event_id"]},
        )

    assert ok.status_code == 200
    assert ok.json()["labels"] == ["Finance", "Urgent"]

    check = sqlite3.connect(db_path)
    meta = json.loads(check.execute("SELECT analysis_metadata FROM cards WHERE id = 12").fetchone()[0])
    check.close()
    assert meta["gmail_applied_labels"] == ["Finance", "Urgent"]


@pytest.mark.asyncio
async def test_archive_email_requires_decision_and_moves_card_to_no_action(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            status TEXT,
            section TEXT,
            proposed_actions TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, summary, status, section, proposed_actions)
           VALUES (13, 'gmail', 'updates@example.com: Weekly digest', 'pending', 'needs-action', ?)""",
        [json.dumps([{"message_id": "msg-13", "to_email": "updates@example.com", "subject": "Weekly digest"}])],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=45: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps({"status": "archived", "message_id": "msg-13"}),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.post("/api/cards/13/archive-email", json={})
        assert blocked.status_code == 400

        decision = await client.post(
            "/api/cards/13/decision",
            json={"action": "archive-email", "decision": "approved", "rationale": "clear the inbox"},
        )
        assert decision.status_code == 200

        ok = await client.post(
            "/api/cards/13/archive-email",
            json={"decision_event_id": decision.json()["decision_event_id"]},
        )

    assert ok.status_code == 200
    assert ok.json()["status"] == "archived"

    check = sqlite3.connect(db_path)
    status, section = check.execute("SELECT status, section FROM cards WHERE id = 13").fetchone()
    check.close()
    assert status == "completed"
    assert section == "no-action"


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


def test_migrate_adds_analysis_metadata_column(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(migrate_module, "DB_PATH", db_path)
    migrate_module.migrate()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()}
    conn.close()

    assert "analysis_metadata" in columns


@pytest.mark.asyncio
async def test_get_suggestions_groups_active_and_held_cards(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            context_notes TEXT,
            analysis_metadata TEXT
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, context_notes, analysis_metadata)
           VALUES (?, 'suggestions', ?, 'Automate triage', 'high', 'pending', '[]', 'automation', 'Why now', ?)""",
        [1, now, json.dumps({"category": "automation", "fingerprint": "aaa", "last_analyzed_at": now, "evidence": ["recurring task"]})],
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, context_notes, analysis_metadata)
           VALUES (?, 'suggestions', ?, 'Document handoff', 'medium', 'held', '[]', 'gap', 'Why now', ?)""",
        [2, now, json.dumps({"category": "gap", "fingerprint": "bbb", "last_analyzed_at": now, "evidence": ["missing runbook"]})],
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, context_notes, analysis_metadata)
           VALUES (?, 'suggestions', ?, 'Old idea', 'low', 'completed', '[]', 'workflow', 'done', ?)""",
        [3, now, json.dumps({"category": "workflow", "fingerprint": "ccc", "last_analyzed_at": now})],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "DB_PATH", db_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/suggestions")

    assert r.status_code == 200
    payload = r.json()
    automation_section = next(section for section in payload["sections"] if section["key"] == "automation")
    workflow_section = next(section for section in payload["sections"] if section["key"] == "workflow")
    assert automation_section["count"] == 1
    assert workflow_section["count"] == 0
    assert payload["held_count"] == 1


@pytest.mark.asyncio
async def test_refresh_suggestions_upserts_without_duplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            execution_status TEXT,
            section TEXT,
            context_notes TEXT,
            analysis_metadata TEXT
        )"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_generate_suggestion_candidates",
        lambda: [
            {
                "summary": "Automate Jira comment drafting",
                "classification": "high",
                "context_notes": "Repeated updates are manual.",
                "section": "automation",
                "proposed_actions": [{"type": "task", "draft": "Create the workflow"}],
                "analysis_metadata": {
                    "category": "automation",
                    "priority": "high",
                    "evidence": ["3 similar updates"],
                    "fingerprint": "same-fingerprint",
                    "generated_from": ["tasks"],
                    "task_draft": {"title": "Automate Jira comments", "priority": "high", "description": "Ship it"},
                    "automation_draft": {"name": "jira-comments"},
                    "open_session_prompt": "Plan the implementation.",
                    "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        ],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/suggestions/refresh")
        second = await client.post("/api/suggestions/refresh")
        listing = await client.get("/api/suggestions")

    assert first.status_code == 200
    assert second.status_code == 200
    assert listing.status_code == 200
    cards = next(section for section in listing.json()["sections"] if section["key"] == "automation")["cards"]
    assert len(cards) == 1
    assert cards[0]["summary"] == "Automate Jira comment drafting"


@pytest.mark.asyncio
async def test_refresh_suggestions_keeps_existing_cards_on_generation_error(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            execution_status TEXT,
            execution_result TEXT,
            section TEXT,
            context_notes TEXT,
            analysis_metadata TEXT
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO cards
           (source, timestamp, summary, classification, status, proposed_actions, execution_status, section, context_notes, analysis_metadata)
           VALUES ('suggestions', ?, 'Existing suggestion', 'high', 'pending', '[]', 'not_run', 'automation', 'Still relevant', ?)""",
        [now, json.dumps({"category": "automation", "fingerprint": "existing-1", "last_analyzed_at": now})],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(
        server,
        "_generate_suggestion_candidates",
        lambda: (_ for _ in ()).throw(RuntimeError("suggestion generation returned invalid JSON")),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refresh = await client.post("/api/suggestions/refresh")
        listing = await client.get("/api/suggestions")

    assert refresh.status_code == 200
    assert refresh.json()["status"] == "error"
    assert listing.status_code == 200
    cards = next(section for section in listing.json()["sections"] if section["key"] == "automation")["cards"]
    assert len(cards) == 1
    assert cards[0]["summary"] == "Existing suggestion"
    check = sqlite3.connect(db_path)
    status, execution_result = check.execute(
        "SELECT status, execution_result FROM cards WHERE source = 'suggestions'"
    ).fetchone()
    check.close()
    assert status == "pending"
    assert execution_result is None


@pytest.mark.asyncio
async def test_approve_suggestion_creates_task_and_automation_draft(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            execution_status TEXT,
            section TEXT,
            context_notes TEXT,
            execution_result TEXT,
            executed_at TEXT,
            analysis_metadata TEXT
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, execution_status, section, context_notes, analysis_metadata)
           VALUES (1, 'suggestions', ?, 'Automate standup prep', 'high', 'pending', '[]', 'not_run', 'automation', 'Repeated prep work', ?)""",
        [
            now,
            json.dumps(
                {
                    "category": "automation",
                    "priority": "high",
                    "evidence": ["daily manual work"],
                    "fingerprint": "auto-1",
                    "generated_from": ["tasks", "knowledge"],
                    "task_draft": {
                        "title": "Automate standup prep",
                        "priority": "high",
                        "description": "Build the automation flow",
                    },
                    "automation_draft": {
                        "name": "standup-prep",
                        "problem": "Standup prep is repeated manually",
                        "proposal": "Create a daily draft generator",
                        "signals": ["morning routine"],
                        "guardrails": ["do not auto-send"],
                    },
                    "open_session_prompt": "Plan the build.",
                    "last_analyzed_at": now,
                }
            ),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "TASKS_FILE", tmp_path / "tasks" / "active-tasks.md")
    monkeypatch.setattr(server, "AUTOMATION_DRAFTS_FILE", tmp_path / "tasks" / "automation-drafts.md")
    monkeypatch.setattr(server, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(server, "CLAUDE_SYNC_FILE", tmp_path / ".runtime" / "claude-sync-events.txt")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decision = await client.post(
            "/api/cards/1/decision",
            json={"action": "approve-suggestion", "decision": "approved", "rationale": "worth doing"},
        )
        assert decision.status_code == 200
        decision_event_id = decision.json()["decision_event_id"]
        r = await client.post(
            "/api/suggestions/1/approve",
            json={"decision_event_id": decision_event_id},
        )

    assert r.status_code == 200
    payload = r.json()
    assert payload["task_number"] == 1
    assert payload["automation_draft_file"].endswith("automation-drafts.md")
    task_text = server.TASKS_FILE.read_text(encoding="utf-8")
    assert "Automate standup prep" in task_text
    draft_text = server.AUTOMATION_DRAFTS_FILE.read_text(encoding="utf-8")
    assert "standup-prep" in draft_text
    sync_text = server.CLAUDE_SYNC_FILE.read_text(encoding="utf-8")
    assert "Dashboard approved suggestion #1 and created Task #1" in sync_text
    assert "active-tasks.md" in sync_text

    check = sqlite3.connect(db_path)
    status = check.execute("SELECT status FROM cards WHERE id = 1").fetchone()[0]
    action_rows = check.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
    check.close()
    assert status == "completed"
    assert action_rows >= 1


@pytest.mark.asyncio
async def test_deny_suggestion_marks_card_held_and_keeps_decision_history(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            timestamp TEXT,
            summary TEXT,
            classification TEXT,
            status TEXT,
            proposed_actions TEXT,
            section TEXT,
            context_notes TEXT,
            analysis_metadata TEXT
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO cards
           (id, source, timestamp, summary, classification, status, proposed_actions, section, context_notes, analysis_metadata)
           VALUES (1, 'suggestions', ?, 'Not now', 'low', 'pending', '[]', 'workflow', 'skip it', ?)""",
        [now, json.dumps({"category": "workflow", "fingerprint": "deny-1", "last_analyzed_at": now})],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "DB_PATH", db_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decision = await client.post(
            "/api/cards/1/decision",
            json={"action": "deny-suggestion", "decision": "rejected", "rationale": "not worth it"},
        )
        assert decision.status_code == 200
        r = await client.post("/api/suggestions/1/deny", json={})

    assert r.status_code == 200
    check = sqlite3.connect(db_path)
    status = check.execute("SELECT status FROM cards WHERE id = 1").fetchone()[0]
    decision_count = check.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
    check.close()
    assert status == "held"
    assert decision_count >= 1


@pytest.mark.asyncio
async def test_open_session_uses_suggestion_prompt_when_available(tmp_path, monkeypatch):
    db_path = tmp_path / "inbox.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            proposed_actions TEXT,
            context_notes TEXT,
            analysis_metadata TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO cards
           (id, source, summary, proposed_actions, context_notes, analysis_metadata)
           VALUES (5, 'suggestions', 'Suggestion session', '[]', 'Because now', ?)""",
        [
            json.dumps(
                {
                    "category": "automation",
                    "fingerprint": "session-1",
                    "evidence": ["signal"],
                    "open_session_prompt": "Walk through the implementation plan in detail.",
                }
            )
        ],
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
    captured = {}
    def fake_launcher(context, launcher_prefix="open-session-", chat_session_id=None):
        captured["context"] = context
        return "/tmp/fake-launcher.sh"
    monkeypatch.setattr(
        server,
        "_launch_terminal_session",
        fake_launcher,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/5/open-session")

    assert r.status_code == 200
    assert "Walk through the implementation plan in detail." in captured["context"]


def test_suggestions_tab_assets_exist():
    index_text = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
    app_text = (Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-source="suggestions"' in index_text
    assert "loadSuggestionsView" in app_text


def test_build_jira_sprint_prompt_targets_systems_board(monkeypatch):
    monkeypatch.setattr(server, "JIRA_USER", "kioja.kudumu@klaviyo.com")
    monkeypatch.setattr(server, "JIRA_BOARD_NAME", "Systems")
    monkeypatch.setattr(server, "JIRA_PROJECT_KEY", "ITWORK2")

    prompt = server._build_jira_sprint_prompt()

    assert "jira_get_agile_boards" in prompt
    assert "board_name='Systems'" in prompt
    assert "project_key='ITWORK2'" in prompt
    assert 'assignee = "kioja.kudumu@klaviyo.com"' in prompt
    assert "project = ITWORK2" in prompt
    assert "sprint = <selected_sprint_id>" in prompt
