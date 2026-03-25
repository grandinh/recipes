"""Tests for full-text search and filtering."""

import pytest


@pytest.fixture
async def seeded_db(client, sample_recipe, sample_recipe_2):
    """Create two recipes for search tests."""
    r1 = await client.post("/api/recipes", json=sample_recipe)
    r2 = await client.post("/api/recipes", json=sample_recipe_2)
    return r1.json(), r2.json()


@pytest.mark.asyncio
async def test_search_by_keyword(client, seeded_db):
    resp = await client.get("/api/search?q=pancakes")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["title"] == "Test Pancakes" for r in data)


@pytest.mark.asyncio
async def test_search_by_ingredient(client, seeded_db):
    resp = await client.get("/api/search?q=cocoa")
    data = resp.json()
    assert any(r["title"] == "Chocolate Cake" for r in data)
    assert not any(r["title"] == "Test Pancakes" for r in data)


@pytest.mark.asyncio
async def test_search_multi_word(client, seeded_db):
    resp = await client.get("/api/search?q=flour+eggs")
    data = resp.json()
    # Both recipes have flour and eggs
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_search_by_category(client, seeded_db):
    resp = await client.get("/api/search?category=Dessert")
    data = resp.json()
    assert all("Dessert" in r["categories"] for r in data)


@pytest.mark.asyncio
async def test_search_by_rating_min(client, seeded_db):
    resp = await client.get("/api/search?rating_min=5")
    data = resp.json()
    assert all(r["rating"] >= 5 for r in data)


@pytest.mark.asyncio
async def test_search_by_cuisine(client, seeded_db):
    resp = await client.get("/api/search?cuisine=French")
    data = resp.json()
    assert all(r["cuisine"] == "French" for r in data)


@pytest.mark.asyncio
async def test_search_by_favorite(client, seeded_db):
    resp = await client.get("/api/search?is_favorite=true")
    data = resp.json()
    assert all(r["is_favorite"] is True for r in data)


@pytest.mark.asyncio
async def test_search_combined_filters(client, seeded_db):
    resp = await client.get("/api/search?q=chocolate&category=Dessert&rating_min=4")
    data = resp.json()
    assert len(data) >= 1
    for r in data:
        assert r["rating"] >= 4


@pytest.mark.asyncio
async def test_search_pagination(client, seeded_db):
    resp = await client.get("/api/search?limit=1&offset=0")
    data = resp.json()
    assert len(data) <= 1


@pytest.mark.asyncio
async def test_search_sort_name(client, seeded_db):
    resp = await client.get("/api/search?sort=name")
    data = resp.json()
    titles = [r["title"] for r in data]
    assert titles == sorted(titles)


@pytest.mark.asyncio
async def test_search_no_results(client, seeded_db):
    resp = await client.get("/api/search?q=xyznonexistent")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_search_empty_query(client, seeded_db):
    resp = await client.get("/api/search")
    assert resp.status_code == 200
    # Returns all recipes when no filters
    assert len(resp.json()) >= 2
