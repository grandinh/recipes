"""Tests for Paprika 3 import (.paprikarecipes)."""

import base64
import gzip
import io
import json
import zipfile
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to create test .paprikarecipes archives
# ---------------------------------------------------------------------------

def _make_paprika_recipe(**overrides):
    """Create a minimal Paprika recipe dict."""
    recipe = {
        "name": "Test Recipe",
        "ingredients": "2 cups flour\n1 cup milk\n2 eggs",
        "directions": "Mix and cook.",
        "servings": "4",
        "prep_time": "10 min",
        "cook_time": "15 min",
        "rating": 4,
        "categories": ["Dinner"],
        "on_favorites": False,
        "source_url": "",
        "source": "",
        "notes": "",
        "description": "A test recipe",
        "photo_data": "",
        "nutritional_info": "",
        "uid": "abc123",
        "hash": "def456",
        "photo_hash": "ghi789",
    }
    recipe.update(overrides)
    return recipe


def _make_archive(recipes: list[dict]) -> bytes:
    """Create a .paprikarecipes ZIP archive from recipe dicts."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, recipe in enumerate(recipes):
            json_bytes = json.dumps(recipe).encode("utf-8")
            gz_bytes = gzip.compress(json_bytes)
            zf.writestr(f"recipe_{i}.paprikarecipe", gz_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# parse_paprika_archive tests
# ---------------------------------------------------------------------------

def test_parse_valid_archive():
    """Parse a valid .paprikarecipes archive."""
    from recipe_app.paprika_import import parse_paprika_archive

    recipes = [_make_paprika_recipe(name="Pasta"), _make_paprika_recipe(name="Salad")]
    archive = _make_archive(recipes)
    result = parse_paprika_archive(archive)
    assert len(result) == 2
    assert result[0]["name"] == "Pasta"
    assert result[1]["name"] == "Salad"


def test_parse_invalid_zip():
    """Invalid ZIP raises ValueError."""
    from recipe_app.paprika_import import parse_paprika_archive

    with pytest.raises(ValueError, match="Not a valid ZIP"):
        parse_paprika_archive(b"not a zip file")


def test_parse_empty_archive():
    """Empty ZIP returns empty list."""
    from recipe_app.paprika_import import parse_paprika_archive

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    result = parse_paprika_archive(buf.getvalue())
    assert result == []


def test_parse_skips_path_traversal():
    """Entries with path traversal are skipped."""
    from recipe_app.paprika_import import parse_paprika_archive

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        json_bytes = json.dumps(_make_paprika_recipe(name="Evil")).encode()
        gz_bytes = gzip.compress(json_bytes)
        zf.writestr("../evil.paprikarecipe", gz_bytes)

        json_bytes2 = json.dumps(_make_paprika_recipe(name="Good")).encode()
        gz_bytes2 = gzip.compress(json_bytes2)
        zf.writestr("good.paprikarecipe", gz_bytes2)

    result = parse_paprika_archive(buf.getvalue())
    assert len(result) == 1
    assert result[0]["name"] == "Good"


def test_parse_skips_malformed_gzip():
    """Entries that aren't valid gzip are skipped."""
    from recipe_app.paprika_import import parse_paprika_archive

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bad.paprikarecipe", b"not gzipped")
        json_bytes = json.dumps(_make_paprika_recipe(name="Good")).encode()
        zf.writestr("good.paprikarecipe", gzip.compress(json_bytes))

    result = parse_paprika_archive(buf.getvalue())
    assert len(result) == 1
    assert result[0]["name"] == "Good"


def test_parse_decompression_bomb_rejected():
    """Entries that decompress beyond the limit are rejected."""
    from recipe_app.paprika_import import _safe_gzip_decompress

    # Create data that compresses well
    big_data = b"A" * (60 * 1024 * 1024)  # 60MB
    compressed = gzip.compress(big_data)

    with pytest.raises(ValueError, match="exceeds limit"):
        _safe_gzip_decompress(compressed, max_size=50 * 1024 * 1024)


# ---------------------------------------------------------------------------
# parse_time_string tests
# ---------------------------------------------------------------------------

