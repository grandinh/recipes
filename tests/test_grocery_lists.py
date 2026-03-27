"""Tests for the global grocery list API endpoints."""


async def test_get_grocery_list_empty(client):
    """Global grocery list starts empty."""
    resp = await client.get("/api/grocery")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["items"] == []


async def test_add_manual_item(client):
    resp = await client.post(
        "/api/grocery/items", json={"text": "Extra butter"}
    )
    assert resp.status_code == 201
    assert resp.json()["text"] == "Extra butter"


async def test_add_manual_item_with_aisle(client):
    resp = await client.post(
        "/api/grocery/items", json={"text": "Milk", "aisle": "Dairy & Eggs"}
    )
    assert resp.status_code == 201
    item = resp.json()
    assert item["text"] == "Milk"
    assert item["aisle"] == "Dairy &amp; Eggs"  # sanitized


async def test_generate_from_recipe_ids(client, create_recipe):
    r = await create_recipe(ingredients=["2 cups flour", "1 cup milk"])
    resp = await client.post(
        "/api/grocery/generate-from-calendar",
        json={"recipe_ids": [r["id"]]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["items_added"] > 0
    assert "items" in data


async def test_generate_from_calendar(client, create_recipe):
    recipe = await create_recipe()
    await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    resp = await client.post(
        "/api/grocery/generate-from-calendar",
        json={"date_start": "2026-03-23", "date_end": "2026-03-29"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["items_added"] > 0


async def test_generate_no_input(client):
    resp = await client.post("/api/grocery/generate-from-calendar", json={})
    assert resp.status_code == 400


async def test_generate_empty_recipe_ids(client):
    resp = await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": []}
    )
    assert resp.status_code == 400


async def test_generate_from_recipe_with_no_ingredients(client, create_recipe):
    r = await create_recipe(ingredients=[])
    resp = await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["items_added"] == 0


async def test_check_item(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    glist = await client.get("/api/grocery")
    items = glist.json()["items"]
    item_id = items[0]["id"]
    resp = await client.patch(
        f"/api/grocery/items/{item_id}", json={"is_checked": True}
    )
    assert resp.status_code == 200
    assert resp.json()["is_checked"]


async def test_check_item_not_found(client):
    resp = await client.patch(
        "/api/grocery/items/99999", json={"is_checked": True}
    )
    assert resp.status_code == 404


async def test_delete_grocery_item(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    glist = await client.get("/api/grocery")
    items = glist.json()["items"]
    item_id = items[0]["id"]
    resp = await client.delete(f"/api/grocery/items/{item_id}")
    assert resp.status_code == 204


async def test_delete_grocery_item_not_found(client):
    resp = await client.delete("/api/grocery/items/99999")
    assert resp.status_code == 404


async def test_clear_checked_grocery_items(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg", "2 cups flour"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    glist = await client.get("/api/grocery")
    data = glist.json()
    item_id = data["items"][0]["id"]
    # Check one item
    await client.patch(
        f"/api/grocery/items/{item_id}", json={"is_checked": True}
    )
    # Clear checked
    resp = await client.post("/api/grocery/clear-checked")
    assert resp.status_code == 200
    result = resp.json()
    assert result["cleared_count"] == 1
    # Verify remaining items
    resp2 = await client.get("/api/grocery")
    assert len(resp2.json()["items"]) == len(data["items"]) - 1


async def test_move_checked_to_pantry(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg", "2 cups flour"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    glist = await client.get("/api/grocery")
    data = glist.json()
    # Check all items
    for item in data["items"]:
        await client.patch(
            f"/api/grocery/items/{item['id']}", json={"is_checked": True}
        )
    # Move to pantry
    resp = await client.post("/api/grocery/move-to-pantry")
    assert resp.status_code == 200
    result = resp.json()
    assert len(result["moved"]) > 0
    # Verify pantry has items
    pantry = await client.get("/api/pantry")
    assert len(pantry.json()) > 0
    # Verify grocery list is empty
    resp2 = await client.get("/api/grocery")
    assert len(resp2.json()["items"]) == 0


async def test_move_checked_to_pantry_dedup(client, create_recipe, create_pantry_item):
    """Moving items already in pantry should not duplicate them."""
    await create_pantry_item("egg")
    r = await create_recipe(ingredients=["1 egg"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    glist = await client.get("/api/grocery")
    data = glist.json()
    for item in data["items"]:
        await client.patch(
            f"/api/grocery/items/{item['id']}", json={"is_checked": True}
        )
    resp = await client.post("/api/grocery/move-to-pantry")
    result = resp.json()
    # "egg" should be in already_in_pantry (case-insensitive match)
    assert len(result["already_in_pantry"]) >= 1


async def test_generate_deduplicates_ingredients(client, create_recipe):
    """Same ingredient across two recipes should be aggregated."""
    r1 = await create_recipe(title="Recipe A", ingredients=["2 cups flour"])
    r2 = await create_recipe(title="Recipe B", ingredients=["1 cup flour"])
    resp = await client.post(
        "/api/grocery/generate-from-calendar",
        json={"recipe_ids": [r1["id"], r2["id"]]},
    )
    assert resp.status_code == 201
    # Check the global list
    glist = await client.get("/api/grocery")
    items = glist.json()["items"]
    # "flour" should appear once (aggregated), not twice
    flour_items = [i for i in items if "flour" in i["text"].lower()]
    assert len(flour_items) == 1


async def test_add_from_recipe(client, create_recipe):
    """Add recipe ingredients to the global grocery list."""
    r = await create_recipe(ingredients=["2 eggs", "1 cup flour"])
    resp = await client.post(f"/api/grocery/add-from-recipe/{r['id']}")
    assert resp.status_code == 201
    data = resp.json()
    assert data["items_added"] >= 1
    assert data["recipe_title"] == "Test Pancakes"


async def test_add_from_recipe_not_found(client):
    resp = await client.post("/api/grocery/add-from-recipe/99999")
    assert resp.status_code == 404


async def test_preview_grocery_additions(client, create_recipe):
    """Preview should return items without modifying the list."""
    r = await create_recipe(ingredients=["2 eggs", "1 cup flour"])
    resp = await client.get(f"/api/grocery/preview/{r['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recipe_title"] == "Test Pancakes"
    assert len(data["items"]) >= 1
    # Verify the global list is still empty (preview is read-only)
    glist = await client.get("/api/grocery")
    assert len(glist.json()["items"]) == 0


async def test_pantry_matching_flag(client, create_recipe, create_pantry_item):
    """Items matching pantry should have in_pantry=True."""
    await create_pantry_item("flour")
    r = await create_recipe(ingredients=["2 cups flour", "1 egg"])
    await client.post(f"/api/grocery/add-from-recipe/{r['id']}")
    glist = await client.get("/api/grocery")
    items = glist.json()["items"]
    flour_items = [i for i in items if "flour" in i["text"].lower()]
    assert len(flour_items) == 1
    assert flour_items[0]["in_pantry"] is True
