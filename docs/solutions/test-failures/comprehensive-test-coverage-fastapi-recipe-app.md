---
title: "Comprehensive test coverage expansion for FastAPI recipe app"
category: test-failures
tags:
  - pytest
  - pytest-asyncio
  - fastapi
  - test-isolation
  - factory-fixtures
  - mcp
  - fastmcp
  - htmx
  - aiosqlite
  - sqlite
  - code-review
module: tests
symptom: "72 tests covered only core CRUD; meal plans, grocery lists, pantry, scaling, ingredient parser, pantry matcher, sanitize, web form handlers, HTMX partials, MCP server, and data integrity had zero test coverage; shared DB caused data leakage between tests"
root_cause: "Missing test files for three feature domains and multiple utility modules; shared single-database conftest prevented reliable assertions and parallel execution; MCP tests required fastmcp Client integration pattern not yet established"
date: 2026-03-25
---

# Comprehensive Test Coverage for FastAPI Recipe App

## Problem

A personal recipe manager (FastAPI + aiosqlite + HTMX + MCP) had 72 tests covering only recipe CRUD, search, categories, health, basic web UI renders, security functions, and import. Three entire feature domains (meal plans, grocery lists, pantry), four utility modules (scaling, ingredient parser, pantry matcher, sanitize), web form POST handlers, HTMX partial rendering, the MCP server (24+ tools), and data integrity (FK cascades, concurrent writes) had **zero** test coverage.

The existing test infrastructure used a **shared SQLite database** across all tests (`tempfile.mkdtemp()` at module import time), forcing tests to use weak `>=` assertions for counts and creating ordering dependencies.

## Root Cause

1. **Missing test files** — new features (meal plans, grocery lists, pantry) were added without corresponding test files
2. **Shared DB architecture** — one temp DB per test run meant data accumulated, preventing exact assertions
3. **No MCP testing pattern** — the fastmcp Client integration approach wasn't established
4. **Deep fixture chains** — the proposed design had 5-level chains that would have been fragile

## Solution

### 1. Test Infrastructure Overhaul (conftest.py)

The key architectural decision: **per-test DB isolation via `tmp_path`**.

```python
@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)
    from recipe_app.config import settings
    monkeypatch.setattr(settings, "database_path", db_path)

    from recipe_app.db import lifespan
    from recipe_app.main import app

    async with lifespan(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            yield ac
```

**Factory fixtures** (max chain depth 2):

```python
@pytest.fixture
def create_recipe(client):
    async def _create(**overrides):
        payload = {**_DEFAULT_RECIPE, **overrides}
        resp = await client.post("/api/recipes", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()
    return _create
```

**pyproject.toml addition:**
```toml
asyncio_default_fixture_loop_scope = "function"
```

### 2. API Integration Tests

- **test_meal_plans.py** (~19 tests): Full CRUD + entries + cascades + FK violation docs
- **test_grocery_lists.py** (~16 tests): Generate, list, get, add item, check, delete, aggregation
- **test_pantry.py** (~17 tests): CRUD + UNIQUE constraint + expiring filter + matches

### 3. Pure Function Unit Tests (sync def, class-grouped)

```python
class TestFormatQuantity:
    @pytest.mark.parametrize("value,expected", [
        pytest.param(3.0, "3", id="whole"),
        pytest.param(0.5, "1/2", id="half"),
        pytest.param(1.5, "1 1/2", id="mixed"),
    ])
    def test_format_quantity(self, value, expected):
        assert format_quantity(value) == expected
```

- **test_scaling.py**: format_quantity, scale_ingredient, _build_scaled_text
- **test_ingredient_parser.py**: parse_ingredient, _fraction_to_float
- **test_pantry_matcher.py**: _matches_pantry, find_matching_recipes_sync
- **test_sanitize_module.py**: sanitize_field (DB write-path), sanitize_url

### 4. Web UI + HTMX Tests

- Form POST handlers use `data=` (not `json=`) with `follow_redirects=False`
- HTMX fragments assert `"<html" not in resp.text`

