"""Tests for MCP server tools via fastmcp in-memory Client."""

import json

import pytest_asyncio
from fastmcp import Client

from recipe_app.mcp_server import mcp
from recipe_app import mcp_server as mcp_mod


def _parse_result(result):
    """Extract structured data from MCP tool result."""
    if not result:
        return None
    # When a tool returns an empty list, fastmcp may produce empty content
    # but populate structured_content with the actual data.
    if not result.content:
        sc = getattr(result, "structured_content", None)
        if sc is not None and "result" in sc:
            return sc["result"]
        return None
    item = result.content[0]
    text = item.text if hasattr(item, "text") else str(item)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


@pytest_asyncio.fixture
async def mcp_client(tmp_path, monkeypatch):
    """MCP client backed by a per-test temp database."""
    db_path = str(tmp_path / "mcp_test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)
    from recipe_app.config import settings

    monkeypatch.setattr(settings, "database_path", db_path)
    # Defensive close before reset
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
    mcp_mod._db = None
    # Reset cached global grocery list ID (each test gets a fresh DB)
    import recipe_app.db as db_mod
    db_mod._cached_global_list_id = None
    async with Client(mcp) as client:
        yield client
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


async def test_mcp_list_tools(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = {t.name for t in tools}
    assert "search_recipes" in tool_names
    assert "create_recipe" in tool_names
    assert "find_recipes_from_pantry" in tool_names
    assert len(tool_names) >= 24


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------


async def test_mcp_create_recipe(mcp_client):
    result = await mcp_client.call_tool(
        "create_recipe", {"title": "MCP Tacos", "cuisine": "Mexican"}
    )
    data = _parse_result(result)
    assert data["title"] == "MCP Tacos"
    assert data["cuisine"] == "Mexican"
    assert "id" in data


async def test_mcp_get_recipe(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Get Me", "cuisine": "Thai"}
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool("get_recipe", {"recipe_id": recipe_id})
    data = _parse_result(result)
    assert data["id"] == recipe_id
    assert data["title"] == "Get Me"
    assert data["cuisine"] == "Thai"


async def test_mcp_update_recipe(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Before Update", "cuisine": "Italian"}
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "update_recipe",
        {"recipe_id": recipe_id, "title": "After Update", "cuisine": "French"},
    )
    data = _parse_result(result)
    assert data["id"] == recipe_id
    assert data["title"] == "After Update"
    assert data["cuisine"] == "French"


async def test_mcp_search_recipes(mcp_client):
    await mcp_client.call_tool("create_recipe", {"title": "Search Target"})
    result = await mcp_client.call_tool("search_recipes", {"query": "Search Target"})
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["title"] == "Search Target"


async def test_mcp_get_recipe_not_found(mcp_client):
    result = await mcp_client.call_tool("get_recipe", {"recipe_id": 99999})
    data = _parse_result(result)
    assert data is None


async def test_mcp_delete_recipe(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe", {"title": "To Delete"}
    )
    recipe_id = _parse_result(create_result)["id"]

    await mcp_client.call_tool("delete_recipe", {"recipe_id": recipe_id})
    result = await mcp_client.call_tool("get_recipe", {"recipe_id": recipe_id})
    data = _parse_result(result)
    assert data is None


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


async def test_mcp_create_category(mcp_client):
    result = await mcp_client.call_tool("create_category", {"name": "Italian"})
    data = _parse_result(result)
    assert data["name"] == "Italian"
    assert "id" in data


async def test_mcp_list_categories(mcp_client):
    await mcp_client.call_tool("create_category", {"name": "Mexican"})
    result = await mcp_client.call_tool("list_categories", {})
    data = _parse_result(result)
    assert isinstance(data, list)
    names = [c["name"] for c in data]
    assert "Mexican" in names


async def test_mcp_delete_category(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_category", {"name": "ToDelete"}
    )
    cat_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool("delete_category", {"category_id": cat_id})
    data = _parse_result(result)
    assert "deleted" in data.lower()

    # Verify it's gone
    list_result = await mcp_client.call_tool("list_categories", {})
    categories = _parse_result(list_result)
    names = [c["name"] for c in categories]
    assert "ToDelete" not in names


# ---------------------------------------------------------------------------
# Scaling (MCP-only feature)
# ---------------------------------------------------------------------------


async def test_mcp_scale_recipe(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "Scalable", "ingredients": ["2 cups flour", "1 cup milk"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "scale_recipe", {"recipe_id": recipe_id, "multiplier": 2.0}
    )
    data = _parse_result(result)
    assert data["multiplier"] == 2.0
    assert data["recipe_id"] == recipe_id
    assert data["title"] == "Scalable"
    assert "scaled_ingredients" in data


async def test_mcp_scale_recipe_no_ingredients(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Empty"}
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "scale_recipe", {"recipe_id": recipe_id, "multiplier": 2.0}
    )
    data = _parse_result(result)
    assert "error" in data


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


async def test_mcp_add_to_calendar(mcp_client):
    recipe_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Calendar Recipe"}
    )
    recipe_id = _parse_result(recipe_result)["id"]

    result = await mcp_client.call_tool(
        "add_to_calendar",
        {"recipe_id": recipe_id, "date": "2026-03-25", "meal_slot": "dinner"},
    )
    data = _parse_result(result)
    assert data["recipe_id"] == recipe_id
    assert data["recipe_title"] == "Calendar Recipe"
    assert data["meal_slot"] == "dinner"
    assert "id" in data


async def test_mcp_get_calendar_week(mcp_client):
    recipe_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Week Recipe"}
    )
    recipe_id = _parse_result(recipe_result)["id"]

    await mcp_client.call_tool(
        "add_to_calendar",
        {"recipe_id": recipe_id, "date": "2026-03-25", "meal_slot": "dinner"},
    )

    result = await mcp_client.call_tool(
        "get_calendar_week", {"date": "2026-03-25"}
    )
    data = _parse_result(result)
    assert "entries" in data
    assert len(data["entries"]) >= 1


async def test_mcp_add_to_calendar_batch(mcp_client):
    recipe_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Batch Recipe"}
    )
    recipe_id = _parse_result(recipe_result)["id"]

    result = await mcp_client.call_tool(
        "add_to_calendar_batch",
        {
            "entries": [
                {"recipe_id": recipe_id, "date": "2026-03-25", "meal_slot": "breakfast"},
                {"recipe_id": recipe_id, "date": "2026-03-26", "meal_slot": "lunch"},
            ]
        },
    )
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) == 2


