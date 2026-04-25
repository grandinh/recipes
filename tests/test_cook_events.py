"""Tests for last-cooked history across REST, MCP, search, and migration."""

import json

import aiosqlite
from fastmcp import Client


def _parse_mcp_result(result):
    if not result:
        return None
    if not result.content:
        structured = getattr(result, "structured_content", None)
        if structured is not None and "result" in structured:
            return structured["result"]
        return None
    item = result.content[0]
    text = item.text if hasattr(item, "text") else str(item)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def _count_cook_events_for_recipe(recipe_id: int) -> int:
    from recipe_app.main import app

    cursor = await app.state.db.execute(
        "SELECT COUNT(*) AS count FROM recipe_cook_events WHERE recipe_id = ?",
        (recipe_id,),
    )
    row = await cursor.fetchone()
    return row["count"]


async def test_record_cook_event_updates_recipe_detail(client, create_recipe):
    recipe = await create_recipe(title="Cooked Once")

    resp = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": "2026-04-18T18:30:00", "notes": "Dinner"},
    )
    assert resp.status_code == 201, resp.text
    recorded = resp.json()
    assert recorded["event"]["recipe_id"] == recipe["id"]
    assert recorded["event"]["cooked_at"] == "2026-04-18T18:30:00"
    assert recorded["recipe"]["last_cooked_at"] == "2026-04-18T18:30:00"
    assert recorded["recipe"]["times_cooked"] == 1

    detail = await client.get(f"/api/recipes/{recipe['id']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["last_cooked_at"] == "2026-04-18T18:30:00"
    assert data["times_cooked"] == 1


async def test_list_recipe_cook_events_returns_newest_first(client, create_recipe):
    recipe = await create_recipe(title="Cook History")
    first = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": "2026-04-18T18:30:00"},
    )
    second = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": "2026-04-20T12:00:00"},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    resp = await client.get(f"/api/recipes/{recipe['id']}/cook-events")
    assert resp.status_code == 200
    events = resp.json()
    assert [event["cooked_at"] for event in events] == [
        "2026-04-20T12:00:00",
        "2026-04-18T18:30:00",
    ]


async def test_delete_cook_event_recalculates_last_cooked(client, create_recipe):
    recipe = await create_recipe(title="Delete Cook Event")
    older = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": "2026-04-18T18:30:00"},
    )
    newer = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": "2026-04-20T12:00:00"},
    )

    delete_resp = await client.delete(
        f"/api/recipes/cook-events/{newer.json()['event']['id']}"
    )
    assert delete_resp.status_code == 204

    detail = await client.get(f"/api/recipes/{recipe['id']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["last_cooked_at"] == "2026-04-18T18:30:00"
    assert data["times_cooked"] == 1

    remaining = await client.get(f"/api/recipes/{recipe['id']}/cook-events")
    assert [event["id"] for event in remaining.json()] == [older.json()["event"]["id"]]


async def test_search_sort_last_cooked_orders_recent_first_nulls_last(
    client, create_recipe
):
    never = await create_recipe(title="Never Cooked")
    older = await create_recipe(title="Older Cooked")
    newer = await create_recipe(title="Newer Cooked")

    await client.post(
        f"/api/recipes/{older['id']}/cooked",
        json={"cooked_at": "2026-04-18T18:30:00"},
    )
    await client.post(
        f"/api/recipes/{newer['id']}/cooked",
        json={"cooked_at": "2026-04-20T12:00:00"},
    )

    resp = await client.get("/api/search?sort=last_cooked")
    assert resp.status_code == 200, resp.text
    ids = [recipe["id"] for recipe in resp.json()]
    assert ids[:3] == [newer["id"], older["id"], never["id"]]


async def test_record_cook_event_missing_recipe_returns_404(client):
    resp = await client.post(
        "/api/recipes/99999/cooked",
        json={"cooked_at": "2026-04-18T18:30:00"},
    )
    assert resp.status_code == 404


async def test_delete_missing_cook_event_returns_404(client):
    resp = await client.delete("/api/recipes/cook-events/99999")
    assert resp.status_code == 404


async def test_times_cooked_zero_when_no_events(client, create_recipe):
    recipe = await create_recipe(title="Never Cooked Detail")

    resp = await client.get(f"/api/recipes/{recipe['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_cooked_at"] is None
    assert data["times_cooked"] == 0


async def test_rapid_double_mark_uses_id_tiebreak_and_counts(client, create_recipe):
    recipe = await create_recipe(title="Double Mark")
    timestamp = "2026-04-18T18:30:00"

    first = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": timestamp},
    )
    second = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={"cooked_at": timestamp},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    detail = await client.get(f"/api/recipes/{recipe['id']}")
    assert detail.json()["times_cooked"] == 2

    events = (await client.get(f"/api/recipes/{recipe['id']}/cook-events")).json()
    assert [event["id"] for event in events] == [
        second.json()["event"]["id"],
        first.json()["event"]["id"],
    ]


