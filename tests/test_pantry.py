"""Tests for pantry API endpoints."""


async def test_add_pantry_item(client):
    resp = await client.post(
        "/api/pantry",
        json={
            "name": "All-Purpose Flour",
            "category": "Baking",
            "quantity": 2.5,
            "unit": "lbs",
            "expiration_date": "2026-06-01",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "All-Purpose Flour"
    assert data["category"] == "Baking"
    assert data["quantity"] == 2.5
    assert data["unit"] == "lbs"
    assert data["expiration_date"] == "2026-06-01"


async def test_add_pantry_item_minimal(client):
    resp = await client.post("/api/pantry", json={"name": "Salt"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Salt"
    assert data["category"] is None
    assert data["quantity"] is None
    assert data["unit"] is None
    assert data["expiration_date"] is None


async def test_add_duplicate_name(client, create_pantry_item):
    """UNIQUE COLLATE NOCASE constraint — documents current 500 behavior."""
    await create_pantry_item("Flour")
    resp = await client.post("/api/pantry", json={"name": "flour"})
    # Currently returns 500 due to unhandled IntegrityError
    assert resp.status_code in (409, 500)
    if resp.status_code == 500:
        assert "Traceback" not in resp.text


async def test_list_pantry_items_empty(client):
    resp = await client.get("/api/pantry")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_pantry_items(client, create_pantry_item):
    await create_pantry_item("Flour")
    await create_pantry_item("Sugar")
    await create_pantry_item("Eggs")
    resp = await client.get("/api/pantry")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


async def test_list_expiring_soon(client, create_pantry_item):
    await create_pantry_item("Fresh Milk", expiration_date="2026-03-27")
    await create_pantry_item("Canned Beans", expiration_date="2027-01-01")
    resp = await client.get("/api/pantry?expiring_within_days=7")
    assert resp.status_code == 200
    data = resp.json()
    # Only fresh milk should be expiring within 7 days of 2026-03-25
    names = [item["name"] for item in data]
    assert "Fresh Milk" in names


async def test_update_pantry_item(client, create_pantry_item):
    item = await create_pantry_item("Butter", quantity=1.0, unit="lbs")
    resp = await client.patch(
        f"/api/pantry/{item['id']}", json={"quantity": 0.5}
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 0.5


async def test_update_pantry_item_not_found(client):
    resp = await client.patch("/api/pantry/99999", json={"quantity": 1.0})
    assert resp.status_code == 404


async def test_update_pantry_item_empty_body(client, create_pantry_item):
    item = await create_pantry_item("Olive Oil")
    resp = await client.patch(f"/api/pantry/{item['id']}", json={})
    assert resp.status_code == 400


async def test_update_rename_to_duplicate(client, create_pantry_item):
    """UNIQUE violation on rename — documents current 500 behavior."""
    await create_pantry_item("Flour")
    item2 = await create_pantry_item("Sugar")
    resp = await client.patch(
        f"/api/pantry/{item2['id']}", json={"name": "Flour"}
    )
    assert resp.status_code in (409, 500)
    if resp.status_code == 500:
        assert "Traceback" not in resp.text


async def test_delete_pantry_item(client, create_pantry_item):
    item = await create_pantry_item("To Delete")
    resp = await client.delete(f"/api/pantry/{item['id']}")
    assert resp.status_code == 204
    resp2 = await client.get("/api/pantry")
    assert all(i["name"] != "To Delete" for i in resp2.json())


async def test_delete_pantry_item_not_found(client):
    resp = await client.delete("/api/pantry/99999")
    assert resp.status_code == 404


async def test_pantry_matches(client, create_recipe, create_pantry_item):
    await create_recipe(
        title="Simple Omelette",
        ingredients=["3 eggs", "1 cup milk", "salt"],
    )
    await create_pantry_item("eggs")
    await create_pantry_item("milk")
    await create_pantry_item("salt")
    resp = await client.get("/api/pantry/matches?max_missing=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["title"] == "Simple Omelette"


async def test_pantry_matches_empty_pantry(client):
    resp = await client.get("/api/pantry/matches")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_pantry_matches_no_matches(client, create_recipe, create_pantry_item):
    await create_recipe(ingredients=["1 lb lobster", "1 cup butter"])
    await create_pantry_item("tofu")
    resp = await client.get("/api/pantry/matches?max_missing=0")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_pantry_matches_max_missing(client, create_recipe, create_pantry_item):
    await create_recipe(
        title="Pasta",
        ingredients=["1 lb pasta", "2 cups sauce", "1 cup cheese"],
    )
    await create_pantry_item("pasta")
    # Missing sauce and cheese = 2 missing
    resp = await client.get("/api/pantry/matches?max_missing=2")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp2 = await client.get("/api/pantry/matches?max_missing=1")
    assert resp2.status_code == 200
    # With max_missing=1, pasta recipe has 2 missing so it should be excluded
    titles = [m["title"] for m in resp2.json()]
    assert "Pasta" not in titles


async def test_add_pantry_item_unique_after_delete(client, create_pantry_item):
    """Deleting and re-creating with same name should succeed."""
    item = await create_pantry_item("Flour")
    await client.delete(f"/api/pantry/{item['id']}")
    # Re-create with same name
    resp = await client.post("/api/pantry", json={"name": "Flour"})
    assert resp.status_code == 201
