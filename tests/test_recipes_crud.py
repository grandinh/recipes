"""Tests for recipe CRUD operations via the REST API."""


async def test_create_recipe(client, sample_recipe):
    resp = await client.post("/api/recipes", json=sample_recipe)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Pancakes"
    assert data["ingredients"] == ["2 cups flour", "1 cup milk", "2 eggs"]
    assert data["rating"] == 4
    assert data["difficulty"] == "easy"
    assert data["cuisine"] == "American"
    assert data["prep_time_minutes"] == 10
    assert data["cook_time_minutes"] == 15
    assert data["total_time_minutes"] == 25
    assert set(data["categories"]) == {"Breakfast", "Quick"}
    assert data["id"] is not None
    assert data["created_at"] is not None


async def test_create_recipe_minimal(client):
    resp = await client.post("/api/recipes", json={"title": "Just a Title"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Just a Title"
    assert data["ingredients"] == []
    assert data["categories"] == []
    assert data["is_favorite"] is False


async def test_create_recipe_no_title_fails(client):
    resp = await client.post("/api/recipes", json={"description": "No title"})
    assert resp.status_code == 422


async def test_get_recipe(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.get(f"/api/recipes/{recipe_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Pancakes"
    assert data["id"] == recipe_id


async def test_get_recipe_not_found(client):
    resp = await client.get("/api/recipes/99999")
    assert resp.status_code == 404


async def test_update_recipe(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/recipes/{recipe_id}",
        json={"title": "Updated Pancakes", "rating": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Pancakes"
    assert data["rating"] == 5
    # Unchanged fields preserved
    assert data["cuisine"] == "American"
    assert data["prep_time_minutes"] == 10


async def test_update_recipe_categories(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/recipes/{recipe_id}",
        json={"categories": ["Dinner", "Comfort Food"]},
    )
    assert resp.status_code == 200
    assert set(resp.json()["categories"]) == {"Dinner", "Comfort Food"}


async def test_update_recipe_not_found(client):
    resp = await client.patch("/api/recipes/99999", json={"title": "Nope"})
    assert resp.status_code == 404


async def test_delete_recipe(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/recipes/{recipe_id}")
    assert resp.status_code == 204

    # Verify gone
    resp = await client.get(f"/api/recipes/{recipe_id}")
    assert resp.status_code == 404


async def test_delete_recipe_not_found(client):
    resp = await client.delete("/api/recipes/99999")
    assert resp.status_code == 404


async def test_list_recipes(client, sample_recipe, sample_recipe_2):
    await client.post("/api/recipes", json=sample_recipe)
    await client.post("/api/recipes", json=sample_recipe_2)

    resp = await client.get("/api/recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


async def test_list_recipes_sort_name(client, sample_recipe, sample_recipe_2):
    await client.post("/api/recipes", json=sample_recipe)
    await client.post("/api/recipes", json=sample_recipe_2)

    resp = await client.get("/api/recipes?sort=name")
    data = resp.json()
    titles = [r["title"] for r in data]
    assert titles == sorted(titles)


async def test_list_recipes_sort_last_cooked(client, sample_recipe, sample_recipe_2):
    # Regression for todo 016: /api/recipes?sort=last_cooked previously 422'd
    # because the endpoint Literal omitted "last_cooked" while db.list_recipes
    # already accepted it.
    await client.post("/api/recipes", json=sample_recipe)
    await client.post("/api/recipes", json=sample_recipe_2)

    resp = await client.get("/api/recipes?sort=last_cooked")
    assert resp.status_code == 200


async def test_list_recipes_pagination(client, sample_recipe):
    # Create a few recipes
    for i in range(5):
        await client.post("/api/recipes", json={"title": f"Recipe {i}"})

    resp = await client.get("/api/recipes?limit=2&offset=0")
    assert len(resp.json()) == 2

    resp = await client.get("/api/recipes?limit=2&offset=2")
    assert len(resp.json()) == 2


async def test_favorite_flag(client):
    resp = await client.post(
        "/api/recipes", json={"title": "Fav Recipe", "is_favorite": True}
    )
    assert resp.status_code == 201
    assert resp.json()["is_favorite"] is True

    recipe_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/recipes/{recipe_id}", json={"is_favorite": False}
    )
    assert resp.json()["is_favorite"] is False


async def test_rating_validation(client):
    resp = await client.post(
        "/api/recipes", json={"title": "Bad Rating", "rating": 0}
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/recipes", json={"title": "Bad Rating", "rating": 6}
    )
    assert resp.status_code == 422


async def test_difficulty_validation(client):
    resp = await client.post(
        "/api/recipes", json={"title": "Bad Diff", "difficulty": "impossible"}
    )
    assert resp.status_code == 422


async def test_duplicate_source_url(client):
    recipe = {"title": "Recipe A", "source_url": "https://example.com/recipe-1"}
    await client.post("/api/recipes", json=recipe)

    recipe2 = {"title": "Recipe B", "source_url": "https://example.com/recipe-1"}
    resp = await client.post("/api/recipes", json=recipe2)
    # SQLite UNIQUE constraint violation
    assert resp.status_code in (409, 500)