async def test_recipe_delete_cascades_cook_events(client, create_recipe):
    recipe = await create_recipe(title="Cascade Cook Events")
    for timestamp in [
        "2026-04-18T18:30:00",
        "2026-04-19T18:30:00",
        "2026-04-20T18:30:00",
    ]:
        resp = await client.post(
            f"/api/recipes/{recipe['id']}/cooked",
            json={"cooked_at": timestamp},
        )
        assert resp.status_code == 201

    assert await _count_cook_events_for_recipe(recipe["id"]) == 3
    delete_resp = await client.delete(f"/api/recipes/{recipe['id']}")
    assert delete_resp.status_code == 204
    assert await _count_cook_events_for_recipe(recipe["id"]) == 0


async def test_calendar_entry_delete_preserves_cook_event_with_null_link(
    client, create_recipe, create_calendar_entry
):
    recipe = await create_recipe(title="Calendar Cook")
    entry = await create_calendar_entry(
        recipe["id"], date="2026-04-18", meal_slot="dinner"
    )

    recorded = await client.post(
        f"/api/recipes/{recipe['id']}/cooked",
        json={
            "cooked_at": "2026-04-18T18:30:00",
            "source": "calendar",
            "calendar_entry_id": entry["id"],
        },
    )
    assert recorded.status_code == 201
    assert recorded.json()["event"]["calendar_entry_id"] == entry["id"]

    delete_resp = await client.delete(f"/api/calendar/entries/{entry['id']}")
    assert delete_resp.status_code == 204

    events = (await client.get(f"/api/recipes/{recipe['id']}/cook-events")).json()
    assert len(events) == 1
    assert events[0]["calendar_entry_id"] is None
    assert events[0]["source"] == "calendar"


async def test_mcp_record_history_and_delete_tools(client, create_recipe):
    from recipe_app import mcp_server as mcp_mod

    recipe = await create_recipe(title="MCP Cooked")
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None

    try:
        async with Client(mcp_mod.mcp) as mcp_client:
            recorded = _parse_mcp_result(
                await mcp_client.call_tool(
                    "record_recipe_cooked",
                    {
                        "recipe_id": recipe["id"],
                        "cooked_at": "2026-04-18T18:30:00",
                        "notes": "MCP mark",
                    },
                )
            )
            assert recorded["event"]["recipe_id"] == recipe["id"]
            assert recorded["recipe"]["times_cooked"] == 1

            detail = _parse_mcp_result(
                await mcp_client.call_tool("get_recipe", {"recipe_id": recipe["id"]})
            )
            assert detail["last_cooked_at"] == "2026-04-18T18:30:00"
            assert detail["times_cooked"] == 1

            history = _parse_mcp_result(
                await mcp_client.call_tool(
                    "get_recipe_cook_history", {"recipe_id": recipe["id"]}
                )
            )
            assert [event["id"] for event in history] == [recorded["event"]["id"]]

            deleted = _parse_mcp_result(
                await mcp_client.call_tool(
                    "delete_recipe_cook_event",
                    {"event_id": recorded["event"]["id"]},
                )
            )
            assert deleted == {"deleted": True, "event_id": recorded["event"]["id"]}
    finally:
        if mcp_mod._db is not None:
            await mcp_mod._db.close()
            mcp_mod._db = None

    detail = await client.get(f"/api/recipes/{recipe['id']}")
    assert detail.json()["times_cooked"] == 0
    assert detail.json()["last_cooked_at"] is None