async def test_mcp_remove_from_calendar(mcp_client):
    """Add a recipe to calendar, then remove it."""
    recipe_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Remove Recipe"}
    )
    recipe_id = _parse_result(recipe_result)["id"]

    entry_result = await mcp_client.call_tool(
        "add_to_calendar",
        {"recipe_id": recipe_id, "date": "2026-03-25", "meal_slot": "dinner"},
    )
    entry_id = _parse_result(entry_result)["id"]

    remove_result = await mcp_client.call_tool(
        "remove_from_calendar", {"entry_id": entry_id}
    )
    remove_data = _parse_result(remove_result)
    assert "removed" in remove_data.lower()

    # Verify calendar is now empty for that week
    week_data = _parse_result(
        await mcp_client.call_tool("get_calendar_week", {"date": "2026-03-25"})
    )
    assert len(week_data["entries"]) == 0


# ---------------------------------------------------------------------------
# Grocery List (single global list)
# ---------------------------------------------------------------------------


async def test_mcp_get_grocery_list(mcp_client):
    """Global list starts empty."""
    result = await mcp_client.call_tool("get_grocery_list", {})
    data = _parse_result(result)
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_mcp_add_grocery_item(mcp_client):
    result = await mcp_client.call_tool(
        "add_grocery_item", {"name": "Butter"}
    )
    data = _parse_result(result)
    assert data["text"] == "Butter"
    assert data["aisle"] is not None