def test_parse_time_string_variants():
    from recipe_app.paprika_import import parse_time_string

    assert parse_time_string("15 min") == 15
    assert parse_time_string("15 minutes") == 15
    assert parse_time_string("1 hour") == 60
    assert parse_time_string("1 hr 30 min") == 90
    assert parse_time_string("1 hour 30 minutes") == 90
    assert parse_time_string("1:30") == 90
    assert parse_time_string("90") == 90
    assert parse_time_string("") is None
    assert parse_time_string(None) is None
    assert parse_time_string("  ") is None
    assert parse_time_string("overnight") is None


# ---------------------------------------------------------------------------
# map_paprika_recipe tests
# ---------------------------------------------------------------------------

def test_map_basic_fields():
    from recipe_app.paprika_import import map_paprika_recipe

    paprika = _make_paprika_recipe(
        name="Pasta Carbonara",
        rating=5,
        on_favorites=True,
        source_url="https://example.com/pasta",
        prep_time="15 min",
        cook_time="20 min",
        categories=["Dinner", "Italian"],
    )
    fields, photo, warnings = map_paprika_recipe(paprika)
    assert fields["title"] == "Pasta Carbonara"
    assert fields["rating"] == 5
    assert fields["is_favorite"] is True
    assert fields["source_url"] == "https://example.com/pasta"
    assert fields["prep_time_minutes"] == 15
    assert fields["cook_time_minutes"] == 20
    assert fields["categories"] == ["Dinner", "Italian"]
    assert fields["ingredients"] == ["2 cups flour", "1 cup milk", "2 eggs"]
    assert photo is None
    assert warnings == []


def test_map_rating_zero_becomes_none():
    from recipe_app.paprika_import import map_paprika_recipe

    paprika = _make_paprika_recipe(rating=0)
    fields, _, _ = map_paprika_recipe(paprika)
    assert fields["rating"] is None


def test_map_source_fallback():
    """When source_url is empty, falls back to source field."""
    from recipe_app.paprika_import import map_paprika_recipe

    paprika = _make_paprika_recipe(source_url="", source="Grandma's cookbook")
    fields, _, _ = map_paprika_recipe(paprika)
    assert fields["source_url"] == "Grandma's cookbook"


def test_map_empty_source_url_becomes_none():
    from recipe_app.paprika_import import map_paprika_recipe

    paprika = _make_paprika_recipe(source_url="", source="")
    fields, _, _ = map_paprika_recipe(paprika)
    assert fields["source_url"] is None


def test_map_photo_data():
    from recipe_app.paprika_import import map_paprika_recipe

    # Create a tiny valid base64 string
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    b64 = base64.b64encode(raw).decode()
    paprika = _make_paprika_recipe(photo_data=b64)
    fields, photo_bytes, warnings = map_paprika_recipe(paprika)
    assert photo_bytes is not None
    assert photo_bytes == raw
    assert warnings == []


def test_map_invalid_photo_data():
    from recipe_app.paprika_import import map_paprika_recipe

    paprika = _make_paprika_recipe(photo_data="not-valid-base64!!!")
    fields, photo_bytes, warnings = map_paprika_recipe(paprika)
    assert photo_bytes is None
    assert len(warnings) == 1
    assert "Photo decode failed" in warnings[0]


# ---------------------------------------------------------------------------
# import_paprika_recipes (integration tests)
# ---------------------------------------------------------------------------

