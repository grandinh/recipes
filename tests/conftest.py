"""Shared fixtures for recipe app tests."""

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Override database path BEFORE importing app modules — each test run gets a fresh DB
_tmp = tempfile.mkdtemp()
os.environ["RECIPE_DATABASE_PATH"] = str(Path(_tmp) / "test.db")

from recipe_app.db import lifespan  # noqa: E402
from recipe_app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    """Async test client with lifespan properly initialised."""
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            yield ac


@pytest.fixture
def sample_recipe():
    """Minimal recipe payload for testing."""
    return {
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


@pytest.fixture
def sample_recipe_2():
    """Second recipe for search/filter tests."""
    return {
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
