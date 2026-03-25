---
title: "feat: Full Automated Test Coverage"
type: feat
status: completed
date: 2026-03-25
deepened: 2026-03-25
---

# Full Automated Test Coverage

## Enhancement Summary

**Deepened on:** 2026-03-25
**Research agents used:** best-practices-researcher, framework-docs-researcher, kieran-python-reviewer, performance-oracle, security-sentinel, architecture-strategist, pattern-recognition-specialist, agent-native-reviewer, data-integrity-guardian

### Key Improvements
1. **Test isolation overhaul** -- switch from shared DB to per-test `tmp_path` DB, eliminating flaky `>=` assertions and test ordering dependencies
2. **MCP testing via fastmcp `Client`** -- use the in-memory client (not raw function calls) to catch protocol-level bugs and the `connect()` migration gap
3. **Security test layer added** -- 20+ new security-focused tests for stored XSS, open redirect, FK error leaks, and input coercion crashes
4. **Fixture architecture flattened** -- factory-as-fixture pattern replaces 5-level chain, keeping max depth at 2
5. **FK enforcement canary test** -- first test in suite verifies `PRAGMA foreign_keys = ON` is actually active
6. **Production bugs surfaced** -- `connect()` missing `run_migrations()`, open redirect via Referer, missing MCP tools (`check_grocery_item`, `add_grocery_item`)

### New Considerations Discovered
- `generate_grocery_list` is not atomic -- partial item INSERT failure orphans the list header
- `update_pantry_item` uses `exclude_none=True` so fields cannot be cleared to NULL
- MCP error return formats are inconsistent (string vs dict vs None)
- Two divergent `sanitize_field` implementations (scraper vs sanitize module) with different allowed tags
- `image_url` from scraped recipes bypasses SSRF validation

---

## Overview

The recipe app has 72 passing tests covering recipes CRUD, search, categories, health, basic web UI renders, security functions, and import. However, three entire feature domains (meal plans, grocery lists, pantry) plus utility modules, web form handlers, HTMX partials, and the MCP server have **zero test coverage**. This plan adds ~170+ tests across 10 new test files to reach ~85-90% coverage.

## Problem Statement / Motivation

- **Meal Plans API** (7 endpoints), **Grocery Lists API** (6 endpoints), and **Pantry API** (5 endpoints) have zero tests
- **Web UI form POST handlers** (13 handlers) have zero tests -- regressions go unnoticed
- **HTMX partial rendering** is the core UX pattern and is completely untested
- **Pure function modules** (`scaling.py`, `ingredient_parser.py`, `pantry_matcher.py`) are ideal unit test candidates with zero coverage
- **MCP server** has 24 tools, all untested -- and 2 tools are missing entirely
- Research uncovered **several latent bugs** (FK constraint errors returning 500, missing type coercion error handling, open redirect, missing migrations in MCP `connect()`) that tests will document and expose

## Proposed Solution

Add tests in priority order. Overhaul test infrastructure first (per-test isolation, flattened fixtures), then cover all domains.

### Phase 0: Test Infrastructure Overhaul

Before writing new tests, fix the shared-DB problem and modernize the fixture architecture.

**0a. Per-test database isolation**

The current `conftest.py` creates one temp DB at module import time, shared across all 72 tests. At 240+ tests, data accumulation causes flaky tests and makes `>=` assertions meaningless.

Switch to per-test isolation using pytest's `tmp_path`:

```python
# tests/conftest.py — revised client fixture
@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Each test gets its own SQLite DB file — zero data leakage."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)
    # Force settings to re-read
    from recipe_app.config import settings
    monkeypatch.setattr(settings, "database_path", db_path)
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            yield ac
```

### Research Insights

**Why per-test isolation matters at scale:**
- The current shared DB means every `test_list_*` must use `assert len(data) >= N` instead of exact counts. At 240 tests, leftover data makes assertions meaningless -- a broken feature can "pass" because another test's data satisfies the `>=` check.
- Per-test `tmp_path` costs ~2-5ms per test for schema creation. At 240 tests that adds ~0.5-1.2s -- negligible vs. the debugging time saved.
- With per-test DBs, tests can use **exact assertions** (`assert len(data) == 2`), making failures immediately diagnostic.

**Performance projection (from performance-oracle):**
- Current 72 tests: 0.94s
- Projected 240 tests with per-test DB: 3-5s (acceptable)
- Dominant cost is lifespan re-entry (~18ms per test) -- acceptable at this scale

**pyproject.toml additions:**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"  # suppress deprecation warning
```

**0b. Factory-as-fixture pattern (flatten fixture chain)**

Replace the proposed 5-level fixture chain with flat factory fixtures. Max depth: `client -> factory`:

```python
# tests/conftest.py — factory fixtures

@pytest.fixture
def sample_recipe():
    """Raw payload dict — tests control creation."""
    return {"title": "Test Pancakes", "ingredients": ["2 cups flour", "1 cup milk"], ...}

@pytest.fixture
def sample_recipe_2():
    return {"title": "Chocolate Cake", "ingredients": ["3 cups flour", "1 cup sugar"], ...}

@pytest.fixture
def create_recipe(client):
    """Factory: creates a recipe via API and returns its JSON."""
    async def _create(**overrides):
        payload = {**DEFAULT_RECIPE, **overrides}
        resp = await client.post("/api/recipes", json=payload)
        assert resp.status_code == 201
        return resp.json()
    return _create

