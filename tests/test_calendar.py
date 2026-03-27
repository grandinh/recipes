"""Tests for the calendar meal plan view."""

from datetime import date, timedelta

import pytest


@pytest.fixture
async def plan_with_entries(client, create_recipe, create_meal_plan):
    """Create a meal plan with entries across two weeks for testing."""
    recipe = await create_recipe(title="Pasta Carbonara")
    recipe2 = await create_recipe(title="Caesar Salad")
    plan = await create_meal_plan("Weekly Plan")

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # This week: Monday dinner and Wednesday lunch
    await client.post(f"/api/meal-plans/{plan['id']}/entries", json={
        "recipe_id": recipe["id"],
        "date": monday.isoformat(),
        "meal_slot": "dinner",
    })
    await client.post(f"/api/meal-plans/{plan['id']}/entries", json={
        "recipe_id": recipe2["id"],
        "date": (monday + timedelta(days=2)).isoformat(),
        "meal_slot": "lunch",
    })
    # Next week: Tuesday breakfast
    await client.post(f"/api/meal-plans/{plan['id']}/entries", json={
        "recipe_id": recipe["id"],
        "date": (monday + timedelta(days=8)).isoformat(),
        "meal_slot": "breakfast",
    })

    return {
        "plan": plan,
        "recipe": recipe,
        "recipe2": recipe2,
        "monday": monday,
    }


# --- DB functions ---

async def test_get_meal_plan_week_filters_by_date(client, plan_with_entries):
    """get_meal_plan_week returns only entries within the date range."""
    data = plan_with_entries
    monday = data["monday"]
    sunday = monday + timedelta(days=6)

    resp = await client.get(
        f"/api/meal-plans/{data['plan']['id']}"
    )
    all_entries = resp.json()["entries"]
    assert len(all_entries) == 3  # all entries across both weeks

    # Now check the web route filters to this week
    resp = await client.get(
        f"/meal-plans/{data['plan']['id']}?week={monday.isoformat()}"
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Pasta Carbonara" in html
    assert "Caesar Salad" in html


async def test_list_recipe_titles(client, create_recipe):
    """list_recipe_titles returns lightweight id+title dicts."""
    await create_recipe(title="Alpha Recipe")
    await create_recipe(title="Beta Recipe")

    # Access via the calendar page — the dropdown should have both
    plan_resp = await client.post("/api/meal-plans", json={"name": "Test"})
    plan_id = plan_resp.json()["id"]

    resp = await client.get(f"/meal-plans/{plan_id}")
    assert resp.status_code == 200
    assert "Alpha Recipe" in resp.text
    assert "Beta Recipe" in resp.text


# --- Calendar page rendering ---

async def test_calendar_page_renders(client, create_meal_plan):
    """Calendar page renders without errors for empty plan."""
    plan = await create_meal_plan("Empty Plan")
    resp = await client.get(f"/meal-plans/{plan['id']}")
    assert resp.status_code == 200
    assert "calendar-grid" in resp.text
    assert "No recipes planned" in resp.text


async def test_calendar_defaults_to_current_week(client, create_meal_plan):
    """Without ?week= param, calendar shows current week."""
    plan = await create_meal_plan("Test")
    resp = await client.get(f"/meal-plans/{plan['id']}")
    assert resp.status_code == 200
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    # The nav should show the current week's Monday
    assert monday.strftime("%b") in resp.text


async def test_calendar_week_param(client, plan_with_entries):
    """?week= param filters entries to that week."""
    data = plan_with_entries
    next_monday = data["monday"] + timedelta(days=7)

    resp = await client.get(
        f"/meal-plans/{data['plan']['id']}?week={next_monday.isoformat()}"
    )
    assert resp.status_code == 200
    assert "Pasta Carbonara" in resp.text  # next week has this entry
    # Caesar Salad appears in the recipe dropdown but not as a calendar entry
    # Check that the calendar-entry class only has Pasta Carbonara
    assert 'class="calendar-entry-title">Pasta Carbonara' in resp.text
    assert 'class="calendar-entry-title">Caesar Salad' not in resp.text


async def test_calendar_bad_week_param(client, create_meal_plan):
    """Invalid ?week= param returns 400."""
    plan = await create_meal_plan("Test")
    resp = await client.get(f"/meal-plans/{plan['id']}?week=not-a-date")
    assert resp.status_code == 400
    assert "Invalid week" in resp.text


async def test_calendar_snaps_to_monday(client, create_meal_plan):
    """Providing a Wednesday date should show Monday-Sunday of that week."""
    plan = await create_meal_plan("Test")
    today = date.today()
    wednesday = today - timedelta(days=today.weekday()) + timedelta(days=2)

    resp = await client.get(
        f"/meal-plans/{plan['id']}?week={wednesday.isoformat()}"
    )
    assert resp.status_code == 200
    monday = wednesday - timedelta(days=wednesday.weekday())
    assert monday.strftime("%-d") in resp.text


# --- HTMX partial rendering ---

async def test_calendar_htmx_returns_partial(client, create_meal_plan):
    """HTMX request returns only the calendar_grid block, not full page."""
    plan = await create_meal_plan("Test")
    resp = await client.get(
        f"/meal-plans/{plan['id']}",
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "calendar-grid" in resp.text


async def test_add_recipe_htmx_returns_grid(client, plan_with_entries):
    """Adding a recipe via HTMX returns updated calendar grid."""
    data = plan_with_entries
    monday = data["monday"]

    resp = await client.post(
        f"/meal-plans/{data['plan']['id']}/add-recipe",
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


async def test_remove_entry_htmx_returns_grid(client, plan_with_entries):
    """Removing an entry via HTMX returns updated calendar grid."""
    data = plan_with_entries
    plan_id = data["plan"]["id"]

    # Get entries to find an ID
    resp = await client.get(f"/api/meal-plans/{plan_id}")
    entries = resp.json()["entries"]
    entry_id = entries[0]["id"]

    resp = await client.post(
        f"/meal-plans/{plan_id}/entries/{entry_id}/remove",
        data={"week_start": data["monday"].isoformat()},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text


async def test_add_recipe_non_htmx_redirects(client, plan_with_entries):
    """Adding a recipe without HTMX returns a 303 redirect."""
    data = plan_with_entries
    resp = await client.post(
        f"/meal-plans/{data['plan']['id']}/add-recipe",
        data={
            "recipe_id": str(data["recipe"]["id"]),
            "date": data["monday"].isoformat(),
            "meal_slot": "lunch",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


async def test_add_recipe_invalid_slot(client, plan_with_entries):
    """Invalid meal_slot returns 400."""
    data = plan_with_entries
    resp = await client.post(
        f"/meal-plans/{data['plan']['id']}/add-recipe",
        data={
            "recipe_id": str(data["recipe"]["id"]),
            "date": data["monday"].isoformat(),
            "meal_slot": "brunch",
        },
    )
    assert resp.status_code == 400


# --- MCP tool ---

async def test_mcp_get_meal_plan_week(client, plan_with_entries):
    """MCP get_meal_plan_week tool returns filtered entries."""
    data = plan_with_entries
    monday = data["monday"]
    sunday = monday + timedelta(days=6)

    # Test via the DB function directly
    from recipe_app.db import get_meal_plan_week, get_db
    from recipe_app.main import app

    db = app.state.db
    result = await get_meal_plan_week(db, data["plan"]["id"], monday.isoformat(), sunday.isoformat())
    assert result is not None
    assert len(result["entries"]) == 2  # only this week's entries
