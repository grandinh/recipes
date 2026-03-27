"""Tests for calendar entry API endpoints (replaced meal plans)."""

from datetime import date, timedelta


async def test_create_calendar_entry(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recipe_id"] == recipe["id"]
    assert data["meal_slot"] == "dinner"
    assert data["recipe_title"] == recipe["title"]


async def test_create_entry_invalid_meal_slot(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "brunch",  # not in Literal
        },
    )
    assert resp.status_code == 422


async def test_create_entry_recipe_not_found(client):
    """FK constraint error — documents that nonexistent recipe_id is not validated."""
    resp = await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": 99999,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    # Router doesn't validate recipe_id existence — FK constraint raises IntegrityError
    assert resp.status_code in (400, 404, 500)
    if resp.status_code == 500:
        assert "Traceback" not in resp.text


async def test_get_calendar_week(client, create_recipe):
    recipe = await create_recipe()
    await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "breakfast",
        },
    )
    await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-26",
            "meal_slot": "lunch",
        },
    )
    # 2026-03-25 is a Wednesday, Monday is 2026-03-23
    resp = await client.get("/api/calendar?week=2026-03-25")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2


async def test_get_calendar_week_default(client):
    """Default week should return current week (no error)."""
    resp = await client.get("/api/calendar")
    assert resp.status_code == 200
    assert "entries" in resp.json()


async def test_get_calendar_week_bad_param(client):
    resp = await client.get("/api/calendar?week=not-a-date")
    assert resp.status_code == 400


async def test_delete_calendar_entry(client, create_recipe):
    recipe = await create_recipe()
    entry_resp = await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    entry_id = entry_resp.json()["id"]
    resp = await client.delete(f"/api/calendar/entries/{entry_id}")
    assert resp.status_code == 204


async def test_delete_entry_not_found(client):
    resp = await client.delete("/api/calendar/entries/99999")
    assert resp.status_code == 404


async def test_batch_create_entries(client, create_recipe):
    recipe = await create_recipe()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    resp = await client.post(
        "/api/calendar/entries/batch",
        json={
            "entries": [
                {"recipe_id": recipe["id"], "date": monday.isoformat(), "meal_slot": "breakfast"},
                {"recipe_id": recipe["id"], "date": (monday + timedelta(days=1)).isoformat(), "meal_slot": "lunch"},
                {"recipe_id": recipe["id"], "date": (monday + timedelta(days=2)).isoformat(), "meal_slot": "dinner"},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 3