@pytest.fixture
def create_meal_plan(client):
    """Factory: creates a meal plan and returns its JSON."""
    async def _create(name="Test Plan"):
        resp = await client.post("/api/meal-plans", json={"name": name})
        assert resp.status_code == 201
        return resp.json()
    return _create

@pytest.fixture
def create_pantry_item(client):
    """Factory: creates a pantry item and returns its JSON."""
    async def _create(name, **kwargs):
        resp = await client.post("/api/pantry", json={"name": name, **kwargs})
        assert resp.status_code == 201
        return resp.json()
    return _create
```

### Research Insights

**Why factory-as-fixture (from kieran-python-reviewer + architecture-strategist):**
- Deep chains (`client -> recipe -> plan -> entries -> grocery_list`) mean a grocery test fails with an opaque traceback when a meal plan bug is the cause
- Factory fixtures keep chains at 2 levels: `client -> create_recipe`. Each test composes exactly the state it needs, visible in the test body
- Pantry tests MUST use unique names per test to avoid UNIQUE constraint collisions -- factory fixtures naturally support `create_pantry_item(f"flour-{uuid4().hex[:8]}")`

**0c. FK enforcement canary test**

This MUST be the first test in the suite. If FK enforcement is off, every cascade/constraint test is meaningless.

```python
# tests/test_data_integrity.py
@pytest.mark.asyncio
async def test_foreign_keys_are_enforced(client, create_recipe, create_meal_plan):
    """Canary test: verify PRAGMA foreign_keys = ON is active."""
    plan = await create_meal_plan()
    resp = await client.post(
        f"/api/meal-plans/{plan['id']}/entries",
        json={"recipe_id": 999999, "date": "2026-03-25", "meal_slot": "dinner"},
    )
    # If FK enforcement is on, this should fail (500 due to unhandled IntegrityError)
    # If FK enforcement is off, this silently succeeds — which means all cascade tests are invalid
    assert resp.status_code != 201, "FK enforcement appears to be OFF — cascades won't work"