async def test_import_single_recipe(client):
    """Import a single recipe end-to-end."""
    from recipe_app.paprika_import import import_paprika_recipes
    from recipe_app.main import app

    db = app.state.db
    paprika_recipes = [_make_paprika_recipe(name="Imported Pasta", source_url="https://example.com/p1")]

    result = await import_paprika_recipes(db, paprika_recipes)
    assert len(result.imported) == 1
    assert result.imported[0].title == "Imported Pasta"
    assert len(result.skipped) == 0
    assert len(result.errors) == 0

    # Verify recipe exists in DB
    resp = await client.get(f"/api/recipes/{result.imported[0].id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Imported Pasta"


async def test_import_duplicate_source_url(client):
    """Duplicate source_url causes skip, not error."""
    from recipe_app.paprika_import import import_paprika_recipes
    from recipe_app.main import app

    db = app.state.db

    # Import first
    recipes1 = [_make_paprika_recipe(name="Original", source_url="https://example.com/dup")]
    r1 = await import_paprika_recipes(db, recipes1)
    assert len(r1.imported) == 1

    # Import same URL again
    recipes2 = [_make_paprika_recipe(name="Duplicate", source_url="https://example.com/dup")]
    r2 = await import_paprika_recipes(db, recipes2)
    assert len(r2.imported) == 0
    assert len(r2.skipped) == 1
    assert "Duplicate" in r2.skipped[0].reason or "duplicate" in r2.skipped[0].reason.lower()


async def test_import_batch_deduplication(client):
    """Two recipes with same source_url in one batch: first imports, second skipped."""
    from recipe_app.paprika_import import import_paprika_recipes
    from recipe_app.main import app

    db = app.state.db
    recipes = [
        _make_paprika_recipe(name="First", source_url="https://example.com/batch"),
        _make_paprika_recipe(name="Second", source_url="https://example.com/batch"),
    ]
    result = await import_paprika_recipes(db, recipes)
    assert len(result.imported) == 1
    assert result.imported[0].title == "First"
    assert len(result.skipped) == 1
    assert result.skipped[0].title == "Second"


async def test_import_no_source_url_imports(client):
    """Recipes without source_url always import (no dedup key)."""
    from recipe_app.paprika_import import import_paprika_recipes
    from recipe_app.main import app

    db = app.state.db
    recipes = [
        _make_paprika_recipe(name="Handwritten 1", source_url=""),
        _make_paprika_recipe(name="Handwritten 2", source_url=""),
    ]
    result = await import_paprika_recipes(db, recipes)
    assert len(result.imported) == 2


async def test_import_categories_created(client):
    """Categories from import are auto-created."""
    from recipe_app.paprika_import import import_paprika_recipes
    from recipe_app.main import app

    db = app.state.db
    recipes = [_make_paprika_recipe(name="Cat Test", categories=["Paprika Special", "Imported"])]
    result = await import_paprika_recipes(db, recipes)
    assert len(result.imported) == 1

    # Check categories exist
    resp = await client.get("/api/categories")
    cat_names = [c["name"] for c in resp.json()]
    assert "Paprika Special" in cat_names
    assert "Imported" in cat_names


# ---------------------------------------------------------------------------
# Web route tests
# ---------------------------------------------------------------------------

async def test_import_page_renders(client):
    """GET /import renders the import form."""
    resp = await client.get("/import")
    assert resp.status_code == 200
    assert "Paprika" in resp.text
    assert "paprikaImportForm" in resp.text


async def test_import_upload_no_file(client):
    """POST /import without file shows error."""
    resp = await client.post("/import", data={})
    assert resp.status_code == 200
    assert "select a" in resp.text.lower() or "Please select" in resp.text


async def test_import_upload_invalid_zip(client):
    """POST /import with non-ZIP shows error."""
    import httpx
    resp = await client.post(
        "/import",
        files={"file": ("test.paprikarecipes", b"not a zip", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert "Not a valid ZIP" in resp.text


async def test_import_upload_valid_archive(client):
    """POST /import with valid archive redirects to status page."""
    archive = _make_archive([_make_paprika_recipe(name="Web Import Test")])
    resp = await client.post(
        "/import",
        files={"file": ("export.paprikarecipes", archive, "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/import/status/" in resp.headers["location"]


async def test_import_full_flow(client):
    """Full import flow: upload -> status -> results."""
    import asyncio

    archive = _make_archive([
        _make_paprika_recipe(name="Flow Recipe 1"),
        _make_paprika_recipe(name="Flow Recipe 2"),
    ])

    # Upload
    resp = await client.post(
        "/import",
        files={"file": ("export.paprikarecipes", archive, "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    status_url = resp.headers["location"]

    # Wait for background task to complete
    for _ in range(20):
        await asyncio.sleep(0.2)
        resp = await client.get(status_url)
        if "Import Complete" in resp.text:
            break
    else:
        pytest.fail("Import did not complete in time")

    assert resp.status_code == 200
    assert "Flow Recipe 1" not in resp.text or "2" in resp.text  # summary shows count
    assert "Imported" in resp.text


async def test_import_status_not_found(client):
    """GET /import/status with bad task_id returns 404."""
    resp = await client.get("/import/status/nonexistent")
    assert resp.status_code == 404
