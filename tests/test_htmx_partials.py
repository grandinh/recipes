"""Tests for HTMX partial rendering — verify fragment vs full-page responses."""

HTMX_HEADERS = {"hx-request": "true"}


async def test_home_full_page(client, create_recipe):
    await create_recipe(title="Full Page Recipe")
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "<html" in resp.text
    assert "Full Page Recipe" in resp.text


async def test_home_htmx_returns_fragment(client, create_recipe):
    await create_recipe(title="HTMX Recipe")
    resp = await client.get("/", headers=HTMX_HEADERS)
    assert resp.status_code == 200
    assert "<!DOCTYPE" not in resp.text
    assert "<html" not in resp.text
    assert "HTMX Recipe" in resp.text


async def test_pantry_add_htmx(client):
    resp = await client.post(
        "/pantry/add", data={"name": "Eggs"}, headers=HTMX_HEADERS
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "Eggs" in resp.text


async def test_pantry_delete_htmx(client, create_pantry_item):
    item = await create_pantry_item("To Remove")
    resp = await client.post(
        f"/pantry/delete/{item['id']}", headers=HTMX_HEADERS
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "To Remove" not in resp.text


async def test_calendar_add_recipe_htmx(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        "/calendar/add-recipe",
        data={
            "recipe_id": str(recipe["id"]),
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
        headers=HTMX_HEADERS,
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    # Fragment should contain the recipe title in entries
    assert recipe["title"] in resp.text


async def test_grocery_add_item_htmx(client):
    resp = await client.post(
        "/grocery/add-item",
        data={"text": "Extra butter"},
        headers=HTMX_HEADERS,
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "Extra butter" in resp.text