```

---

### Phase 1: Meal Plans/Grocery/Pantry API Tests

**`tests/test_meal_plans.py`** (~20 tests):

| Test | Endpoint | Scenario |
|------|----------|----------|
| `test_create_meal_plan` | `POST /api/meal-plans` | Happy path |
| `test_create_meal_plan_empty_name` | `POST /api/meal-plans` | 422 validation |
| `test_list_meal_plans` | `GET /api/meal-plans` | Returns list |
| `test_list_meal_plans_empty` | `GET /api/meal-plans` | Empty list |
| `test_get_meal_plan` | `GET /api/meal-plans/{id}` | Found |
| `test_get_meal_plan_not_found` | `GET /api/meal-plans/{id}` | 404 |
| `test_update_meal_plan` | `PATCH /api/meal-plans/{id}` | Rename |
| `test_update_meal_plan_not_found` | `PATCH /api/meal-plans/{id}` | 404 |
| `test_delete_meal_plan` | `DELETE /api/meal-plans/{id}` | Found |
| `test_delete_meal_plan_not_found` | `DELETE /api/meal-plans/{id}` | 404 |
| `test_delete_meal_plan_cascades_entries` | `DELETE /api/meal-plans/{id}` | Verify entries are deleted |
| `test_add_entry` | `POST /api/meal-plans/{id}/entries` | Happy path |
| `test_add_entry_plan_not_found` | `POST /api/meal-plans/{id}/entries` | 404 |
| `test_add_entry_recipe_not_found` | `POST /api/meal-plans/{id}/entries` | FK error -- documents 500 bug |
| `test_add_entry_invalid_meal_slot` | `POST /api/meal-plans/{id}/entries` | 422 from Literal constraint |
| `test_add_entry_servings_override_null` | `POST /api/meal-plans/{id}/entries` | Nullable field round-trip |
| `test_remove_entry` | `DELETE /api/meal-plans/entries/{id}` | Happy path |
| `test_remove_entry_not_found` | `DELETE /api/meal-plans/entries/{id}` | 404 |
| `test_get_meal_plan_includes_entries` | `GET /api/meal-plans/{id}` | Entries in response, exact count |
| `test_get_meal_plan_entry_count_after_recipe_delete` | `GET /api/meal-plans/{id}` | CASCADE + INNER JOIN interaction |

### Research Insights

**Data integrity (from data-integrity-guardian):**
- `get_meal_plan` uses INNER JOIN on recipes. If a recipe is deleted, CASCADE removes the entry, so the INNER JOIN is correct. But the test must verify the entry is actually CASCADE-deleted (not just hidden by the JOIN).
- `MealPlanEntryCreate.date` has no format validation -- `"banana"` would be accepted. Test with a real date and document the gap.
- Verify `test_add_entry_recipe_not_found` response does NOT contain "IntegrityError", "sqlite3", or file paths (security-sentinel finding).

**`tests/test_grocery_lists.py`** (~18 tests):

| Test | Endpoint | Scenario |
|------|----------|----------|
| `test_generate_from_meal_plan` | `POST /api/grocery-lists/generate` | With meal_plan_id |
| `test_generate_from_recipe_ids` | `POST /api/grocery-lists/generate` | With recipe_ids list |
| `test_generate_empty_plan` | `POST /api/grocery-lists/generate` | Plan with no entries |
| `test_generate_nonexistent_plan` | `POST /api/grocery-lists/generate` | Silently creates empty list -- document |
| `test_generate_nonexistent_recipes` | `POST /api/grocery-lists/generate` | All IDs invalid |
| `test_generate_empty_recipe_ids` | `POST /api/grocery-lists/generate` | `recipe_ids=[]` triggers 400 |
| `test_generate_deduplicates_ingredients` | `POST /api/grocery-lists/generate` | Same ingredient across recipes |
| `test_generate_from_recipe_with_no_ingredients` | `POST /api/grocery-lists/generate` | Zero items in list |
| `test_list_grocery_lists` | `GET /api/grocery-lists` | Returns list with counts |
| `test_list_grocery_lists_empty` | `GET /api/grocery-lists` | Empty |
| `test_get_grocery_list` | `GET /api/grocery-lists/{id}` | Found with items |
| `test_get_grocery_list_not_found` | `GET /api/grocery-lists/{id}` | 404 |
| `test_add_manual_item` | `POST /api/grocery-lists/{id}/items` | Happy path |
| `test_add_item_list_not_found` | `POST /api/grocery-lists/{id}/items` | 404 |
| `test_check_item` | `PATCH /api/grocery-lists/items/{id}` | Toggle checked |
| `test_check_item_not_found` | `PATCH /api/grocery-lists/items/{id}` | 404 |
| `test_delete_grocery_list` | `DELETE /api/grocery-lists/{id}` | Found |
| `test_delete_grocery_list_cascades_items` | `DELETE /api/grocery-lists/{id}` | Items also deleted |

### Research Insights

**Data integrity (from data-integrity-guardian):**
- `generate_grocery_list` is NOT atomic -- if an item INSERT fails mid-way, the list header is committed but items are partially written. Test should verify that successful generation creates both header and all expected items.
- Missing CASCADE test: `test_delete_grocery_list_cascades_items` was absent from original plan. Must verify items are deleted, not orphaned.
- `generate_grocery_list` with nonexistent `meal_plan_id` silently creates an empty list linked to a non-existent plan. With FK enforcement ON, this should actually fail since `meal_plan_id` references `meal_plans(id)`. Test documents whether FK catches this.

**`tests/test_pantry.py`** (~18 tests):

| Test | Endpoint | Scenario |
|------|----------|----------|
| `test_add_pantry_item` | `POST /api/pantry` | Happy path, all fields |
| `test_add_pantry_item_minimal` | `POST /api/pantry` | Name only, nullables round-trip |
| `test_add_duplicate_name` | `POST /api/pantry` | Case-insensitive duplicate -- documents 500 |
| `test_add_duplicate_name_case_variant` | `POST /api/pantry` | "Flour" then "flour" -- COLLATE NOCASE |
| `test_add_unique_after_delete` | `POST /api/pantry` | Delete "Flour" then re-create -- should succeed |
| `test_list_pantry_items` | `GET /api/pantry` | Returns list |
| `test_list_pantry_items_empty` | `GET /api/pantry` | Empty |
| `test_list_expiring_soon` | `GET /api/pantry?expiring_within_days=7` | Filter by expiration |
| `test_update_pantry_item` | `PATCH /api/pantry/{id}` | Partial update |
| `test_update_pantry_item_not_found` | `PATCH /api/pantry/{id}` | 404 |
| `test_update_pantry_item_empty_body` | `PATCH /api/pantry/{id}` | 400 no fields |
| `test_update_rename_to_duplicate` | `PATCH /api/pantry/{id}` | UNIQUE violation -- documents 500 |
| `test_update_cannot_clear_to_null` | `PATCH /api/pantry/{id}` | `exclude_none` limitation |
| `test_delete_pantry_item` | `DELETE /api/pantry/{id}` | Found |
| `test_delete_pantry_item_not_found` | `DELETE /api/pantry/{id}` | 404 |
| `test_pantry_matches` | `GET /api/pantry/matches` | With matching recipes |
| `test_pantry_matches_empty_pantry` | `GET /api/pantry/matches` | No pantry items |
| `test_pantry_matches_max_missing` | `GET /api/pantry/matches?max_missing=0` | Strict matching |

### Research Insights

**Unique name handling (from data-integrity-guardian + kieran-python-reviewer):**
- Every pantry test must use unique names. Use factory fixture with UUID suffix.
- `test_add_unique_after_delete` prevents regression where soft-delete logic might block re-creation.
- `test_update_cannot_clear_to_null` documents that `PATCH` with `{"expiration_date": null}` is silently ignored due to `exclude_none=True`.
- `quantity` is a REAL column -- verify round-trip of `1.5` (not coerced to int or string).

---

### Phase 2: Pure Function Unit Tests

All functions are synchronous. Tests MUST use sync `def test_*` (not `async def`), grouped in classes, following the `test_security.py` pattern. Use `pytest.mark.parametrize` heavily.

**`tests/test_scaling.py`** (~18 tests):

```python
# tests/test_scaling.py — sync unit tests, class-grouped
import pytest
from recipe_app.scaling import format_quantity, scale_ingredient, scale_recipe_ingredients

