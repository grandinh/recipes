---
title: "Agent parity: MCP grocery management and photo upload with code review fixes"
category: implementation-patterns
date: 2026-03-27
tags:
  - mcp
  - code-review
  - grocery-list
  - photo-upload
  - input-sanitization
  - error-handling
  - agent-parity
  - fastapi
  - aiosqlite
  - fastmcp
modules:
  - src/recipe_app/db.py
  - src/recipe_app/mcp_server.py
  - src/recipe_app/routers/meal_plans.py
  - src/recipe_app/main.py
severity: medium
resolved: true
---

# Agent Parity: MCP Grocery Management + Photo Upload

## Problem

The recipe app needed MCP tool parity with the web UI for grocery list management. Agents could generate and view grocery lists but couldn't delete items, clear checked items, move purchased items to pantry, or upload recipe photos. Additionally, `add_pantry_item` and `update_pantry_item` had no input sanitization (XSS via MCP).

## Root Cause Analysis

The issues found during 8-agent parallel code review fell into three categories:

1. **Silent failure on invalid input:** Cross-domain DB functions (grocery -> pantry) lacked existence checks present in same-domain operations. Result: successful-looking empty response instead of clear "not found" error.

2. **Entry-point parity gaps:** Size guards, cleanup logic, and validation present in the web UI were absent in MCP tools. Classic "second entry point" oversight.

3. **Sanitization inconsistency:** Some fields sanitized, others not. The `sanitize_field(x) or x` anti-pattern (documented in prior solutions) was avoided, but `unit` field was missed entirely.

## Solution

### 1. Cross-domain DB functions need explicit existence checks

When a DB function operates on items belonging to a parent entity in another domain, verify the parent exists first. Return `None` for not-found so callers can map to 404/error.

```python
# db.py -- move_checked_to_pantry
async def move_checked_to_pantry(db, list_id: int) -> dict | None:
    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id FROM grocery_lists WHERE id = ?", (list_id,),
            )
            if not await cursor.fetchone():
                await db.commit()
                return None  # Caller maps to 404
            # ... proceed with moving checked items
```

Both REST and MCP layers must handle `None`:

```python
# REST endpoint
if result is None:
    raise HTTPException(status_code=404, detail="Grocery list not found")

# MCP tool
if result is None:
    return {"error": f"Grocery list {list_id} not found"}
```

### 2. MCP tools must enforce same limits as web UI

The web UI checked `len(raw) > settings.max_photo_size`. The MCP tool had no size guard.

```python
# mcp_server.py -- upload_recipe_photo
MAX_BASE64_SIZE = 14 * 1024 * 1024  # ~10 MB decoded
if len(image_base64) > MAX_BASE64_SIZE:
    return {"error": "Image too large (max 10 MB)"}
```

### 3. MCP tools must replicate web UI side effects

The web UI deletes old photo files on re-upload. The MCP tool initially didn't.

```python
old_photo = recipe.get("photo_path")
await db_module.update_recipe(db, recipe_id, RecipeUpdate(photo_path=filename))
if old_photo:
    await delete_photo(old_photo)
```

### 4. Remove dead parameters that mislead agent callers

`media_type` was accepted but `save_photo()` auto-detects format via Pillow. Agents took the parameter literally and might craft incorrect values or blame it for failures.

### 5. Narrow exception handling

```python
# Before (masks MemoryError, etc.):
except Exception:
    return {"error": "Invalid base64 image data"}

# After:
import binascii
except (binascii.Error, ValueError):
    return {"error": "Invalid base64 image data"}
```

### 6. Sanitize ALL string fields in write functions

When adding sanitization, audit every string parameter -- not just the obvious ones.

```python
name = sanitize_field(name)
if category:
    category = sanitize_field(category)
if unit:        # Was missing!
    unit = sanitize_field(unit)
```

### 7. Test assertions must be falsifiable

```python
# Before (always true -- len() >= 0 is a tautology):
assert len(result["already_in_pantry"]) >= 1 or len(result["moved"]) >= 0

# After:
assert len(result["already_in_pantry"]) >= 1
```

## Key Patterns

| Pattern | Rule |
|---------|------|
| **Entry-point parity** | Every entry point (web UI, REST, MCP) must enforce the same validation, limits, cleanup, and error handling |
| **`sanitize_field(x) or x` is a bypass** | Empty string is falsy. Always use direct assignment: `x = sanitize_field(x)` |
| **Cross-domain existence checks** | A SELECT returning zero rows from child table is ambiguous. Add explicit parent existence check inside the transaction |
| **Falsifiable assertions** | Any assertion with `or` where one branch is a tautology can never fail. Verify each branch can be false |
| **Narrow exceptions** | `except Exception` masks bugs. Catch only expected error types (`binascii.Error`, `ValueError`) |
| **Dead parameters mislead agents** | LLM agents take docstrings literally. Remove unused parameters rather than leaving them "for later" |

## Prevention Checklist

When adding a feature exposed through multiple entry points:

- [ ] All entry points enforce the same input validation
- [ ] All entry points enforce the same size/length guards
- [ ] All string fields in write paths are sanitized (audit ALL fields)
- [ ] Cleanup and side-effect logic is identical across paths
- [ ] Error handling returns appropriate status codes/messages per path
- [ ] Parent entity existence is verified for cross-domain operations
- [ ] Tests cover not-found cases for every new endpoint
- [ ] Test assertions are falsifiable (no tautological `or` clauses)
- [ ] Exception handling catches specific types, not bare `Exception`
- [ ] No unused parameters in function signatures

## Testing Lessons

- **Parity tests**: Write parallel tests exercising the same operation through web UI and MCP, asserting identical DB outcomes
- **Sanitization tests**: Pass `<script>alert(1)</script>` in EVERY string field, not just `name`
- **Assertion review**: Before merging, scan every `assert` for OR clauses with always-true branches

## Related Documentation

### Solution Docs
- [Grocery aggregation pipeline and code review fixes](grocery-aggregation-pipeline-and-code-review-fixes.md) -- N+1 queries, `BEGIN IMMEDIATE` pattern, module extraction
- [Calendar view and Paprika import](calendar-view-paprika-import-fastapi-htmx.md) -- `sanitize_field(x) or x` bypass first documented, HTMX race conditions, `hx-sync` patterns
- [Comprehensive test coverage](../test-failures/comprehensive-test-coverage-fastapi-recipe-app.md) -- MCP testing via `fastmcp.Client`, `_parse_result()` helper, sanitization gap discovery

### Plans
- [Agent integration plan](../../plans/2026-03-27-002-feat-agent-integration-grocery-ocr-parity-plan.md) -- Source plan for this work
- [Agent integration brainstorm](../../brainstorms/2026-03-26-003-feat-agent-integration-completeness-brainstorm.md) -- Original exploration of MCP tool gaps

### Recurring Themes
- **Sanitization bypass** appears in 3 separate docs -- always use direct assignment, never `or` fallback
- **MCP tool gaps** tracked across 4 plans -- each sprint identified different missing tools
- **`BEGIN IMMEDIATE` + rollback** is the established transaction pattern (5 usages in `db.py`)
