"""Tests for grocery list API endpoints."""

import pytest


@pytest.mark.asyncio
async def test_generate_from_recipe_ids(client, create_recipe):
    r = await create_recipe(ingredients=["2 cups flour", "1 cup milk"])
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]], "name": "Shopping"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Shopping"
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_generate_from_meal_plan(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"meal_plan_id": plan["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["meal_plan_id"] == plan["id"]
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_generate_no_input(client):
    resp = await client.post("/api/grocery-lists/generate", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_generate_empty_recipe_ids(client):
    resp = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": []}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_generate_from_recipe_with_no_ingredients(client, create_recipe):
    r = await create_recipe(ingredients=[])
    resp = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["items"]) == 0


@pytest.mark.asyncio
async def test_list_grocery_lists_empty(client):
    resp = await client.get("/api/grocery-lists")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_grocery_lists(client, create_recipe):
    r = await create_recipe()
    await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]], "name": "List 1"},
    )
    await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r["id"]], "name": "List 2"},
    )
    resp = await client.get("/api/grocery-lists")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_grocery_list(client, create_recipe):
    r = await create_recipe(ingredients=["2 cups flour"])
    gl = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    list_id = gl.json()["id"]
    resp = await client.get(f"/api/grocery-lists/{list_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0


@pytest.mark.asyncio
async def test_get_grocery_list_not_found(client):
    resp = await client.get("/api/grocery-lists/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_manual_item(client, create_recipe):
    r = await create_recipe()
    gl = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    list_id = gl.json()["id"]
    resp = await client.post(
        f"/api/grocery-lists/{list_id}/items", json={"text": "Extra butter"}
    )
    assert resp.status_code == 201
    assert resp.json()["text"] == "Extra butter"


@pytest.mark.asyncio
async def test_add_item_list_not_found(client):
    resp = await client.post(
        "/api/grocery-lists/99999/items", json={"text": "Nope"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_check_item(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg"])
    gl = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    items = gl.json()["items"]
    item_id = items[0]["id"]
    resp = await client.patch(
        f"/api/grocery-lists/items/{item_id}", json={"is_checked": True}
    )
    assert resp.status_code == 200
    assert resp.json()["is_checked"]  # SQLite returns 1 for True


@pytest.mark.asyncio
async def test_check_item_not_found(client):
    resp = await client.patch(
        "/api/grocery-lists/items/99999", json={"is_checked": True}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_grocery_list(client, create_recipe):
    r = await create_recipe()
    gl = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    list_id = gl.json()["id"]
    resp = await client.delete(f"/api/grocery-lists/{list_id}")
    assert resp.status_code == 204
    # Verify it's gone
    resp2 = await client.get(f"/api/grocery-lists/{list_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_grocery_list_not_found(client):
    resp = await client.delete("/api/grocery-lists/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_deduplicates_ingredients(client, create_recipe):
    """Same ingredient across two recipes should be aggregated."""
    r1 = await create_recipe(title="Recipe A", ingredients=["2 cups flour"])
    r2 = await create_recipe(title="Recipe B", ingredients=["1 cup flour"])
    resp = await client.post(
        "/api/grocery-lists/generate",
        json={"recipe_ids": [r1["id"], r2["id"]]},
    )
    assert resp.status_code == 201
    items = resp.json()["items"]
    # "flour" should appear once (aggregated), not twice
    flour_items = [i for i in items if "flour" in i["text"].lower()]
    assert len(flour_items) == 1
