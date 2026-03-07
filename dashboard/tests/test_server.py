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
