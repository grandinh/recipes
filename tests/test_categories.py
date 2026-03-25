"""Tests for category CRUD operations."""


async def test_create_category(client):
    resp = await client.post("/api/categories", json={"name": "Vegan"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Vegan"
    assert data["id"] is not None


async def test_list_categories_with_counts(client, sample_recipe):
    await client.post("/api/recipes", json=sample_recipe)

    resp = await client.get("/api/categories")
    assert resp.status_code == 200
    data = resp.json()
    # sample_recipe has Breakfast and Quick categories
    names = {c["name"] for c in data}
    assert "Breakfast" in names
    assert "Quick" in names
    # Check counts
    breakfast = next(c for c in data if c["name"] == "Breakfast")
    assert breakfast["recipe_count"] >= 1


async def test_delete_category(client):
    create_resp = await client.post("/api/categories", json={"name": "ToDelete"})
    cat_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/categories/{cat_id}")
    assert resp.status_code == 204


async def test_delete_category_not_found(client):
    resp = await client.delete("/api/categories/99999")
    assert resp.status_code == 404


async def test_delete_category_preserves_recipes(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    # Find the Breakfast category
    cats_resp = await client.get("/api/categories")
    breakfast = next(c for c in cats_resp.json() if c["name"] == "Breakfast")

    # Delete the category
    await client.delete(f"/api/categories/{breakfast['id']}")

    # Recipe still exists
    resp = await client.get(f"/api/recipes/{recipe_id}")
    assert resp.status_code == 200
    # But Breakfast category is gone from recipe
    assert "Breakfast" not in resp.json()["categories"]
