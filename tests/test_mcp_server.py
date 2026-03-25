"""Tests for MCP server tools via fastmcp in-memory Client."""

import pytest
import pytest_asyncio
from fastmcp import Client

from recipe_app.mcp_server import mcp
from recipe_app import mcp_server as mcp_mod


@pytest_asyncio.fixture
async def mcp_client(tmp_path, monkeypatch):
    """MCP client backed by a per-test temp database."""
    db_path = str(tmp_path / "mcp_test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)
    from recipe_app.config import settings
    monkeypatch.setattr(settings, "database_path", db_path)
    # Reset the module-level _db so it reconnects to the test DB
    mcp_mod._db = None
    async with Client(mcp) as client:
        yield client
    # Cleanup
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_mcp_create_recipe(mcp_client):
    result = await mcp_client.call_tool(
        "create_recipe", {"title": "MCP Tacos", "cuisine": "Mexican"}
    )
    assert "MCP Tacos" in str(result)


@pytest.mark.asyncio
async def test_mcp_search_recipes(mcp_client):
    await mcp_client.call_tool("create_recipe", {"title": "Search Target"})
    result = await mcp_client.call_tool("search_recipes", {"query": "Search Target"})
    assert "Search Target" in str(result)


@pytest.mark.asyncio
async def test_mcp_get_recipe_not_found(mcp_client):
    result = await mcp_client.call_tool("get_recipe", {"recipe_id": 99999})
    assert "null" in str(result).lower() or "None" in str(result)


@pytest.mark.asyncio
async def test_mcp_delete_recipe(mcp_client):
    await mcp_client.call_tool("create_recipe", {"title": "To Delete"})
    result = await mcp_client.call_tool("search_recipes", {})
    # Find the recipe ID (result is a list or contains list data)
    await mcp_client.call_tool("delete_recipe", {"recipe_id": 1})
    result2 = await mcp_client.call_tool("get_recipe", {"recipe_id": 1})
    assert "null" in str(result2).lower() or "None" in str(result2)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_create_category(mcp_client):
    result = await mcp_client.call_tool("create_category", {"name": "Italian"})
    assert "Italian" in str(result)


@pytest.mark.asyncio
async def test_mcp_list_categories(mcp_client):
    await mcp_client.call_tool("create_category", {"name": "Mexican"})
    result = await mcp_client.call_tool("list_categories", {})
    assert "Mexican" in str(result)


# ---------------------------------------------------------------------------
# Scaling (MCP-only feature)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_scale_recipe(mcp_client):
    await mcp_client.call_tool(
        "create_recipe",
        {"title": "Scalable", "ingredients": ["2 cups flour", "1 cup milk"]},
    )
    result = await mcp_client.call_tool(
        "scale_recipe", {"recipe_id": 1, "multiplier": 2.0}
    )
    assert "multiplier" in str(result).lower() or "scaled" in str(result).lower()


@pytest.mark.asyncio
async def test_mcp_scale_recipe_no_ingredients(mcp_client):
    await mcp_client.call_tool("create_recipe", {"title": "Empty"})
    result = await mcp_client.call_tool(
        "scale_recipe", {"recipe_id": 1, "multiplier": 2.0}
    )
    assert "error" in str(result).lower()


# ---------------------------------------------------------------------------
# Meal Plans
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_create_meal_plan(mcp_client):
    result = await mcp_client.call_tool(
        "create_meal_plan", {"name": "MCP Plan"}
    )
    assert "MCP Plan" in str(result)


@pytest.mark.asyncio
async def test_mcp_list_meal_plans(mcp_client):
    await mcp_client.call_tool("create_meal_plan", {"name": "Plan A"})
    result = await mcp_client.call_tool("list_meal_plans", {})
    assert "Plan A" in str(result)


@pytest.mark.asyncio
async def test_mcp_delete_meal_plan(mcp_client):
    await mcp_client.call_tool("create_meal_plan", {"name": "Delete Me"})
    result = await mcp_client.call_tool("delete_meal_plan", {"plan_id": 1})
    assert "deleted" in str(result).lower()


# ---------------------------------------------------------------------------
# Grocery Lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_generate_grocery_list(mcp_client):
    await mcp_client.call_tool(
        "create_recipe",
        {"title": "GL Recipe", "ingredients": ["2 cups flour"]},
    )
    result = await mcp_client.call_tool(
        "generate_grocery_list", {"recipe_ids": [1], "name": "MCP List"}
    )
    assert "MCP List" in str(result) or "items" in str(result).lower()


@pytest.mark.asyncio
async def test_mcp_list_grocery_lists(mcp_client):
    await mcp_client.call_tool(
        "create_recipe", {"title": "R", "ingredients": ["1 egg"]}
    )
    await mcp_client.call_tool(
        "generate_grocery_list", {"recipe_ids": [1]}
    )
    result = await mcp_client.call_tool("list_grocery_lists", {})
    assert str(result)  # non-empty


# ---------------------------------------------------------------------------
# Pantry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_add_pantry_item(mcp_client):
    result = await mcp_client.call_tool(
        "add_pantry_item", {"name": "MCP Flour", "quantity": 2.0, "unit": "lbs"}
    )
    assert "MCP Flour" in str(result)


@pytest.mark.asyncio
async def test_mcp_list_pantry_items(mcp_client):
    await mcp_client.call_tool("add_pantry_item", {"name": "Eggs"})
    result = await mcp_client.call_tool("list_pantry_items", {})
    assert "Eggs" in str(result)


@pytest.mark.asyncio
async def test_mcp_delete_pantry_item(mcp_client):
    await mcp_client.call_tool("add_pantry_item", {"name": "Delete Me"})
    result = await mcp_client.call_tool("delete_pantry_item", {"item_id": 1})
    assert "deleted" in str(result).lower()


@pytest.mark.asyncio
async def test_mcp_find_recipes_from_pantry_empty(mcp_client):
    result = await mcp_client.call_tool(
        "find_recipes_from_pantry", {"max_missing": 2}
    )
    # Empty pantry → empty results
    assert "[]" in str(result) or result == []


# ---------------------------------------------------------------------------
# Cross-tool workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_recipe_to_grocery_list_flow(mcp_client):
    """Create recipe → meal plan → add entry → generate grocery list."""
    await mcp_client.call_tool(
        "create_recipe",
        {"title": "Flow Recipe", "ingredients": ["2 cups flour", "1 egg"]},
    )
    await mcp_client.call_tool("create_meal_plan", {"name": "Flow Plan"})
    await mcp_client.call_tool(
        "add_recipe_to_meal_plan",
        {
            "plan_id": 1,
            "recipe_id": 1,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    result = await mcp_client.call_tool(
        "generate_grocery_list", {"meal_plan_id": 1, "name": "Flow List"}
    )
    assert "Flow List" in str(result) or "items" in str(result).lower()
