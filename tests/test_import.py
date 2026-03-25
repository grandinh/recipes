"""Tests for URL import endpoint -- uses mocked HTTP responses."""

from unittest.mock import AsyncMock, MagicMock, patch


MOCK_RECIPE_HTML = (
    b'<html><head><script type="application/ld+json">'
    b'{"@context":"https://schema.org","@type":"Recipe",'
    b'"name":"Mock Tomato Soup","description":"A simple tomato soup",'
    b'"recipeIngredient":["4 tomatoes","1 onion","2 cups broth"],'
    b'"recipeInstructions":[{"text":"Chop tomatoes. Saute onion. Add broth. Simmer."}],'
    b'"image":"https://example.com/soup.jpg","totalTime":"PT30M",'
    b'"recipeYield":"4 servings","recipeCategory":"Soup"}'
    b"</script></head><body></body></html>"
)


def _mock_stream_response(html: bytes = MOCK_RECIPE_HTML, content_type: str = "text/html"):
    """Build a mock httpx streaming response."""
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"content-type": content_type}

    async def aiter_bytes(chunk_size=8192):
        yield html

    mock_resp.aiter_bytes = aiter_bytes
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


async def test_import_from_url(client):
    mock_resp = _mock_stream_response()
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("recipe_app.scraper.httpx.AsyncClient", return_value=mock_client),
        patch("recipe_app.scraper.validate_url", return_value=("https://example.com/soup", "93.184.216.34")),
    ):
        resp = await client.post(
            "/api/recipes/import",
            json={"url": "https://example.com/soup"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert "recipe" in data
    assert data["recipe"]["title"] == "Mock Tomato Soup"
    assert data["recipe"]["source_url"] == "https://example.com/soup"
    assert isinstance(data["warnings"], list)


async def test_import_duplicate_url(client):
    mock_resp = _mock_stream_response()
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("recipe_app.scraper.httpx.AsyncClient", return_value=mock_client),
        patch("recipe_app.scraper.validate_url", return_value=("https://example.com/dup-test", "93.184.216.34")),
    ):
        # First import
        resp1 = await client.post(
            "/api/recipes/import",
            json={"url": "https://example.com/dup-test"},
        )
        assert resp1.status_code == 201

        # Second import of same URL — should be 409
        resp2 = await client.post(
            "/api/recipes/import",
            json={"url": "https://example.com/dup-test"},
        )
        assert resp2.status_code == 409


async def test_import_ssrf_blocked(client):
    resp = await client.post(
        "/api/recipes/import",
        json={"url": "http://127.0.0.1:8080/secret"},
    )
    assert resp.status_code == 400
    assert "blocked" in resp.json()["detail"].lower() or "scheme" in resp.json()["detail"].lower()


async def test_import_invalid_scheme(client):
    resp = await client.post(
        "/api/recipes/import",
        json={"url": "ftp://example.com/recipe"},
    )
    assert resp.status_code == 400
