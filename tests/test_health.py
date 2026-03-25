"""Tests for the health endpoint."""


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "recipe_count" in data
    assert isinstance(data["recipe_count"], int)


async def test_health_counts_recipes(client, sample_recipe):
    # Get initial count
    resp1 = await client.get("/health")
    initial_count = resp1.json()["recipe_count"]

    # Add a recipe
    await client.post("/api/recipes", json=sample_recipe)

    resp2 = await client.get("/health")
    assert resp2.json()["recipe_count"] == initial_count + 1
