"""Tests for web UI routes returning HTML."""

import pytest


@pytest.mark.asyncio
async def test_home_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_home_page_with_recipes(client, sample_recipe):
    await client.post("/api/recipes", json=sample_recipe)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text


@pytest.mark.asyncio
async def test_recipe_detail_page(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.get(f"/recipe/{recipe_id}")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text
    assert "2 cups flour" in resp.text


@pytest.mark.asyncio
async def test_recipe_detail_not_found(client):
    resp = await client.get("/recipe/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_recipe_page(client):
    resp = await client.get("/add")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_edit_recipe_page(client, sample_recipe):
    create_resp = await client.post("/api/recipes", json=sample_recipe)
    recipe_id = create_resp.json()["id"]

    resp = await client.get(f"/edit/{recipe_id}")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text


@pytest.mark.asyncio
async def test_csp_header(client):
    resp = await client.get("/")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp


@pytest.mark.asyncio
async def test_search_from_web(client, sample_recipe):
    await client.post("/api/recipes", json=sample_recipe)
    resp = await client.get("/?q=pancakes")
    assert resp.status_code == 200
    assert "Test Pancakes" in resp.text