class TestFormatQuantity:
    @pytest.mark.parametrize("value,expected", [
        pytest.param(3.0, "3", id="whole"),
        pytest.param(0.5, "1/2", id="half"),
        pytest.param(1.5, "1 1/2", id="mixed"),
        pytest.param(0.333, "1/3", id="third"),
        pytest.param(0.125, "1/8", id="eighth"),
        pytest.param(0.0, "0", id="zero"),
        pytest.param(1000.5, "1000 1/2", id="large-mixed"),
    ])
    def test_format_quantity(self, value, expected):
        assert format_quantity(value) == expected

    def test_format_quantity_negative(self):
        """Document behavior for negative values (nonsensical but should not crash)."""
        result = format_quantity(-0.5)
        assert isinstance(result, str)

class TestScaleIngredient:
    def test_double(self): ...         # 2 cups × 2 = 4 cups
    def test_half(self): ...           # 2 cups × 0.5 = 1 cup
    def test_not_scalable(self): ...   # salt to taste unchanged
    def test_range(self): ...          # 2-3 cups × 2 = 4-6 cups
    def test_no_quantity(self): ...    # None quantity
    def test_zero_factor(self): ...    # × 0 edge case

class TestScaleRecipeIngredients:
    def test_multiple_ingredients(self): ...
    def test_empty_list(self): ...

class TestBuildScaledText:
    def test_with_unit(self): ...      # "4 cups flour"
    def test_no_unit(self): ...        # "3 eggs"
    def test_with_prep(self): ...      # "2 cups flour, sifted"
    def test_range(self): ...          # "4-6 cups flour"
```

**`tests/test_ingredient_parser.py`** (~12 tests):

```python
# tests/test_ingredient_parser.py — sync unit tests
import pytest
from recipe_app.ingredient_parser import parse_ingredient, parse_recipe_ingredients

class TestParseIngredient:
    def test_numeric(self): ...        # "2 cups flour" → quantity=2.0, unit="cups", name="flour"
    def test_fraction(self): ...       # "1/2 cup milk" → quantity=0.5
    def test_no_quantity(self): ...    # "salt to taste" → scalable=False
    def test_string_quantity(self): ...# "1 dozen eggs" → scalable=False
    def test_empty_string(self): ...   # "" → fallback
    def test_with_preparation(self):...# "2 cloves garlic, minced"
    def test_fallback_on_failure(self):# malformed input → fallback dict

class TestParseRecipeIngredients:
    def test_batch(self): ...          # list of ingredients
    def test_batch_empty(self): ...    # empty list

class TestFractionToFloat:
    def test_half(self): ...           # 1/2 → 0.5
    def test_quarter(self): ...        # 1/4 → 0.25
```

### Research Insights

**Pattern compliance (from pattern-recognition-specialist):**
- Sync functions MUST use sync `def test_*` to match `test_security.py` precedent
- Class grouping (e.g., `class TestFormatQuantity`) matches existing `TestSSRFProtection`, `TestXSSSanitization`
- Test NLP functions with known stable inputs (integration-style), not mocks -- matches how `test_security.py` tests `validate_url` with real DNS resolution
- `parse_ingredient` calls `ingredient_parser_nlp` which costs ~603ms to import on first call. Add a session-scoped preload fixture to avoid one-test outlier in `--durations` output

**`tests/test_pantry_matcher.py`** (~12 tests):

```python
# tests/test_pantry_matcher.py — sync unit tests (test _matches_pantry and find_matching_recipes_sync)
from recipe_app.pantry_matcher import find_matching_recipes_sync, _matches_pantry

class TestMatchesPantry:
    def test_exact_match(self): ...
    def test_substring_match(self): ...
    def test_no_match(self): ...
    def test_case_insensitive(self): ...
    def test_short_name(self): ...     # 1-char name behavior

class TestFindMatchingRecipesSync:
    def test_empty_pantry(self): ...
    def test_all_matched(self): ...
    def test_partial_match(self): ...
    def test_max_missing_filter(self): ...
    def test_sort_order(self): ...
    def test_json_string_ingredients(self): ...
    def test_list_ingredients(self): ...
```

**`tests/test_sanitize_module.py`** (~14 tests):

```python
# tests/test_sanitize_module.py — imports from recipe_app.sanitize (NOT scraper)
# The DB layer uses sanitize.py; test_security.py tests the scraper's version
from recipe_app.sanitize import sanitize_field, sanitize_url

class TestSanitizeField:
    def test_strips_script(self): ...
    def test_allows_safe_tags(self): ...       # <b>, <ul>, <li>, <img>, <h1>-<h4> (broader than scraper)
    def test_strips_onclick(self): ...
    def test_strips_img_onerror(self): ...     # onerror not in ALLOWED_ATTRS
    def test_img_javascript_src(self): ...     # <img src="javascript:alert(1)">
    def test_strips_iframe(self): ...
    def test_none_returns_none(self): ...      # differs from scraper which returns ""
    def test_empty(self): ...

class TestSanitizeUrl:
    def test_valid_https(self): ...
    def test_valid_http(self): ...
    def test_javascript_scheme(self): ...
    def test_data_scheme(self): ...
    def test_ftp_scheme(self): ...
    def test_empty(self): ...
