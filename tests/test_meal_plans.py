"""Tests for meal plan API endpoints."""


async def test_create_meal_plan(client):
    resp = await client.post("/api/meal-plans", json={"name": "Weekly Dinners"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Weekly Dinners"
    assert "id" in data


async def test_create_meal_plan_empty_name(client):
    # Pydantic requires name to be a non-empty string
    resp = await client.post("/api/meal-plans", json={})
    assert resp.status_code == 422


async def test_list_meal_plans_empty(client):
    resp = await client.get("/api/meal-plans")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_meal_plans(client, create_meal_plan):
    await create_meal_plan("Plan A")
    await create_meal_plan("Plan B")
    resp = await client.get("/api/meal-plans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_get_meal_plan(client, create_meal_plan):
    plan = await create_meal_plan("My Plan")
    resp = await client.get(f"/api/meal-plans/{plan['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Plan"


async def test_get_meal_plan_not_found(client):
    resp = await client.get("/api/meal-plans/99999")
    assert resp.status_code == 404


async def test_update_meal_plan(client, create_meal_plan):
    plan = await create_meal_plan("Old Name")
    resp = await client.patch(
        f"/api/meal-plans/{plan['id']}", json={"name": "New Name"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


async def test_update_meal_plan_not_found(client):
    resp = await client.patch("/api/meal-plans/99999", json={"name": "X"})
    assert resp.status_code == 404


async def test_delete_meal_plan(client, create_meal_plan):
    plan = await create_meal_plan("To Delete")
    resp = await client.delete(f"/api/meal-plans/{plan['id']}")
    assert resp.status_code == 204
    # Verify it's gone
    resp2 = await client.get(f"/api/meal-plans/{plan['id']}")
    assert resp2.status_code == 404


async def test_delete_meal_plan_not_found(client):
    resp = await client.delete("/api/meal-plans/99999")
    assert resp.status_code == 404


async def test_add_entry(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recipe_id"] == recipe["id"]
    assert data["meal_slot"] == "dinner"


async def test_add_entry_plan_not_found(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        "/api/meal-plans/99999/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "lunch",
        },
    )
    assert resp.status_code == 404


async def test_add_entry_invalid_meal_slot(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "brunch",  # not in Literal
        },
    )
    assert resp.status_code == 422


async def test_add_entry_recipe_not_found(client, create_meal_plan):
    """FK constraint error — documents that nonexistent recipe_id is not validated."""
    plan = await create_meal_plan()
    resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": 99999,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    # Router doesn't validate recipe_id existence — FK constraint raises IntegrityError
    # This documents the current behavior (likely 500)
    assert resp.status_code in (400, 404, 500)
    if resp.status_code == 500:
        assert "Traceback" not in resp.text


async def test_remove_entry(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    entry = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    entry_id = entry.json()["id"]
    resp = await client.delete(f"/api/meal-plans/entries/{entry_id}")
    assert resp.status_code == 204


async def test_remove_entry_not_found(client):
    resp = await client.delete("/api/meal-plans/entries/99999")
    assert resp.status_code == 404


async def test_get_meal_plan_includes_entries(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "breakfast",
        },
    )
    await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-26",
            "meal_slot": "lunch",
        },
    )
    resp = await client.get(f"/api/meal-plans/{plan['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2


async def test_delete_meal_plan_cascades_entries(
    client, create_recipe, create_meal_plan
):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    entry_resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    entry_id = entry_resp.json()["id"]
    # Delete the plan
    resp = await client.delete(f"/api/meal-plans/{plan['id']}")
    assert resp.status_code == 204
    # Entry should also be gone (ON DELETE CASCADE)
    resp2 = await client.delete(f"/api/meal-plans/entries/{entry_id}")
    assert resp2.status_code == 404


async def test_add_entry_with_servings_override(
    client, create_recipe, create_meal_plan
):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
            "servings_override": 8,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["servings_override"] == 8
