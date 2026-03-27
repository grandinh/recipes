"""Data integrity tests — FK enforcement, cascades, cross-feature flows."""

import asyncio


async def test_foreign_keys_are_enforced(client):
    """Canary test: verify PRAGMA foreign_keys = ON is active."""
    resp = await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": 999999,
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    # If FK enforcement is on, this should NOT succeed
    assert resp.status_code != 201, "FK enforcement appears OFF"


async def test_full_calendar_planning_flow(client, create_recipe):
    """Recipe -> calendar entry -> generate grocery items -> verify items."""
    r1 = await create_recipe(title="Flow Recipe", ingredients=["2 cups flour", "1 egg"])

    await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": r1["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )

    gl_resp = await client.post(
        "/api/grocery/generate-from-calendar",
        json={"date_start": "2026-03-23", "date_end": "2026-03-29"},
    )
    assert gl_resp.status_code == 201
    data = gl_resp.json()
    assert data["items_added"] > 0

    # Verify items are on the global list
    glist = await client.get("/api/grocery")
    assert len(glist.json()["items"]) > 0


async def test_delete_recipe_cascades_calendar_entries(client, create_recipe):
    """ON DELETE CASCADE: recipe deletion removes referencing calendar entries."""
    recipe = await create_recipe()
    await client.post(
        "/api/calendar/entries",
        json={
            "recipe_id": recipe["id"],
            "date": "2026-03-25",
            "meal_slot": "dinner",
        },
    )
    # Verify entry exists
    cal_data = await client.get("/api/calendar?week=2026-03-25")
    assert len(cal_data.json()["entries"]) == 1

    # Delete the recipe
    await client.delete(f"/api/recipes/{recipe['id']}")

    # Entry should be gone (CASCADE)
    cal_data2 = await client.get("/api/calendar?week=2026-03-25")
    assert len(cal_data2.json()["entries"]) == 0


async def test_clear_checked_removes_items(client, create_recipe):
    """Clear checked removes all checked items from the global list."""
    r = await create_recipe(ingredients=["1 egg"])
    await client.post(
        "/api/grocery/generate-from-calendar", json={"recipe_ids": [r["id"]]}
    )
    # Add a manual item too
    await client.post("/api/grocery/items", json={"text": "Butter"})

    glist = await client.get("/api/grocery")
    items = glist.json()["items"]
    assert len(items) >= 2

    # Check all items
    for item in items:
        await client.patch(
            f"/api/grocery/items/{item['id']}", json={"is_checked": True}
        )

    # Clear checked
    resp = await client.post("/api/grocery/clear-checked")
    assert resp.status_code == 200
    assert resp.json()["cleared_count"] == len(items)

    # List should now be empty
    glist2 = await client.get("/api/grocery")
    assert len(glist2.json()["items"]) == 0


async def test_pantry_matches_after_adding_items(
    client, create_recipe, create_pantry_item
):
    """Add pantry items matching recipe ingredients -> verify match endpoint."""
    await create_recipe(
        title="Matching Soup",
        ingredients=["1 onion", "2 carrots", "3 cups broth"],
    )
    await create_pantry_item("onion")
    await create_pantry_item("carrots")
    await create_pantry_item("broth")

    resp = await client.get("/api/pantry/matches?max_missing=0")
    assert resp.status_code == 200
    data = resp.json()
    titles = [m["title"] for m in data]
    assert "Matching Soup" in titles


async def test_concurrent_writes_serialized(client, create_recipe):
    """Multiple concurrent writes should not produce SQLITE_BUSY errors."""
    tasks = [create_recipe(title=f"Concurrent {i}") for i in range(5)]
    results = await asyncio.gather(*tasks)
    assert all(r["id"] for r in results)
    assert len(set(r["id"] for r in results)) == 5
