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
# Meal Plans
# ---------------------------------------------------------------------------


async def test_mcp_create_meal_plan(mcp_client):
    result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "MCP Plan"}
    )
    data = _parse_result(result)
    assert data["name"] == "MCP Plan"
    assert "id" in data


async def test_mcp_get_meal_plan(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "Get Plan"}
    )
    plan_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool("get_meal_plan", {"plan_id": plan_id})
    data = _parse_result(result)
    assert data["id"] == plan_id
    assert data["name"] == "Get Plan"
    assert "entries" in data


async def test_mcp_update_meal_plan(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "Old Name"}
    )
    plan_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "update_meal_plan", {"plan_id": plan_id, "name": "New Name"}
    )
    data = _parse_result(result)
    assert data["id"] == plan_id
    assert data["name"] == "New Name"


async def test_mcp_list_meal_plans(mcp_client):
    await mcp_client.call_tool("create_meal_plan", {"name": "Plan A"})
    result = await mcp_client.call_tool("list_meal_plans", {})
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    names = [p["name"] for p in data]
    assert "Plan A" in names


async def test_mcp_delete_meal_plan(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "Delete Me"}
    )
    plan_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool("delete_meal_plan", {"plan_id": plan_id})
    data = _parse_result(result)
    assert "deleted" in data.lower()


async def test_mcp_add_and_remove_recipe_from_meal_plan(mcp_client):
    """Add a recipe to a meal plan, then remove the entry."""
    recipe_result = await mcp_client.call_tool(
        "create_recipe", {"title": "Plan Recipe"}
    )
    recipe_id = _parse_result(recipe_result)["id"]

    plan_result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "Entry Plan"}
    )
    plan_id = _parse_result(plan_result)["id"]

    entry_result = await mcp_client.call_tool(
        "add_recipe_to_meal_plan",
        {
            "plan_id": plan_id,
            "recipe_id": recipe_id,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    entry_data = _parse_result(entry_result)
    assert entry_data["recipe_id"] == recipe_id
    entry_id = entry_data["id"]

    # Remove the entry
    remove_result = await mcp_client.call_tool(
        "remove_recipe_from_meal_plan", {"entry_id": entry_id}
    )
    remove_data = _parse_result(remove_result)
    assert "removed" in remove_data.lower()

    # Verify plan is now empty
    plan_data = _parse_result(
        await mcp_client.call_tool("get_meal_plan", {"plan_id": plan_id})
    )
    assert len(plan_data["entries"]) == 0


# ---------------------------------------------------------------------------
# Grocery Lists
# ---------------------------------------------------------------------------


async def test_mcp_generate_grocery_list(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "GL Recipe", "ingredients": ["2 cups flour"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    result = await mcp_client.call_tool(
        "generate_grocery_list", {"recipe_ids": [recipe_id], "name": "MCP List"}
    )
    data = _parse_result(result)
    assert data["name"] == "MCP List"
    assert "items" in data


async def test_mcp_get_grocery_list(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "GL Get Recipe", "ingredients": ["1 egg"]},
    )
    recipe_id = _parse_result(create_result)["id"]

    gen_result = await mcp_client.call_tool(
        "generate_grocery_list", {"recipe_ids": [recipe_id], "name": "Get List"}
    )
    list_id = _parse_result(gen_result)["id"]

    result = await mcp_client.call_tool("get_grocery_list", {"list_id": list_id})
    data = _parse_result(result)
    assert data["id"] == list_id
    assert data["name"] == "Get List"
    assert "items" in data
    assert len(data["items"]) >= 1


async def test_mcp_list_grocery_lists(mcp_client):
    create_result = await mcp_client.call_tool(
        "create_recipe", {"title": "R", "ingredients": ["1 egg"]}
    )
    recipe_id = _parse_result(create_result)["id"]

    await mcp_client.call_tool(
        "generate_grocery_list", {"recipe_ids": [recipe_id]}
    )
    result = await mcp_client.call_tool("list_grocery_lists", {})
    data = _parse_result(result)
    assert isinstance(data, list)
    assert len(data) >= 1


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
    """Create recipe -> meal plan -> add entry -> generate grocery list."""
    recipe_result = await mcp_client.call_tool(
        "create_recipe",
        {"title": "Flow Recipe", "ingredients": ["2 cups flour", "1 egg"]},
    )
    recipe_id = _parse_result(recipe_result)["id"]

    plan_result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "Flow Plan"}
    )
    plan_id = _parse_result(plan_result)["id"]

    await mcp_client.call_tool(
        "add_recipe_to_meal_plan",
        {
            "plan_id": plan_id,
            "recipe_id": recipe_id,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    result = await mcp_client.call_tool(
        "generate_grocery_list", {"meal_plan_id": plan_id, "name": "Flow List"}
    )
    data = _parse_result(result)
    assert data["name"] == "Flow List"
    assert "items" in data
    assert len(data["items"]) >= 1
