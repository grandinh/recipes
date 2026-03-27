"""Shared fixtures for recipe app tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Default payloads
# ---------------------------------------------------------------------------

_DEFAULT_RECIPE = {
    "title": "Test Pancakes",
    "description": "Fluffy pancakes",
    "ingredients": ["2 cups flour", "1 cup milk", "2 eggs"],
    "directions": "Mix ingredients. Cook on griddle.",
    "servings": "4 servings",
    "prep_time_minutes": 10,
    "cook_time_minutes": 15,
    "rating": 4,
    "difficulty": "easy",
    "cuisine": "American",
    "categories": ["Breakfast", "Quick"],
}

_DEFAULT_RECIPE_2 = {
    "title": "Chocolate Cake",
    "description": "Rich chocolate cake",
    "ingredients": ["2 cups flour", "1 cup cocoa", "1 cup sugar", "3 eggs"],
    "directions": "Mix dry ingredients. Add wet. Bake at 350F for 30 min.",
    "servings": "8 servings",
    "prep_time_minutes": 20,
    "cook_time_minutes": 30,
    "rating": 5,
    "difficulty": "medium",
    "cuisine": "French",
    "categories": ["Dessert", "Baking"],
    "is_favorite": True,
}


# ---------------------------------------------------------------------------
# Core client fixture — per-test DB isolation via tmp_path
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Async test client with a fresh SQLite DB per test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)

    # Force settings singleton to pick up new path
    from recipe_app.config import settings

    monkeypatch.setattr(settings, "database_path", db_path)

    from recipe_app.db import lifespan
    from recipe_app.main import app

    async with lifespan(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as ac:
            yield ac


# ---------------------------------------------------------------------------
# Payload fixtures (raw dicts — tests control creation)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_recipe():
    """Minimal recipe payload for testing."""
    return dict(_DEFAULT_RECIPE)


@pytest.fixture
def sample_recipe_2():
    """Second recipe for search/filter tests."""
    return dict(_DEFAULT_RECIPE_2)


# ---------------------------------------------------------------------------
# Factory fixtures — create resources via API and return JSON
# ---------------------------------------------------------------------------


@pytest.fixture
def create_recipe(client):
    """Factory: creates a recipe via POST and returns its JSON."""

    async def _create(**overrides):
        payload = {**_DEFAULT_RECIPE, **overrides}
        resp = await client.post("/api/recipes", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _create


@pytest.fixture
def create_calendar_entry(client):
    """Factory: creates a calendar entry via POST and returns its JSON."""

    async def _create(recipe_id, date, meal_slot="dinner"):
        resp = await client.post("/api/calendar/entries", json={
            "recipe_id": recipe_id,
            "date": date,
            "meal_slot": meal_slot,
        })
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _create


@pytest.fixture
def create_pantry_item(client):
    """Factory: creates a pantry item via POST and returns its JSON."""

    async def _create(name, **kwargs):
        resp = await client.post("/api/pantry", json={"name": name, **kwargs})
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _create