async def test_mcp_add_recipe_to_grocery_list(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "GL Recipe", "ingredients": ["2 cups flour", "1 egg"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "add_recipe_to_grocery_list", {"recipe_id": recipe_id}
    )
    data = _parse_result(result)
    assert data["items_added"] >= 1
    assert data["recipe_title"] == "GL Recipe"


async def test_mcp_preview_grocery_additions(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "Preview Recipe", "ingredients": ["1 egg"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "preview_grocery_additions", {"recipe_id": recipe_id}
    )
    data = _parse_result(result)
    assert data["recipe_title"] == "Preview Recipe"
    assert len(data["items"]) >= 1


async def test_mcp_generate_grocery_list_from_calendar(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "Cal Recipe", "ingredients": ["2 cups flour"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    await mcp_client.call_tool(
        "add_to_calendar",
        {"recipe_id": recipe_id, "date": "2026-03-25", "meal_slot": "dinner"},
    )

    result = await mcp_client.call_tool(
        "generate_grocery_list_from_calendar",
        {"start": "2026-03-23", "end": "2026-03-29"},
    )
    data = _parse_result(result)
    assert data["items_added"] >= 1


# ---------------------------------------------------------------------------
# Pantry
# ---------------------------------------------------------------------------


async def test_mcp_add_pantry_item(mcp_client):
    result = await mcp_client.call_tool(
        "add_pantry_item", {"name": "MCP Flour", "quantity": 2.0, "unit": "lbs"}
    )
    data = _parse_result(result)
    assert data["name"] == "MCP Flour"
    assert data["quantity"] == 2.0
    assert data["unit"] == "lbs"
    assert "id" in data


async def test_mcp_update_pantry_item(mcp_client):
    create_result = await mcp_client.call_tool(
        "add_pantry_item", {"name": "Sugar", "quantity": 1.0, "unit": "lbs"}
    )
    item_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "update_pantry_item",
        {"item_id": item_id, "quantity": 5.0, "unit": "kg"},
    )
    data = _parse_result(result)
    assert data["id"] == item_id
    assert data["name"] == "Sugar"
    assert data["quantity"] == 5.0
    assert data["unit"] == "kg"


async def test_mcp_list_pantry_items(mcp_client):
    await mcp_client.call_tool("add_pantry_item", {"name": "Eggs"})
    result = await mcp_client.call_tool("list_pantry_items", {})
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    names = [item["name"] for item in data]
    assert "Eggs" in names


async def test_mcp_delete_pantry_item(mcp_client):
    create_result = await mcp_client.call_tool(
        "add_pantry_item", {"name": "Delete Me"}
    )
    item_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool("delete_pantry_item", {"item_id": item_id})
    data = _parse_result(result)
    assert "deleted" in data.lower()


async def test_mcp_find_recipes_from_pantry_empty(mcp_client):
    result = await mcp_client.call_tool(
        "find_recipes_from_pantry", {"max_missing": 2}
    )
    data = _parse_result(result)
    # Empty pantry -> empty results
    assert data == []


# ---------------------------------------------------------------------------
# Cross-tool workflow
# ---------------------------------------------------------------------------


async def test_mcp_recipe_to_grocery_list_flow(mcp_client):
    """Create recipe -> add to calendar -> generate grocery items."""
    recipe_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "Flow Recipe", "ingredients": ["2 cups flour", "1 egg"]},
    )
    recipe_id = _parse_result(recipe_result)["id"]

    await mcp_client.call_tool(
        "add_to_calendar",
        {
            "recipe_id": recipe_id,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    result = await mcp_client.call_tool(
        "generate_grocery_list_from_calendar",
        {"start": "2026-03-23", "end": "2026-03-29"},
    )
    data = _parse_result(result)
    assert data["items_added"] >= 1
    assert "items" in data


# ---------------------------------------------------------------------------
# Grocery Item Management (delete, clear, move)
# ---------------------------------------------------------------------------


async def test_mcp_delete_grocery_item(mcp_client):
    recipe = await mcp_client.call_tool(
        "create_recipe", {"title": "R", "ingredients": ["1 egg"]}
    )
    recipe_id = _parse_result(recipe)["id"]
    await mcp_client.call_tool(
        "add_recipe_to_grocery_list", {"recipe_id": recipe_id}
    )
    glist = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))
    item_id = glist["items"][0]["id"]

    result = _parse_result(await mcp_client.call_tool("delete_grocery_item", {"item_id": item_id}))
    assert "deleted" in result.lower()

    # Verify item is gone
    glist2 = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))
    item_ids = [i["id"] for i in glist2["items"]]
    assert item_id not in item_ids


