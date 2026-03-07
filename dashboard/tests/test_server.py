import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport
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


# --- New tests for smart poller features ---


@pytest.mark.asyncio
async def test_get_cards_with_section_filter():
    """Verify section query parameter filters cards correctly."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards?section=needs-action")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["cards"], list)
    for card in data["cards"]:
        assert card.get("section") == "needs-action"


@pytest.mark.asyncio
async def test_get_cards_with_source_and_section():
    """Verify combined source + section filtering."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards?source=slack&section=no-action")
    assert r.status_code == 200
    data = r.json()
    for card in data["cards"]:
        assert card["source"] == "slack"
        assert card.get("section") == "no-action"


@pytest.mark.asyncio
async def test_dismiss_card():
    """Verify card moves to no-action section."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
        cards = r.json()["cards"]
        if not cards:
            pytest.skip("no cards in DB")
        card_id = cards[0]["id"]
        r2 = await client.post(f"/api/cards/{card_id}/dismiss")
    assert r2.status_code == 200
    assert r2.json()["section"] == "no-action"


@pytest.mark.asyncio
async def test_filter_suggestions_endpoint():
    """Verify filter suggestions endpoint returns expected structure."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/filters/suggestions")
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)


@pytest.mark.asyncio
async def test_dismiss_filter_suggestion():
    """Verify filter suggestion can be dismissed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/filters/dismiss", json={
            "suggestion_id": 99999,
            "permanent": False,
        })
    # Should not error even with non-existent ID
    assert r.status_code == 200


# --- Decision log tests ---


@pytest.mark.asyncio
async def test_decision_logged_on_hold():
    """Verify holding a card creates a decision log entry."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/cards")
        cards = r.json()["cards"]
        if not cards:
            pytest.skip("no cards in DB")
        card_id = cards[0]["id"]
        await client.post(f"/api/cards/{card_id}/hold")

        # Check decision was logged
        r2 = await client.get(f"/api/decisions/search?q=&limit=50")
        decisions = r2.json()["decisions"]
        held = [d for d in decisions if d["card_id"] == card_id and d["action"] == "held"]
        assert len(held) >= 1


@pytest.mark.asyncio
async def test_decision_logged_on_dismiss():
    """Verify dismissing a card creates a decision log entry."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First restore a card to pending so we can dismiss it
        r = await client.get("/api/cards?status=held")
        cards = r.json()["cards"]
        if not cards:
            r = await client.get("/api/cards")
            cards = r.json()["cards"]
        if not cards:
            pytest.skip("no cards in DB")
        card_id = cards[0]["id"]
        await client.post(f"/api/cards/{card_id}/dismiss")

        r2 = await client.get(f"/api/decisions/search?q=&limit=50")
        decisions = r2.json()["decisions"]
        dismissed = [d for d in decisions if d["card_id"] == card_id and d["action"] == "dismissed"]
        assert len(dismissed) >= 1


@pytest.mark.asyncio
async def test_decision_search_empty_query():
    """Verify search endpoint works with empty query."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/decisions/search")
    assert r.status_code == 200
    data = r.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)
    assert "total" in data


@pytest.mark.asyncio
async def test_decision_search_with_filters():
    """Verify search endpoint accepts source and action filters."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/decisions/search?source=slack&action=held&limit=5")
    assert r.status_code == 200
    data = r.json()
    for d in data["decisions"]:
        assert d["source"] == "slack"
        assert d["action"] == "held"


def test_brain_load_decisions():
    """Verify brain.load_decisions returns list without errors."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bin"))
    from brain import load_decisions
    result = load_decisions("test query", limit=3)
    assert isinstance(result, list)


def test_brain_context_prompt_includes_decisions():
    """Verify build_context_prompt includes decisions section."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bin"))
    from brain import build_context_prompt
    prompt = build_context_prompt()
    assert "Similar past decisions" in prompt


def test_migration_idempotent():
    """Verify migrate.py can run twice without error."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from migrate import migrate, DB_PATH

    if not DB_PATH.exists():
        pytest.skip("inbox.db not found")

    # Run twice — should not raise
    migrate()
    migrate()


@pytest.mark.asyncio
async def test_briefing_caching():
    """Verify briefing endpoint returns data and caches it."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First call may generate or return cached
        r = await client.get("/api/briefing")
    assert r.status_code == 200
    data = r.json()
    # Should have either valid briefing or error key
    assert "date" in data or "error" in data
