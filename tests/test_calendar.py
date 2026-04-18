"""Tests for the global calendar view."""

from datetime import date, timedelta

import pytest


@pytest.fixture
async def calendar_with_entries(client, create_recipe):
    """Create calendar entries across two weeks for testing."""
    recipe = await create_recipe(title="Pasta Carbonara")
    recipe2 = await create_recipe(title="Caesar Salad")

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # This week: Monday dinner and Wednesday lunch
    await client.post("/api/calendar/entries", json={
        "recipe_id": recipe["id"],
        "date": monday.isoformat(),
        "meal_slot": "dinner",
    })
    await client.post("/api/calendar/entries", json={
        "recipe_id": recipe2["id"],
        "date": (monday + timedelta(days=2)).isoformat(),
        "meal_slot": "lunch",
    })
    # Next week: Tuesday breakfast
    await client.post("/api/calendar/entries", json={
        "recipe_id": recipe["id"],
        "date": (monday + timedelta(days=8)).isoformat(),
        "meal_slot": "breakfast",
    })

    return {
        "recipe": recipe,
        "recipe2": recipe2,
        "monday": monday,
    }


# --- DB functions ---

async def test_get_calendar_week_filters_by_date(client, calendar_with_entries):
    """get_calendar_week returns only entries within the date range."""
    data = calendar_with_entries
    monday = data["monday"]

    # All entries across both weeks via the week API
    resp = await client.get(f"/api/calendar?week={monday.isoformat()}")
    this_week_entries = resp.json()["entries"]
    assert len(this_week_entries) == 2  # only this week

    # Next week should have 1
    next_monday = monday + timedelta(days=7)
    resp = await client.get(f"/api/calendar?week={next_monday.isoformat()}")
    next_week_entries = resp.json()["entries"]
    assert len(next_week_entries) == 1


async def test_list_recipe_titles(client, create_recipe):
    """list_recipe_titles returns lightweight id+title dicts."""
    await create_recipe(title="Alpha Recipe")
    await create_recipe(title="Beta Recipe")

    # Access via the calendar page — the dropdown should have both
    resp = await client.get("/calendar")
    assert resp.status_code == 200
    assert "Alpha Recipe" in resp.text
    assert "Beta Recipe" in resp.text


# --- Calendar page rendering ---

async def test_calendar_page_renders(client):
    """Calendar page renders without errors when empty."""
    resp = await client.get("/calendar")
    assert resp.status_code == 200
    assert "calendar-grid" in resp.text
    assert "No recipes planned" in resp.text


async def test_calendar_defaults_to_current_week(client):
    """Without ?week= param, calendar shows current week."""
    resp = await client.get("/calendar")
    assert resp.status_code == 200
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    # The nav should show the current week's Monday
    assert monday.strftime("%b") in resp.text


async def test_calendar_week_param(client, calendar_with_entries):
    """?week= param filters entries to that week."""
    data = calendar_with_entries
    next_monday = data["monday"] + timedelta(days=7)

    resp = await client.get(f"/calendar?week={next_monday.isoformat()}")
    assert resp.status_code == 200
    # Pasta Carbonara should appear as a calendar entry (not just in the add-recipe <select>)
    assert 'class="calendar-entry"' in resp.text
    assert "Pasta Carbonara</a>" in resp.text
    # Caesar Salad is on the prior week — shouldn't appear as a calendar-entry link,
    # but may still show in the add-recipe <option> list, so check it's not linked as an entry
    assert "Caesar Salad</a>" not in resp.text


async def test_calendar_bad_week_param(client):
    """Invalid ?week= param returns 400."""
    resp = await client.get("/calendar?week=not-a-date")
    assert resp.status_code == 400
    assert "Invalid week" in resp.text


async def test_calendar_snaps_to_monday(client):
    """Providing a Wednesday date should show Monday-Sunday of that week."""
    today = date.today()
    wednesday = today - timedelta(days=today.weekday()) + timedelta(days=2)

    resp = await client.get(f"/calendar?week={wednesday.isoformat()}")
    assert resp.status_code == 200
    monday = wednesday - timedelta(days=wednesday.weekday())
    assert monday.strftime("%-d") in resp.text


# --- HTMX partial rendering ---