```

### Research Insights

**Security (from security-sentinel):**
- The DB-layer `sanitize.sanitize_field` is COMPLETELY untested -- existing `test_security.py` tests the scraper's different implementation
- `sanitize.sanitize_field(None)` returns `None` while `scraper.sanitize_field(None)` returns `""` -- different behavior, must be tested independently
- `sanitize.py` allows `img` tag with `src` and `alt` attrs. `<img src="javascript:alert(1)">` may pass bleach depending on version. Test this explicitly.
- Meal plan names, grocery item text, and pantry names are NOT sanitized before DB write -- they bypass `sanitize_field` entirely. Tests should verify this by sending XSS payloads and checking what the API returns.

---

### Phase 3: Web UI Form & HTMX Tests

**`tests/test_web_ui_forms.py`** (~22 tests):

Tests for all POST handlers. Use `data=` (not `json=`), `follow_redirects=False` to assert 303 + Location header.

```python
# tests/test_web_ui_forms.py

# Recipe form handlers
async def test_add_recipe_form(client):
    resp = await client.post("/add", data={
        "title": "Form Recipe", "ingredients": "2 cups flour\n1 cup milk",
        "directions": "Mix.", "categories": "Dinner,Quick",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/recipe/" in resp.headers["location"]

async def test_add_recipe_form_non_numeric_time(client):
    """Documents bug: int() crashes on non-numeric prep_time_minutes."""
    resp = await client.post("/add", data={"title": "Test", "prep_time_minutes": "abc"})
    # Currently returns 500 due to ValueError — should be 400/422
    assert resp.status_code in (303, 400, 422, 500)  # documents actual behavior

async def test_edit_recipe_form(client, create_recipe): ...
async def test_delete_recipe_form(client, create_recipe): ...

# Meal plan form handlers
async def test_create_meal_plan_form(client): ...
async def test_add_recipe_to_plan_form(client, create_recipe, create_meal_plan): ...
async def test_remove_entry_form(client): ...
async def test_delete_meal_plan_form(client, create_meal_plan): ...

# Grocery list form handlers
async def test_generate_grocery_list_form(client, create_recipe, create_meal_plan): ...
async def test_check_grocery_item_form(client): ...
async def test_add_grocery_item_form(client): ...
async def test_delete_grocery_list_form(client): ...

# Pantry form handlers
async def test_add_pantry_item_form(client): ...
async def test_delete_pantry_item_form(client, create_pantry_item): ...

# Security: open redirect via Referer
async def test_form_redirect_ignores_external_referer(client, create_meal_plan):
    """Documents open redirect bug in Referer-based redirects."""
    plan = await create_meal_plan()
    resp = await client.post(
        f"/meal-plans/{plan['id']}/delete",
        headers={"referer": "https://evil.com/phishing"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    # Should redirect to local path, not external URL
    assert not location.startswith("http")  # Documents whether this is a bug

# Security: extra form fields ignored
async def test_form_extra_fields_ignored(client):
    resp = await client.post("/add", data={
        "title": "Test", "id": "999", "created_at": "2020-01-01",
    }, follow_redirects=False)
    assert resp.status_code == 303
```

### Research Insights

**httpx form data (from framework-docs-researcher):**
- `data=dict` sends `application/x-www-form-urlencoded` -- required for `request.form()` in FastAPI
- `json=dict` sends `application/json` -- used for API endpoints with Pydantic models
- Mixing these up causes silent 422 errors from Pydantic (body is None)
- `follow_redirects=False` is httpx default (unlike `requests` which follows). Always explicit.

**Security (from security-sentinel):**
- Open redirect via `Referer` header at `main.py:215` -- `return RedirectResponse(referer, status_code=303)`. An attacker can set Referer to `https://evil.com`. This is a real vulnerability.
- `int(form.get("prep_time_minutes"))` crashes with ValueError on non-numeric input. Test documents the crash.
- Extra form fields like `id=999` or `created_at=2020-01-01` should be silently ignored by Pydantic. Verify.

**`tests/test_web_ui_pages.py`** -- merge into existing `test_web_ui.py`:

Add to existing `test_web_ui.py` rather than creating a new file (architecture-strategist recommendation):

```python
# Additional tests in tests/test_web_ui.py
async def test_meal_plans_page(client): ...
async def test_meal_plan_detail_page(client, create_meal_plan): ...
async def test_grocery_lists_page(client): ...
async def test_grocery_list_detail_page(client): ...
async def test_pantry_page(client): ...
async def test_pantry_what_can_i_make_page(client): ...
async def test_meal_plan_detail_not_found(client): ...
async def test_grocery_list_detail_not_found(client): ...
```

**`tests/test_htmx_partials.py`** (~8 tests):

```python
# tests/test_htmx_partials.py
HTMX_HEADERS = {"hx-request": "true"}

async def test_home_htmx_returns_fragment(client, create_recipe):
    recipe = await create_recipe(title="HTMX Test Recipe")
    resp = await client.get("/", headers=HTMX_HEADERS)
    assert resp.status_code == 200
    assert "<!DOCTYPE" not in resp.text   # fragment, not full page
    assert "<html" not in resp.text       # no page wrapper
    assert "HTMX Test Recipe" in resp.text

async def test_home_full_page_has_wrapper(client, create_recipe):
    """Contrast: without hx-request header, full page is returned."""
    await create_recipe(title="Full Page Recipe")
    resp = await client.get("/")
    assert "<html" in resp.text           # full document
    assert "Full Page Recipe" in resp.text

# Additional HTMX partial tests
async def test_pantry_add_htmx(client): ...
async def test_grocery_check_htmx(client): ...
async def test_grocery_add_item_htmx(client): ...
async def test_meal_plan_add_recipe_htmx(client): ...
```

### Research Insights

**jinja2-fragments behavior (from framework-docs-researcher):**
- `block_name=` parameter on `TemplateResponse` renders only the named `{% block %}`, not the full template
- When `block_name` is `None`, full template renders normally
- Fragment responses do NOT contain `<html>`, `<head>`, `<body>` wrapper elements
- Both return `text/html` content type and status 200
- Test both the fragment AND full-page versions of the same route to catch regressions in either direction

---

### Phase 4: Cross-Feature Integration & MCP

**`tests/test_data_integrity.py`** (~10 tests):

```python
# tests/test_data_integrity.py — FK enforcement, cascades, cross-feature flows

async def test_foreign_keys_are_enforced(client, create_meal_plan):
    """CANARY: must be first test. Verifies PRAGMA foreign_keys = ON."""

async def test_full_meal_planning_flow(client, create_recipe):
    """Recipe → meal plan → add entries → generate grocery list → verify items."""

async def test_delete_recipe_cascades_meal_plan_entries(client, create_recipe, create_meal_plan):
    """ON DELETE CASCADE: recipe deletion removes referencing entries."""

async def test_delete_meal_plan_nullifies_grocery_list(client, create_recipe, create_meal_plan):
    """ON DELETE SET NULL: plan deletion preserves list but nullifies meal_plan_id.
    Must verify: list still exists, items preserved, meal_plan_id is None."""

async def test_delete_grocery_list_cascades_items(client):
    """ON DELETE CASCADE: list deletion removes all items."""

async def test_delete_recipe_cascades_category_junction(client, create_recipe):
    """ON DELETE CASCADE: recipe deletion cleans up recipe_categories rows."""

async def test_pantry_matches_after_adding_items(client, create_recipe, create_pantry_item):
    """Add pantry items matching recipe ingredients → verify match endpoint."""

async def test_generate_grocery_list_aggregates_ingredients(client, create_recipe):
    """Same ingredient across recipes appears once (aggregated) in list."""

async def test_concurrent_writes_serialized(client, create_recipe):
    """asyncio.gather multiple writes → no SQLITE_BUSY errors."""
    import asyncio
    tasks = [create_recipe(title=f"Concurrent {i}") for i in range(5)]
    results = await asyncio.gather(*tasks)
    assert all(r["id"] for r in results)
```

### Research Insights

**Data integrity (from data-integrity-guardian):**
- `test_delete_meal_plan_nullifies_grocery_list` must assert 3 things: (1) list still exists (200), (2) `meal_plan_id is None`, (3) items preserved. Only checking `meal_plan_id` would miss a regression from SET NULL to CASCADE.
- The `_write_lock` in db.py is the primary concurrency control. At least one test should verify two simultaneous writes don't produce SQLITE_BUSY.
- `recipe_categories` junction table has `ON DELETE CASCADE` on both FKs. Orphaned rows would corrupt category counts.

**`tests/test_mcp_server.py`** (~28 tests):

Use `fastmcp.Client` for in-memory testing (not raw function calls). This catches protocol-level issues: tool registration, parameter validation, return value serialization, and the `connect()` migration gap.

```python
# tests/test_mcp_server.py
import pytest
import pytest_asyncio
from fastmcp import Client
from recipe_app.mcp_server import mcp
from recipe_app import mcp_server as mcp_mod

@pytest_asyncio.fixture
async def mcp_client(tmp_path, monkeypatch):
    """MCP client backed by a per-test temp database."""
    db_path = str(tmp_path / "mcp_test.db")
    monkeypatch.setenv("RECIPE_DATABASE_PATH", db_path)
    from recipe_app.config import settings
    monkeypatch.setattr(settings, "database_path", db_path)
    # Reset the module-level _db so it reconnects to the test DB
    mcp_mod._db = None
    async with Client(mcp) as client:
        yield client
    # Cleanup
    if mcp_mod._db is not None:
        await mcp_mod._db.close()
        mcp_mod._db = None

# --- Connection lifecycle ---
async def test_mcp_connection_creates_all_tables(mcp_client):
    """Verify connect() runs migrations — will FAIL if run_migrations() is missing."""
    result = await mcp_client.call_tool("list_meal_plans", {})
    # If connect() doesn't call run_migrations(), this fails with "no such table"
    assert isinstance(result.data, list)

async def test_mcp_list_tools(mcp_client):
    """Verify all 24+ tools are registered."""
    tools = await mcp_client.list_tools()
    tool_names = {t.name for t in tools}
    assert "search_recipes" in tool_names
    assert "create_recipe" in tool_names
    assert "find_recipes_from_pantry" in tool_names
    assert len(tool_names) >= 24

# --- Recipe CRUD ---
async def test_mcp_create_recipe(mcp_client): ...
async def test_mcp_get_recipe(mcp_client): ...
async def test_mcp_get_recipe_not_found(mcp_client):
    result = await mcp_client.call_tool("get_recipe", {"recipe_id": 99999})
    assert result.data is None

async def test_mcp_update_recipe(mcp_client): ...
async def test_mcp_delete_recipe(mcp_client): ...
async def test_mcp_search_recipes(mcp_client): ...

# --- Categories ---
async def test_mcp_list_categories(mcp_client): ...
async def test_mcp_create_category(mcp_client): ...
async def test_mcp_delete_category(mcp_client): ...

# --- Scaling (MCP-only feature) ---
async def test_mcp_scale_recipe(mcp_client): ...
async def test_mcp_scale_recipe_no_ingredients(mcp_client):
    """Recipe with no ingredients returns error dict."""
    r = await mcp_client.call_tool("create_recipe", {"title": "Empty"})
    result = await mcp_client.call_tool("scale_recipe", {"recipe_id": r.data["id"], "multiplier": 2.0})
    assert "error" in str(result.data).lower()

# --- Meal Plans ---
async def test_mcp_create_meal_plan(mcp_client): ...
async def test_mcp_get_meal_plan(mcp_client): ...
async def test_mcp_list_meal_plans(mcp_client): ...
async def test_mcp_update_meal_plan(mcp_client): ...
async def test_mcp_delete_meal_plan(mcp_client): ...
async def test_mcp_add_recipe_to_meal_plan(mcp_client): ...
async def test_mcp_remove_recipe_from_meal_plan(mcp_client): ...

# --- Grocery Lists ---
async def test_mcp_generate_grocery_list(mcp_client): ...
async def test_mcp_get_grocery_list(mcp_client): ...
async def test_mcp_list_grocery_lists(mcp_client): ...
async def test_mcp_delete_grocery_list(mcp_client): ...

# --- Pantry ---
async def test_mcp_add_pantry_item(mcp_client): ...
async def test_mcp_delete_pantry_item(mcp_client): ...
async def test_mcp_list_pantry_items(mcp_client): ...
async def test_mcp_update_pantry_item(mcp_client): ...
async def test_mcp_find_recipes_from_pantry(mcp_client): ...

# --- Cross-tool workflow ---
async def test_mcp_recipe_to_grocery_list_flow(mcp_client):
    """Create recipe → meal plan → add entry → generate grocery list."""
```

### Research Insights

**MCP testing (from framework-docs-researcher + agent-native-reviewer):**
- `fastmcp.Client(server)` connects in-memory with zero network overhead. This is the recommended approach per fastmcp docs.
- Direct function calls miss: tool registration validation, parameter schema generation, return value serialization, and the `get_db()` connection lifecycle.
- **Critical production bug:** `db.connect()` calls `init_schema` but NOT `run_migrations()`. MCP server against a fresh DB will lack meal_plan, grocery_list, and pantry tables. `test_mcp_connection_creates_all_tables` will surface this.
- Must reset `mcp_mod._db = None` before AND after each test to prevent stale event-loop connections.

**Agent parity gaps (from agent-native-reviewer):**
- **Missing MCP tools:** `check_grocery_item` and `add_grocery_item`. An agent can generate a grocery list but cannot check off items or add forgotten items. These should be added before or during testing.
- `create_recipe` MCP tool is missing `source_url`, `image_url`, `nutritional_info` parameters that the API and web UI support.
- MCP error return formats are inconsistent: some return strings, some return dicts with error keys, some return None. Tests should verify and document the actual format for each error case.

---

## Technical Considerations

- **Per-test DB isolation**: Each test gets its own temp SQLite via `tmp_path`. No shared state, no `>=` assertions, no ordering dependencies. Cost: ~18ms/test for lifespan. Acceptable.
- **Factory-as-fixture**: `create_recipe`, `create_meal_plan`, `create_pantry_item` factories return JSON dicts. Max fixture chain depth: 2 (`client -> factory`).
- **Sync vs. async convention**: Pure function tests use sync `def test_*` in classes. HTTP/MCP tests use `async def test_*` with `@pytest.mark.asyncio`. Matches existing patterns in `test_security.py` vs. `test_recipes_crud.py`.
- **MCP testing via fastmcp Client**: In-memory client validates tool registration, parameter schemas, and serialization. Separate fixture resets the `_db` global per test.
- **Form POST content type**: `data=` for `application/x-www-form-urlencoded`, `json=` for API endpoints. Mixing these causes silent 422s.
- **Redirect handling**: httpx defaults to `follow_redirects=False`. Always explicit.
- **NLP import warmup**: Add `session`-scoped fixture to preload `ingredient_parser_nlp` (603ms cold start) so it doesn't appear as a one-test outlier.
- **`asyncio_default_fixture_loop_scope = "function"`**: Suppress pytest-asyncio v1.3.0 deprecation warning.

## Bugs Discovered During Analysis

### Must Fix (block testing or production correctness)
1. **`db.connect()` missing `run_migrations()`** -- MCP server against a fresh DB lacks meal_plan/grocery/pantry tables (`db.py:317-324`)
2. **Open redirect via Referer header** -- `return RedirectResponse(referer, status_code=303)` at `main.py:215` redirects to attacker-controlled URL

### Should Fix (unhandled errors returning 500)
3. **`POST /api/meal-plans/{id}/entries` with nonexistent recipe_id** -- FK IntegrityError returns 500 with internal details (`routers/meal_plans.py:59`)
4. **`POST /api/pantry` with duplicate name** -- UNIQUE COLLATE NOCASE returns 500 (`routers/pantry.py:67`)
5. **`PATCH /api/pantry/{id}` rename to duplicate** -- same UNIQUE violation, 500 (`routers/pantry.py:86`)
6. **`_form_to_recipe_create` type coercion** -- `int(form.get("prep_time_minutes"))` crashes on non-numeric input (`main.py:403`)

### Should Fix (missing agent capabilities)
7. **Missing MCP tools: `check_grocery_item`, `add_grocery_item`** -- agents can't interact with grocery lists after generation (`mcp_server.py`)
8. **MCP `create_recipe` missing `source_url`, `image_url`, `nutritional_info` params** (`mcp_server.py:60-93`)

### Document (known limitations)
9. **`GroceryItemCreate.text` accepts empty string** via API but web UI strips/validates
10. **No date format validation** on `MealPlanEntryCreate.date` and `PantryItemCreate.expiration_date`
11. **`generate_grocery_list` is not atomic** -- partial item INSERT failure orphans the list header (`db.py:764-820`)
12. **`update_pantry_item` cannot clear fields to NULL** due to `exclude_none=True` (`db.py:934`)
13. **Unsanitized text in meal plan names, grocery items, and pantry names** -- no `sanitize_field` on write path
14. **MCP error formats inconsistent** -- string vs dict vs None across tools

## Acceptance Criteria

- [ ] All 72 existing tests continue to pass (with updated fixture)
- [ ] Test infrastructure: per-test DB isolation via `tmp_path`, factory fixtures, FK canary test
- [ ] Meal Plans API: ~20 tests covering all 7 endpoints + FK/cascade + error cases
- [ ] Grocery Lists API: ~18 tests covering all 6 endpoints + aggregation + cascades
- [ ] Pantry API: ~18 tests covering all 5 endpoints + matches + UNIQUE constraint
- [ ] Scaling module: ~18 sync unit tests with parametrize
- [ ] Ingredient parser: ~12 sync unit tests
- [ ] Pantry matcher: ~12 sync unit tests
- [ ] Sanitize module: ~14 sync unit tests (from `recipe_app.sanitize`, NOT scraper)
- [ ] Web UI forms: ~22 async tests for POST handlers + security cases
- [ ] Web UI pages: ~8 tests added to existing `test_web_ui.py`
- [ ] HTMX partials: ~8 async tests verifying fragment vs full-page rendering
- [ ] Data integrity: ~10 tests (FK canary, cascades, cross-feature flows, concurrency)
- [ ] MCP server: ~28 tests via fastmcp Client (lifecycle + CRUD + workflows)
- [ ] Total: ~250+ tests (up from 72)
- [ ] All bugs documented with tests asserting current behavior
- [ ] `uv run pytest` passes cleanly

## Implementation Order

| Phase | Files | Est. Tests | Priority |
|-------|-------|-----------|----------|
| 0a | `conftest.py` overhaul (per-test DB, factories) | — | Prerequisite |
| 0b | `pyproject.toml` additions | — | Prerequisite |
| 0c | `test_data_integrity.py` (FK canary) | 1 | Prerequisite |
| 1a | `test_meal_plans.py` | ~20 | Critical |
| 1b | `test_grocery_lists.py` | ~18 | Critical |
| 1c | `test_pantry.py` | ~18 | Critical |
| 1d | `test_data_integrity.py` (remaining) | ~9 | Critical |
| 2a | `test_scaling.py` | ~18 | High |
| 2b | `test_ingredient_parser.py` | ~12 | High |
| 2c | `test_pantry_matcher.py` | ~12 | High |
| 2d | `test_sanitize_module.py` | ~14 | High |
| 3a | `test_web_ui_forms.py` | ~22 | High |
| 3b | `test_web_ui.py` additions | ~8 | Medium |
| 3c | `test_htmx_partials.py` | ~8 | Medium |
| 4 | `test_mcp_server.py` | ~28 | Medium |

## Sources & References

### Internal References
- Existing test patterns: `tests/conftest.py`, `tests/test_recipes_crud.py`, `tests/test_security.py`
- Untested routers: `src/recipe_app/routers/meal_plans.py`, `src/recipe_app/routers/pantry.py`
- Untested modules: `src/recipe_app/scaling.py`, `src/recipe_app/ingredient_parser.py`, `src/recipe_app/pantry_matcher.py`, `src/recipe_app/sanitize.py`
- MCP server: `src/recipe_app/mcp_server.py`
- Web UI handlers: `src/recipe_app/main.py` (lines 159-448)
- DB functions: `src/recipe_app/db.py` (lines 662-977)
- Schema: `src/recipe_app/sql/schema.sql`

### External References
- [pytest-asyncio fixtures reference](https://pytest-asyncio.readthedocs.io/en/stable/reference/fixtures/)
- [httpx ASGITransport documentation](https://github.com/encode/httpx/blob/master/docs/advanced/transports.md)
- [FastAPI official testing guide](https://fastapi.tiangolo.com/tutorial/testing/)
- [FastMCP testing patterns](https://github.com/prefecthq/fastmcp/blob/main/docs/patterns/testing.mdx)
- [jinja2-fragments Starlette integration](https://github.com/sponsfreixes/jinja2-fragments)
