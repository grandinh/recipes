"""Tests for web UI routes returning HTML."""


async def test_home_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_home_page_with_recipes(client, sample_recipe):
    await client.post("/api/recipes", json=sample_recipe)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text


async def test_recipe_detail_page(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.get(f"/recipe/{recipe_id}")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text
    assert "2 cups flour" in resp.text


async def test_recipe_detail_not_found(client):
    resp = await client.get("/recipe/99999")
    assert resp.status_code == 404


async def test_add_recipe_page(client):
    resp = await client.get("/add")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_edit_recipe_page(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.get(f"/edit/{recipe_id}")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text


async def test_csp_header(client):
    resp = await client.get("/")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp


async def test_search_from_web(client, sample_recipe):
    await client.post("/api/recipes", json=sample_recipe)
    resp = await client.get("/?q=pancakes")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text


# ---------------------------------------------------------------------------
# Calendar, grocery list, and pantry page renders
# ---------------------------------------------------------------------------


async def test_calendar_page(client):
    resp = await client.get("/calendar")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_calendar_page_with_entries(client, create_recipe):
    recipe = await create_recipe(title="Calendar Test")
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    await client.post("/api/calendar/entries", json={
        "recipe_id": recipe["id"],
        "date": monday.isoformat(),
        "meal_slot": "dinner",
    })
    resp = await client.get(f"/calendar?week={monday.isoformat()}")
    assert resp.status_code == 200
    assert "Calendar Test" in resp.text


async def test_grocery_page(client):
    resp = await client.get("/grocery")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_grocery_page_with_items(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg"])
    await client.post(
        "/api/grocery/generate-from-calendar",
        json={"recipe_ids": [r["id"]]},
    )
    resp = await client.get("/grocery")
    assert resp.status_code == 200
    assert "aisle-section" in resp.text


async def test_pantry_page(client):
    resp = await client.get("/pantry")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_pantry_what_can_i_make_page(client):
    resp = await client.get("/pantry/what-can-i-make")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