### 5. MCP Tests via fastmcp Client

```python
def _parse_result(result):
    """Extract structured data from MCP tool result."""
    if not result or not result.content:
        sc = getattr(result, "structured_content", None)
        if sc is not None and "result" in sc:
            return sc["result"]
        return None
    item = result.content[0]
    text = item.text if hasattr(item, "text") else str(item)
    return json.loads(text)

@pytest_asyncio.fixture
async def mcp_client(tmp_path, monkeypatch):
    # Defensive close before reset
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
    mcp_mod._db = None
    async with Client(mcp) as client:
        yield client
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None
```

### 6. Data Integrity Tests

- FK canary test (must be first — verifies `PRAGMA foreign_keys = ON`)
- CASCADE delete (recipe → meal plan entries)
- SET NULL (meal plan → grocery list)
- Concurrent writes via `asyncio.gather`

## Key Patterns

| Pattern | When to use |
|---|---|
| `data=` for form POSTs | Web UI route tests (HTML forms) |
| `json=` for API endpoints | REST API route tests |
| sync `def` for pure functions | scaling, parsing, matching, sanitize |
| `async def` for HTTP tests | All integration tests using httpx AsyncClient |
| Factory fixtures return JSON dicts | `create_recipe()`, `create_meal_plan()`, `create_pantry_item()` |
| Max fixture chain depth: 2 | `client -> factory`, never deeper |
| `raise_app_exceptions=False` | Realistic error codes instead of leaked exceptions |
| `tmp_path` per test | Complete DB isolation, no flakiness |
| `_parse_result()` for MCP | Structured assertions, not `in str(result)` |

## Bugs Found During Testing

1. FK constraint errors return raw 500 (meal plan entries, pantry duplicates)
2. Open redirect via Referer header in form handlers
3. `_form_to_recipe_create` crashes on non-numeric input (`int()` ValueError)
4. MCP `connect()` doesn't call `run_migrations()` — fresh DBs lack tables
5. Grocery list detail template rendering fails (500)
6. No sanitization on meal plan names, grocery items, pantry names

## Prevention Strategies

### Never use shared databases in tests
Each test gets its own `tmp_path` database. This enables exact assertions, parallel execution (pytest-xdist), and zero ordering dependencies.

### Match test function type to the code under test
- Pure functions → sync `def test_*` (no async overhead)
- HTTP endpoints → `async def test_*` (await the client)
- Never add `@pytest.mark.asyncio` when `asyncio_mode = "auto"` is set

### Parse MCP results structurally
Never do `assert "X" in str(result)`. Always parse via `_parse_result()` and assert on specific dict keys/values.

### Reset MCP `_db` global defensively
Close before nulling at fixture start AND teardown. One leaked connection can corrupt all subsequent tests.

### Extract IDs from responses — never hardcode
`recipe_id = create_resp.json()["id"]`, not `recipe_id = 1`.

### Check error response bodies for leaks
If a test expects a 500, always assert `"Traceback" not in resp.text`.

### Use xfail for known bugs, not permissive assertions
`@pytest.mark.xfail(reason="Issue #42", strict=False)` signals clearly when a bug is fixed. `assert status in (200, 500)` silently passes either way.

## Results

| Metric | Before | After |
|--------|--------|-------|
| Total tests | 72 | 246 |
| Test files | 7 | 17 |
| Runtime | 0.93s (shared DB) | ~10s (per-test isolation) |
| Feature coverage | recipes, search, categories only | All domains + MCP + data integrity |
| Test isolation | Shared DB, flaky | Per-test tmp_path, deterministic |

## Cross-References

- **Plan:** `docs/plans/2026-03-25-002-feat-full-automated-test-coverage-plan.md`
- **Review todos:** `todos/001-complete-p1-mcp-test-assertions-too-loose.md` through `006-pending-p3-weak-test-names.md`
- **Project testing docs:** `CLAUDE.md` (lines 41-45, 58)
