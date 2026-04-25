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
# Mark Cooked form handler — freshness fragment + redirect fallback
# ---------------------------------------------------------------------------


async def test_recipe_detail_shows_never_cooked_initially(client, create_recipe):
    recipe = await create_recipe(title="Never Cooked Display")
    resp = await client.get(f"/recipe/{recipe['id']}")
    assert resp.status_code == 200
    assert "Never cooked" in resp.text
    assert "Mark Cooked" in resp.text


async def test_mark_cooked_form_redirects_without_htmx(client, create_recipe):
    recipe = await create_recipe(title="Form Mark Cooked")
    resp = await client.post(
        f"/recipe/{recipe['id']}/cooked", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/recipe/{recipe['id']}"

    detail = await client.get(f"/api/recipes/{recipe['id']}")
    data = detail.json()
    assert data["times_cooked"] == 1
    assert data["last_cooked_at"] is not None


async def test_mark_cooked_returns_freshness_fragment_for_htmx(
    client, create_recipe
):
    recipe = await create_recipe(title="HTMX Mark Cooked")
    resp = await client.post(
        f"/recipe/{recipe['id']}/cooked",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="freshness-meta"' in resp.text
    assert "Last cooked" in resp.text
    # Fragment-only — no full page chrome
    assert "<html" not in resp.text.lower()


async def test_mark_cooked_missing_recipe_returns_404_for_htmx(client):
    resp = await client.post(
        "/recipe/99999/cooked", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 404


async def test_recipe_list_sort_last_cooked_renders(client, create_recipe):
    cooked = await create_recipe(title="Cooked Recipe")
    await create_recipe(title="Uncooked Recipe")
    await client.post(
        f"/api/recipes/{cooked['id']}/cooked",
        json={"cooked_at": "2026-04-20T12:00:00"},
    )

    resp = await client.get("/?sort=last_cooked")
    assert resp.status_code == 200
    body = resp.text
    assert 'value="last_cooked"' in body
    # Cooked recipe ranks before uncooked one in the rendered list
    assert body.index("Cooked Recipe") < body.index("Uncooked Recipe")


# ---------------------------------------------------------------------------
# Calendar form handlers
# ---------------------------------------------------------------------------


async def test_add_recipe_to_calendar_form(client, create_recipe):
    recipe = await create_recipe()
    resp = await client.post(
        "/calendar/add-recipe",
        data={
            "recipe_id": str(recipe["id"]),
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/calendar" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Grocery list form handlers
# ---------------------------------------------------------------------------


async def test_add_from_calendar_form(client, create_recipe):
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
        "/grocery/add-from-calendar",
        data={"date_start": "2026-03-23", "date_end": "2026-03-29"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/grocery" in resp.headers["location"]


async def test_add_from_recipe_form(client, create_recipe):
    r = await create_recipe(ingredients=["1 egg"])
    resp = await client.post(
        f"/grocery/add-from-recipe/{r['id']}", follow_redirects=False
    )
    assert resp.status_code == 303
    assert "/grocery" in resp.headers["location"]


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