async def test_mcp_delete_grocery_item_not_found(mcp_client):
    result = _parse_result(await mcp_client.call_tool("delete_grocery_item", {"item_id": 99999}))
    assert "not found" in result.lower()


async def test_mcp_clear_bought_items(mcp_client):
    recipe = await mcp_client.call_tool(
        "create_recipe", {"title": "R", "ingredients": ["1 egg", "2 cups flour"]}
    )
    recipe_id = _parse_result(recipe)["id"]
    await mcp_client.call_tool(
        "add_recipe_to_grocery_list", {"recipe_id": recipe_id}
    )
    glist = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))
    item_id = glist["items"][0]["id"]

    # Check one item
    await mcp_client.call_tool("check_grocery_item", {"item_id": item_id, "is_checked": True})

    # Clear checked
    result = _parse_result(await mcp_client.call_tool("clear_bought_items", {}))
    assert result["cleared_count"] == 1

    # Verify one item was removed
    glist2 = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))
    assert len(glist2["items"]) == len(glist["items"]) - 1


async def test_mcp_move_checked_to_pantry(mcp_client):
    """Full workflow: add recipe to grocery -> check items -> move to pantry."""
    recipe = await mcp_client.call_tool(
        "create_recipe", {"title": "R", "ingredients": ["1 egg", "2 cups flour"]}
    )
    recipe_id = _parse_result(recipe)["id"]
    await mcp_client.call_tool(
        "add_recipe_to_grocery_list", {"recipe_id": recipe_id}
    )
    glist = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))

    # Check all items
    for item in glist["items"]:
        await mcp_client.call_tool("check_grocery_item", {"item_id": item["id"], "is_checked": True})

    # Move to pantry
    result = _parse_result(await mcp_client.call_tool("move_checked_to_pantry", {}))
    assert len(result["moved"]) > 0
    assert isinstance(result["already_in_pantry"], list)

    # Verify pantry has items
    pantry = _parse_result(await mcp_client.call_tool("list_pantry_items", {}))
    assert len(pantry) > 0

    # Verify grocery list is empty
    glist2 = _parse_result(await mcp_client.call_tool("get_grocery_list", {}))
    assert len(glist2["items"]) == 0


# ---------------------------------------------------------------------------
# Pantry sanitization
# ---------------------------------------------------------------------------


async def test_mcp_pantry_sanitizes_html(mcp_client):
    """Verify that dangerous HTML in pantry names is stripped."""
    result = await mcp_client.call_tool(
        "add_pantry_item", {"name": "<script>alert(1)</script>Flour", "category": "<script>x</script>Baking"}
    )
    data = _parse_result(result)
    assert "<script>" not in data["name"]
    assert "Flour" in data["name"]
    assert "<script>" not in data["category"]
    assert "Baking" in data["category"]


# ---------------------------------------------------------------------------
# Photo upload
# ---------------------------------------------------------------------------


async def test_mcp_upload_recipe_photo(mcp_client):
    """Upload a valid photo via MCP tool."""
    import base64
    from PIL import Image
    import io

    # Create a small test image
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    b64_data = base64.b64encode(buf.getvalue()).decode()

    recipe = await mcp_client.call_tool("create_recipe", {"title": "Photo Recipe"})
    recipe_id = _parse_result(recipe)["id"]

    result = _parse_result(
        await mcp_client.call_tool(
            "upload_recipe_photo",
            {"recipe_id": recipe_id, "image_base64": b64_data},
        )
    )
    assert result["recipe_id"] == recipe_id
    assert result["photo_path"].endswith(".jpg")


async def test_mcp_upload_recipe_photo_not_found(mcp_client):
    result = _parse_result(
        await mcp_client.call_tool(
            "upload_recipe_photo",
            {"recipe_id": 99999, "image_base64": "dGVzdA=="},
        )
    )
    assert "error" in result


async def test_mcp_upload_recipe_photo_invalid_base64(mcp_client):
    recipe = await mcp_client.call_tool("create_recipe", {"title": "Bad Photo"})
    recipe_id = _parse_result(recipe)["id"]
    result = _parse_result(
        await mcp_client.call_tool(
            "upload_recipe_photo",
            {"recipe_id": recipe_id, "image_base64": "not-valid-base64!!!"},
        )
    )
    assert "error" in result