async def test_calendar_htmx_returns_partial(client):
    """HTMX request returns only the calendar_grid block, not full page."""
    resp = await client.get(
        "/calendar",
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "calendar-grid" in resp.text


async def test_add_recipe_htmx_returns_grid(client, calendar_with_entries):
    """Adding a recipe via HTMX returns updated calendar grid."""
    data = calendar_with_entries
    monday = data["monday"]

    resp = await client.post(
        "/calendar/add-recipe",
        data={
            "recipe_id": str(data["recipe"]["id"]),
            "date": monday.isoformat(),
            "meal_slot": "breakfast",
        },
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "Pasta Carbonara" in resp.text


async def test_remove_entry_htmx_returns_grid(client, calendar_with_entries):
    """Removing an entry via HTMX returns updated calendar grid."""
    data = calendar_with_entries
    monday = data["monday"]

    # Get entries to find an ID
    resp = await client.get(f"/api/calendar?week={monday.isoformat()}")
    entries = resp.json()["entries"]
    entry_id = entries[0]["id"]

    resp = await client.post(
        f"/calendar/entries/{entry_id}/remove",
        data={"week_start": monday.isoformat()},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text


async def test_add_recipe_non_htmx_redirects(client, calendar_with_entries):
    """Adding a recipe without HTMX returns a 303 redirect."""
    data = calendar_with_entries
    resp = await client.post(
        "/calendar/add-recipe",
        data={
            "recipe_id": str(data["recipe"]["id"]),
            "date": data["monday"].isoformat(),
            "meal_slot": "lunch",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


async def test_add_recipe_invalid_slot(client, calendar_with_entries):
    """Invalid meal_slot returns 400."""
    data = calendar_with_entries
    resp = await client.post(
        "/calendar/add-recipe",
        data={
            "recipe_id": str(data["recipe"]["id"]),
            "date": data["monday"].isoformat(),
            "meal_slot": "brunch",
        },
    )
    assert resp.status_code == 400


# --- API endpoints ---

async def test_api_create_entry(client, create_recipe):
    """POST /api/calendar/entries creates a calendar entry."""
    recipe = await create_recipe(title="Test Recipe")
    today = date.today()

    resp = await client.post("/api/calendar/entries", json={
        "recipe_id": recipe["id"],
        "date": today.isoformat(),
        "meal_slot": "dinner",
    })
    assert resp.status_code == 201
    entry = resp.json()
    assert entry["recipe_id"] == recipe["id"]
    assert entry["recipe_title"] == "Test Recipe"
    assert entry["meal_slot"] == "dinner"


async def test_api_delete_entry(client, calendar_with_entries):
    """DELETE /api/calendar/entries/{id} removes an entry."""
    data = calendar_with_entries
    monday = data["monday"]

    resp = await client.get(f"/api/calendar?week={monday.isoformat()}")
    entries = resp.json()["entries"]
    entry_id = entries[0]["id"]

    resp = await client.delete(f"/api/calendar/entries/{entry_id}")
    assert resp.status_code == 204


async def test_api_delete_nonexistent_entry(client):
    """DELETE nonexistent entry returns 404."""
    resp = await client.delete("/api/calendar/entries/99999")
    assert resp.status_code == 404


async def test_api_batch_create(client, create_recipe):
    """POST /api/calendar/entries/batch creates multiple entries."""
    recipe = await create_recipe(title="Batch Recipe")
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    resp = await client.post("/api/calendar/entries/batch", json={
        "entries": [
            {"recipe_id": recipe["id"], "date": monday.isoformat(), "meal_slot": "breakfast"},
            {"recipe_id": recipe["id"], "date": (monday + timedelta(days=1)).isoformat(), "meal_slot": "lunch"},
        ],
    })
    assert resp.status_code == 201
    created = resp.json()
    assert len(created) == 2


# --- MCP tool ---

async def test_mcp_get_calendar_week(client, calendar_with_entries):
    """DB get_calendar_week returns filtered entries."""
    data = calendar_with_entries
    monday = data["monday"]
    sunday = monday + timedelta(days=6)

    from recipe_app.db import get_calendar_week
    from recipe_app.main import app

    db = app.state.db
    result = await get_calendar_week(db, monday.isoformat(), sunday.isoformat())
    assert len(result["entries"]) == 2  # only this week's entries
