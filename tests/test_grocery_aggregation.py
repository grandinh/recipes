"""Integration tests for the grocery aggregation pipeline (full DB path)."""

import pytest


async def test_aggregation_sums_quantities(client, create_recipe):
    """Same ingredient across recipes = summed quantity."""
    r1 = await create_recipe(title="Recipe A", ingredients=["2 eggs", "1 cup milk"])
    r2 = await create_recipe(title="Recipe B", ingredients=["3 eggs"])
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r1["id"], r2["id"]]},
    )
    assert resp.status_code == 201
    items = resp.json()["items"]
    egg_items = [i for i in items if "egg" in i["text"].lower()]
    assert len(egg_items) == 1
    assert "5" in egg_items[0]["text"]


async def test_multiplicity_from_calendar(client, create_recipe):
    """Same recipe on two days = double quantities."""
    recipe = await create_recipe(ingredients=["2 eggs"])
    # Add same recipe twice (different days)
    await client.post(
        "/api/calendar/entries",
        json={"recipe_id": recipe["id"], "date": "2026-03-25", "meal_slot": "dinner"},
    )
    await client.post(
        "/api/calendar/entries",
        json={"recipe_id": recipe["id"], "date": "2026-03-26", "meal_slot": "dinner"},
    )
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"date_start": "2026-03-23", "date_end": "2026-03-29"},
    )
    assert resp.status_code == 201
    items = resp.json()["items"]
    egg_items = [i for i in items if "egg" in i["text"].lower()]
    assert len(egg_items) == 1
    assert "4" in egg_items[0]["text"]


async def test_aisle_grouping_in_response(client, create_recipe):
    """Items should have aisle field set."""
    r = await create_recipe(ingredients=["1 lb chicken", "2 tomatoes", "1 cup flour"])
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]]},
    )
    assert resp.status_code == 201
    items = resp.json()["items"]
    aisles = {i["aisle"] for i in items}
    assert "Other" not in aisles or len(aisles) > 1  # at least some recognized


async def test_add_recipe_to_grocery_list(client, create_recipe):
    """Add to grocery list from recipe page creates a new list."""
    r = await create_recipe(ingredients=["2 eggs", "1 cup flour"])
    resp = await client.post(f"/recipes/{r['id']}/add-to-grocery-list", follow_redirects=False)
    assert resp.status_code == 303
    # Follow redirect
    location = resp.headers["location"]
    assert "/grocery-lists/" in location


async def test_empty_calendar_creates_empty_list(client):
    """Empty calendar date range should create an empty grocery list, not error."""
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"date_start": "2099-01-01", "date_end": "2099-01-07"},
    )
    assert resp.status_code == 201
    assert resp.json()["items"] == []


async def test_fk_cleanup_on_recipe_delete(client, create_recipe):
    """Deleting a recipe should NULL out recipe_id in grocery_list_items."""
    r = await create_recipe(ingredients=["2 eggs"])
    # Create grocery list from recipe
    gl_resp = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]]},
    )
    list_id = gl_resp.json()["id"]

    # Delete the recipe
    await client.delete(f"/api/recipes/{r['id']}")

    # Check grocery list items — recipe_id should be NULL
    resp = await client.get(f"/api/grocery-lists/{list_id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    for item in items:
        assert item["recipe_id"] is None


async def test_grocery_detail_page_renders(client, create_recipe):
    """Grocery list detail page should render 200."""
    r = await create_recipe(ingredients=["1 egg"])
    gl = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]]},
    )
    list_id = gl.json()["id"]
    resp = await client.get(f"/grocery-lists/{list_id}")
    assert resp.status_code == 200
    assert "aisle-section" in resp.text


async def test_csp_no_inline_handlers(client, create_recipe):
    """Grocery detail HTML should not contain onchange= (CSP regression)."""
    r = await create_recipe(ingredients=["1 egg"])
    gl = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]]},
    )
    list_id = gl.json()["id"]
    resp = await client.get(f"/grocery-lists/{list_id}")
    assert resp.status_code == 200
    assert "onchange=" not in resp.text


async def test_grocery_date_range_filter(client, create_recipe):
    """Date range filter should only include meals within the range."""
    recipe = await create_recipe(ingredients=["2 eggs"])
    # Add entries on different dates
    await client.post(
        "/api/calendar/entries",
        json={"recipe_id": recipe["id"], "date": "2026-03-25", "meal_slot": "dinner"},
    )
    await client.post(
        "/api/calendar/entries",
        json={"recipe_id": recipe["id"], "date": "2026-03-28", "meal_slot": "dinner"},
    )
    # Generate with date range excluding second entry
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={
            "date_start": "2026-03-25",
            "date_end": "2026-03-26",
        },
    )
    assert resp.status_code == 201
    items = resp.json()["items"]
    egg_items = [i for i in items if "egg" in i["text"].lower()]
    assert len(egg_items) == 1
    assert "2" in egg_items[0]["text"]  # only from one entry


async def test_add_grocery_item_sanitization(client, create_recipe):
    """Manual grocery items should be sanitized."""
    r = await create_recipe()
    gl = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]]},
    )
    list_id = gl.json()["id"]
    resp = await client.post(
        f"/api/grocery-lists/{list_id}/items",
        json={"text": "<script>alert('xss')</script>butter"},
    )
    assert resp.status_code == 201
    assert "<script>" not in resp.json()["text"]


async def test_mcp_add_recipe_to_grocery_list(client):
    """MCP tool add_recipe_to_grocery_list should work."""
    # Create recipe via API first
    r = await client.post("/api/recipes", json={
        "title": "MCP Grocery Test",
        "ingredients": ["2 cups flour", "1 egg"],
    })
    recipe_id = r.json()["id"]

    # Test through MCP
    from tests.test_mcp_server import _parse_result
    from recipe_app.mcp_server import mcp
    from fastmcp import Client

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "add_recipe_to_grocery_list",
            {"recipe_id": recipe_id},
        )
        data = _parse_result(result)
        assert "items" in data
        assert len(data["items"]) >= 1
