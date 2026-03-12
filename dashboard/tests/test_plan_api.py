"""Tests for plan API routes on /api/cards/{card_id}/plan/..."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

import server
from server import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan_dict(card_id: int = 1) -> dict:
    """Return a minimal but valid Plan dict for seeding test fixtures."""
    return {
        "id": f"plan-{card_id}",
        "card_id": card_id,
        "source": "playbook",
        "playbook_id": "test-pb",
        "confidence": 0.9,
        "status": "pending",
        "created_at": "2026-03-10T12:00:00+00:00",
        "executed_at": None,
        "phases": [
            {
                "name": "Setup",
                "steps": [
                    {
                        "index": 1,
                        "summary": "Create ticket",
                        "detail": "Create a Jira ticket",
                        "action_type": "mcp",
                        "tool": "mcp__jira__create_issue",
                        "params": {"project": "ITWORK2"},
                        "param_sources": {},
                        "draft_content": None,
                        "risk": "low",
                        "status": "pending",
                        "output": None,
                    }
                ],
            },
            {
                "name": "Execution",
                "steps": [
                    {
                        "index": 2,
                        "summary": "Assign ticket",
                        "detail": "Assign the created ticket",
                        "action_type": "mcp",
                        "tool": "mcp__jira__update_issue",
                        "params": {},
                        "param_sources": {},
                        "draft_content": None,
                        "risk": "low",
                        "status": "pending",
                        "output": None,
                    },
                    {
                        "index": 3,
                        "summary": "Close ticket",
                        "detail": "Close the ticket",
                        "action_type": "mcp",
                        "tool": "mcp__jira__transition_issue",
                        "params": {},
                        "param_sources": {},
                        "draft_content": None,
                        "risk": "low",
                        "status": "pending",
                        "output": None,
                    },
                ],
            },
        ],
    }


def _seed_plan(plans_dir: Path, db_path: Path, card_id: int = 1) -> dict:
    """Write a plan JSON file and its SQLite index row. Returns the plan dict."""
    plan = _make_plan_dict(card_id)
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{card_id}.json").write_text(json.dumps(plan), encoding="utf-8")

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            card_id INTEGER PRIMARY KEY,
            plan_id TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO plans (card_id, plan_id, source, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (plan["card_id"], plan["id"], plan["source"], plan["status"], plan["created_at"]),
    )
    conn.commit()
    conn.close()
    return plan


def _seed_card(db_path: Path, card_id: int = 1) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY,
            source TEXT,
            summary TEXT,
            context_notes TEXT,
            proposed_actions TEXT,
            draft_response TEXT,
            analysis_metadata TEXT
        )
    """)
    conn.execute(
        """
        INSERT OR REPLACE INTO cards
            (id, source, summary, context_notes, proposed_actions, draft_response, analysis_metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card_id,
            "gmail",
            "RE: Budget approval",
            "From the CFO, due Friday",
            json.dumps([{"type": "send-email", "draft": "Thanks, I'll review today."}]),
            "Thanks, I'll review today.",
            json.dumps({"category": "workflow"}),
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_plan_404_when_none(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards/1/plan")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_plan_returns_plan(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    _seed_plan(plans_dir, db_path, card_id=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards/1/plan")

    assert r.status_code == 200
    body = r.json()
    assert "plan" in body
    assert body["plan"]["card_id"] == 1
    assert body["plan"]["id"] == "plan-1"
    assert len(body["plan"]["phases"]) == 2


@pytest.mark.asyncio
async def test_update_step_approve(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    _seed_plan(plans_dir, db_path, card_id=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/api/cards/1/plan/steps/1", json={"status": "approved"})

    assert r.status_code == 200
    body = r.json()
    assert body["step"]["status"] == "approved"
    assert body["step"]["index"] == 1


@pytest.mark.asyncio
async def test_update_step_edit_draft(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    _seed_plan(plans_dir, db_path, card_id=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            "/api/cards/1/plan/steps/1",
            json={"status": "approved", "draft_content": "new text"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["step"]["status"] == "edited"
    assert body["step"]["draft_content"] == "new text"


@pytest.mark.asyncio
async def test_approve_remaining(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    _seed_plan(plans_dir, db_path, card_id=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/cards/1/plan/approve-remaining",
            json={"from_index": 2},
        )

    assert r.status_code == 200
    body = r.json()
    # Steps 2 and 3 are pending and have index >= 2 → both approved
    assert body["approved_count"] == 2
    assert "plan" in body


@pytest.mark.asyncio
async def test_regenerate(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)

    _seed_plan(plans_dir, db_path, card_id=1)
    _seed_card(db_path, card_id=1)
    plan_file = plans_dir / "1.json"
    assert plan_file.exists()
    claude_payload = {
        "playbook_id": "on-demand/gmail",
        "confidence": 0.7,
        "phases": [
            {
                "name": "Review",
                "steps": [
                    {
                        "summary": "Update the draft",
                        "detail": "Reflect the user's feedback.",
                        "action_type": "manual",
                        "tool": "manual",
                        "params": {},
                        "param_sources": {},
                        "draft_content": "Revised draft",
                        "risk": "low",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps(claude_payload),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/cards/1/plan/regenerate",
            json={"feedback": "Wrong tools"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generated"
    assert body["feedback"] == "Wrong tools"
    assert plan_file.exists()
    assert body["plan"]["card_id"] == 1


@pytest.mark.asyncio
async def test_generate_plan_on_demand(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    db_path = tmp_path / "inbox.db"
    monkeypatch.setattr(server, "PLANS_DIR", str(plans_dir))
    monkeypatch.setattr(server, "DB_PATH", db_path)
    _seed_card(db_path, card_id=7)

    claude_payload = {
        "playbook_id": "on-demand/gmail",
        "confidence": 0.8,
        "phases": [
            {
                "name": "Review",
                "steps": [
                    {
                        "summary": "Review the email and confirm the ask",
                        "detail": "Check due date and recipient.",
                        "action_type": "manual",
                        "tool": "manual",
                        "params": {},
                        "param_sources": {},
                        "draft_content": None,
                        "risk": "low",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        server,
        "_run_claude_print",
        lambda prompt, timeout=60: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=json.dumps(claude_payload),
            stderr="",
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/cards/7/plan/generate", json={})

    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is True
    assert body["plan"]["card_id"] == 7
    assert (plans_dir / "7.json").exists()
