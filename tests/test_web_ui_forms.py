"""Tests for web UI form POST handlers — redirects, form parsing, error cases."""


# ---------------------------------------------------------------------------
# Recipe form handlers
# ---------------------------------------------------------------------------


async def test_add_recipe_form(client):
    resp = await client.post(
        "/add",
        data={
            "title": "Form Pancakes",
            "ingredients": "2 cups flour\n1 cup milk",
            "directions": "Mix and cook.",
            "categories": "Breakfast,Quick",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/recipe/" in resp.headers["location"]


async def test_add_recipe_form_minimal(client):
    resp = await client.post(
        "/add", data={"title": "Minimal"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "/recipe/" in resp.headers["location"]


async def test_edit_recipe_form(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        f"/edit/{recipe['id']}",
        data={"title": "Updated Title", "ingredients": "new ingredient"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"/recipe/{recipe['id']}" in resp.headers["location"]


async def test_delete_recipe_form(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        f"/delete/{recipe['id']}", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


# ---------------------------------------------------------------------------
# Meal plan form handlers
# ---------------------------------------------------------------------------


async def test_create_meal_plan_form(client):
    resp = await client.post(
        "/meal-plans", data={"name": "Weekly"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "/meal-plans/" in resp.headers["location"]


async def test_add_recipe_to_plan_form(client, create_recipe, create_meal_plan):
    recipe = await create_recipe()
    plan = await create_meal_plan()
    resp = await client.post(
        f"/meal-plans/{plan['id']}/add-recipe",
        data={
            "recipe_id": str(recipe["id"]),
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"/meal-plans/{plan['id']}" in resp.headers["location"]


async def test_delete_meal_plan_form(client, create_meal_plan):
    plan = await create_meal_plan()
    resp = await client.post(
        f"/meal-plans/{plan['id']}/delete", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/meal-plans"


# ---------------------------------------------------------------------------
# Grocery list form handlers
# ---------------------------------------------------------------------------


async def test_generate_grocery_list_form(client, create_recipe, create_meal_plan):
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
        "/grocery-lists/generate",
        data={"meal_plan_id": str(plan["id"]), "name": "Shopping"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/grocery-lists/" in resp.headers["location"]


async def test_delete_grocery_list_form(client, create_recipe):
    r = await create_recipe()
    gl = await client.post(
        "/api/grocery-lists/generate", json={"recipe_ids": [r["id"]]}
    )
    list_id = gl.json()["id"]
    resp = await client.post(
        f"/grocery-lists/{list_id}/delete", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/grocery-lists"


# ---------------------------------------------------------------------------
# Pantry form handlers
# ---------------------------------------------------------------------------


async def test_add_pantry_item_form(client):
    resp = await client.post(
        "/pantry/add", data={"name": "Flour"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pantry"


async def test_delete_pantry_item_form(client, create_pantry_item):
    item = await create_pantry_item("To Delete")
    resp = await client.post(
        f"/pantry/delete/{item['id']}", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pantry"