async def test_mcp_record_missing_recipe_returns_error(client):
    from recipe_app import mcp_server as mcp_mod

    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None

    try:
        async with Client(mcp_mod.mcp) as mcp_client:
            result = _parse_mcp_result(
                await mcp_client.call_tool(
                    "record_recipe_cooked", {"recipe_id": 99999}
                )
            )
            assert "error" in result
            assert "not found" in result["error"]
    finally:
        if mcp_mod._db is not None:
            await mcp_mod._db.close()
            mcp_mod._db = None


async def test_mcp_record_invalid_cooked_at_returns_error(client, create_recipe):
    """MCP `record_recipe_cooked` with non-ISO `cooked_at` should return an
    error dict instead of corrupting the cook-events table with a string
    that fails lexicographic MAX/ORDER BY comparisons."""
    from recipe_app import mcp_server as mcp_mod

    recipe = await create_recipe(title="Bad Timestamp")
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None

    try:
        async with Client(mcp_mod.mcp) as mcp_client:
            result = _parse_mcp_result(
                await mcp_client.call_tool(
                    "record_recipe_cooked",
                    {"recipe_id": recipe["id"], "cooked_at": "not-a-date"},
                )
            )
            assert "error" in result
            assert "Invalid cooked_at" in result["error"]
    finally:
        if mcp_mod._db is not None:
            await mcp_mod._db.close()
            mcp_mod._db = None

    # No event row should have been written.
    assert await _count_cook_events_for_recipe(recipe["id"]) == 0


async def test_v5_migration_is_idempotent(tmp_path, monkeypatch):
    from recipe_app.config import settings
    from recipe_app import db as db_mod

    db_path = tmp_path / "migration.db"
    monkeypatch.setattr(settings, "database_path", db_path)

    db = await aiosqlite.connect(db_path)
    db.row_factory = db_mod._row_to_dict
    try:
        await db.execute("PRAGMA foreign_keys = ON")
        await db_mod.init_schema(db)
        recipe = await db.execute(
            "INSERT INTO recipes (title) VALUES (?)", ("Migrated Recipe",)
        )
        await db.execute(
            """
            INSERT INTO calendar_entries (recipe_id, date, meal_slot)
            VALUES (?, ?, ?)
            """,
            (recipe.lastrowid, "2026-04-18", "dinner"),
        )
        await db.execute("PRAGMA user_version = 4")
        await db.commit()

        await db_mod.run_migrations(db)
        await db_mod.run_migrations(db)

        version_row = await (await db.execute("PRAGMA user_version")).fetchone()
        assert version_row["user_version"] == 5

        recipe_row = await (
            await db.execute(
                "SELECT last_cooked_at, times_cooked FROM recipes WHERE id = ?",
                (recipe.lastrowid,),
            )
        ).fetchone()
        assert recipe_row["last_cooked_at"] is None
        assert recipe_row["times_cooked"] == 0

        event_count = await (
            await db.execute("SELECT COUNT(*) AS count FROM recipe_cook_events")
        ).fetchone()
        assert event_count["count"] == 0
    finally:
        await db.close()


async def test_mcp_get_history_missing_recipe_returns_error(client):
    from recipe_app import mcp_server as mcp_mod
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None
    try:
        async with Client(mcp_mod.mcp) as mcp_client:
            result = _parse_mcp_result(
                await mcp_client.call_tool("get_recipe_cook_history", {"recipe_id": 99999})
            )
            assert isinstance(result, dict)
            assert "error" in result
            assert "not found" in result["error"]
    finally:
        if mcp_mod._db is not None:
            await mcp_mod._db.close()
            mcp_mod._db = None


async def test_mcp_delete_missing_cook_event_returns_error(client):
    from recipe_app import mcp_server as mcp_mod
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None
    try:
        async with Client(mcp_mod.mcp) as mcp_client:
            result = _parse_mcp_result(
                await mcp_client.call_tool("delete_recipe_cook_event", {"event_id": 99999})
            )
            assert isinstance(result, dict)
            assert "error" in result
    finally:
        if mcp_mod._db is not None:
            await mcp_mod._db.close()
            mcp_mod._db = None
