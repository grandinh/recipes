---
title: "feat: Agent Integration — Grocery Completion + Photo Upload"
type: feat
status: completed
date: 2026-03-27
deepened: 2026-03-27
origin: docs/brainstorms/2026-03-26-003-feat-agent-integration-completeness-brainstorm.md
---

# feat: Agent Integration — Grocery Completion + Photo Upload

## Enhancement Summary

**Deepened on:** 2026-03-27
**Sections enhanced:** All
**Agents used:** kieran-python-reviewer, performance-oracle, security-sentinel, architecture-strategist, agent-native-reviewer, code-simplicity-reviewer, pattern-recognition-specialist, data-integrity-guardian, data-migration-expert, julik-frontend-races-reviewer, agent-native-architecture-skill, learnings-researcher (x3)

### Key Changes from Deepening
1. **CRITICAL: `sanitize_field(name) or name` is the exact bypass documented in learnings** — empty string is falsy, falls through to unsanitized original. Replace with `sanitize_field(name)` everywhere.
2. **CUT: `bulk_check_grocery_items`** — premature optimization. Agent can call `check_grocery_item` in a loop for <100 items.
3. **CUT: OCR / Anthropic API** — no paid API calls for a personal app. OCR can be revisited later with a local/free solution.
4. **SIMPLIFIED: `move_checked_to_pantry`** — Ship name-only with `INSERT OR IGNORE`, no quantity merging. Eliminates re-parsing, float-vs-Fraction debate, unit comparison, silent no-op bug.
5. **RENAMED: `clear_checked_items` → `clear_checked_grocery_items`** — matches existing naming convention.
6. **ADDED: `upload_recipe_photo` MCP tool** — closes the last major agent parity gap. No API calls, just saves image to disk.
7. **ADDED: `BEGIN IMMEDIATE` / rollback** for `move_checked_to_pantry` — matches `_save_grocery_list` pattern.
8. **ADDED: HTMX race protection** — `hx-disabled-elt="this"` on all mutating buttons, all target `#items-list` with `innerHTML` swap.

### New Considerations Discovered
- `delete_grocery_item` should return `bool` (not dict) to match all existing delete functions
- Use `DELETE ... RETURNING` (SQLite 3.35+) to eliminate SELECT-then-DELETE
- Use `INSERT ... ON CONFLICT DO NOTHING` (SQLite UPSERT) to eliminate TOCTOU on pantry UNIQUE constraint
- `_updateGroceryRemaining()` must be called unconditionally in `htmx:afterSettle` after item list changes

## Overview

Round out the MCP tool surface so agents (Chef, OpenClaw) can complete full end-to-end workflows without falling back to the web UI. Three things: (1) fill remaining grocery item management gaps, (2) fix the pantry sanitization bug, and (3) add photo upload for agent parity.

Webhooks/events are **deferred** — polling is adequate for Chef's weekly cron and OpenClaw's request/response model.

OCR recipe scanning is **deferred** — requires paid Anthropic API calls. Can be revisited with a local/free solution.

**Important correction from brainstorm:** The brainstorm states agents "cannot check/uncheck items or add ad-hoc items." This is outdated — `check_grocery_item` and `add_grocery_item` MCP tools already exist.

## Problem Statement

**Grocery gaps:** Agents can generate, view, check, and add items to grocery lists. But they cannot delete a wrong item, clear checked items after shopping, or move purchased items to the pantry. The web UI also lacks delete-item and clear-checked — these are missing everywhere.

**Photo upload gap:** The web UI supports uploading photos to recipes via multipart form. No MCP tool exists for this — agents cannot attach photos to recipes.

**Sanitization bug:** `add_pantry_item` and `update_pantry_item` in `db.py` do not sanitize inputs. Exploitable today via MCP: `add_pantry_item(name="<script>alert(1)</script>")`.

## Proposed Solution

### Grocery MCP Tool Completion

Add three operations across all three layers (DB → REST API → MCP tool), plus web UI:

| Operation | DB function | REST endpoint | MCP tool | Web UI |
|---|---|---|---|---|
| Delete single item | `delete_grocery_item` | `DELETE /api/grocery-lists/items/{id}` | `delete_grocery_item` | Button on list detail |
| Clear checked items | `clear_checked_grocery_items` | `POST /api/grocery-lists/{id}/clear-checked` | `clear_checked_grocery_items` | Button on list detail |
| Move checked to pantry | `move_checked_to_pantry` | `POST /api/grocery-lists/{id}/move-to-pantry` | `move_checked_to_pantry` | Button on list detail |

**Also fix:** Add `sanitize_field()` calls to `add_pantry_item` and `update_pantry_item` in `db.py` (both `name` and `category` fields).

### Photo Upload MCP Tool

- MCP tool: `upload_recipe_photo(recipe_id, image_base64, media_type)` — attaches a photo to an existing recipe
- Uses existing `save_photo` from `photos.py` — no new dependencies, no API calls

## Technical Approach

### 1a. `delete_grocery_item(db, item_id) -> bool`

```python
# src/recipe_app/db.py
async def delete_grocery_item(db: aiosqlite.Connection, item_id: int) -> bool:
    """Delete a single item from a grocery list. Returns True if deleted."""
    async with _write_lock:
        cursor = await db.execute(
            "DELETE FROM grocery_list_items WHERE id = ? RETURNING id",
            (item_id,),
        )
        row = await cursor.fetchone()
        await db.commit()
        return row is not None
```

- Returns `bool` matching all existing delete functions
- Uses `DELETE ... RETURNING` (SQLite 3.35+) to eliminate SELECT-then-DELETE
- MCP tool returns string: `"Item {item_id} deleted"` / `"Item {item_id} not found"`

### 1b. `clear_checked_grocery_items(db, list_id) -> dict | None`

```python
# src/recipe_app/db.py
async def clear_checked_grocery_items(db: aiosqlite.Connection, list_id: int) -> dict | None:
    """Delete all checked items from a grocery list. Returns None if list not found."""
    async with _write_lock:
        cursor = await db.execute(
            "SELECT id FROM grocery_lists WHERE id = ?", (list_id,),
        )
        if not await cursor.fetchone():
            return None
        cursor = await db.execute(
            "DELETE FROM grocery_list_items WHERE grocery_list_id = ? AND is_checked = 1",
            (list_id,),
        )
        await db.commit()
        return {"list_id": list_id, "cleared_count": cursor.rowcount}
```

- Returns `None` for nonexistent list (distinguishes "not found" from "nothing checked")
- Web UI button uses `hx-confirm="Remove all checked items?"`

### 1c. `move_checked_to_pantry(db, list_id) -> dict`

**Simplified design (v1):** Name-only insert with `INSERT OR IGNORE`. No quantity merging, no re-parsing. The user can update quantities in the pantry view if they care.

```python
# src/recipe_app/db.py
async def move_checked_to_pantry(db: aiosqlite.Connection, list_id: int) -> dict:
    """Move checked grocery items to pantry (name-only). Returns summary."""
    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")

            cursor = await db.execute(
                "SELECT id, text, normalized_name, aisle FROM grocery_list_items "
                "WHERE grocery_list_id = ? AND is_checked = 1",
                (list_id,),
            )
            checked_items = await cursor.fetchall()
            if not checked_items:
                await db.commit()
                return {"moved": [], "already_in_pantry": [], "warnings": []}

            moved, already_in_pantry, warnings = [], [], []

            for row in checked_items:
                item_id = row["id"]
                name = row["normalized_name"] or row["text"]
                aisle = row["aisle"]

                # Sanitize — never use `sanitize_field(x) or x` (empty string bypass)
                sanitized = sanitize_field(name)
                if not sanitized:
                    warnings.append(f"Skipped item with unsanitizable name: {row['text']!r}")
                    continue
                name = sanitized
                category = sanitize_field(aisle) if aisle else None

                # UPSERT: insert if new, no-op if exists (eliminates TOCTOU race)
                cursor2 = await db.execute(
                    """INSERT INTO pantry_items (name, category)
                       VALUES (?, ?)
                       ON CONFLICT(name) DO NOTHING
                       RETURNING id""",
                    (name, category),
                )
                inserted = await cursor2.fetchone()

                if inserted:
                    moved.append(name)
                else:
                    already_in_pantry.append(name)

                # Remove from grocery list
                await db.execute(
                    "DELETE FROM grocery_list_items WHERE id = ?", (item_id,),
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return {"moved": moved, "already_in_pantry": already_in_pantry, "warnings": warnings}
```

**Key design decisions (14 agents converged on simplification):**
- Uses `normalized_name` column directly (already went through normalization pipeline) — no re-parsing
- Uses `INSERT ... ON CONFLICT DO NOTHING` (SQLite UPSERT) — eliminates TOCTOU race
- Uses `BEGIN IMMEDIATE` + `try/except/rollback` matching `_save_grocery_list` pattern
- Accesses rows via `row["name"]` not `row[0]` (codebase uses dict row factory)
- Sanitizes both `name` AND `category` — never uses `sanitize_field(x) or x`
- Continue-and-report on per-item failures, matching Paprika import's `ImportResult` pattern

**Future enhancement (only if needed):** Add quantity merging by storing `quantity REAL` and `unit TEXT` columns in `grocery_list_items` at generation time (the aggregation pipeline already has these values but discards them).

### 1d. Pantry sanitization fix

```python
# src/recipe_app/db.py — add to add_pantry_item and update_pantry_item
# NEVER use `sanitize_field(name) or name` — empty string is falsy, bypasses sanitization
name = sanitize_field(name)
if category:
    category = sanitize_field(category)
```

### 1e. MCP tool: `upload_recipe_photo`

```python
# src/recipe_app/mcp_server.py

@mcp.tool
async def upload_recipe_photo(
    recipe_id: int,
    image_base64: str,
    media_type: str = "image/jpeg",
) -> dict:
    """Upload a photo for an existing recipe.

    recipe_id: ID of the recipe to attach the photo to.
    image_base64: Base64-encoded image data (JPEG, PNG, WebP, or GIF).
    media_type: MIME type of the image. Default: image/jpeg.
    """
    import base64 as b64
    from recipe_app.photos import save_photo
    from recipe_app.models import RecipeUpdate

    db = await get_db()
    recipe = await db_module.get_recipe(db, recipe_id)
    if not recipe:
        return {"error": f"Recipe {recipe_id} not found"}

    try:
        image_data = b64.b64decode(image_base64)
    except Exception:
        return {"error": "Invalid base64 image data"}

    filename = await save_photo(image_data, recipe_id)
    await db_module.update_recipe(db, recipe_id, RecipeUpdate(photo_path=filename))
    return {"recipe_id": recipe_id, "photo_path": filename}
```

- No API calls, no new dependencies — uses existing `save_photo` from `photos.py`
- Closes the last major agent parity gap

## System-Wide Impact

- **Interaction graph**: `move_checked_to_pantry` crosses two domains (grocery → pantry). Uses `INSERT...ON CONFLICT DO NOTHING` for atomic pantry upsert. Runs under `BEGIN IMMEDIATE` with rollback for transaction safety
- **State lifecycle risks**: `move_checked_to_pantry` uses continue-and-report for per-item failures. Transaction wraps the whole operation — either all items commit or none do
- **API surface parity**: After this sprint, all practical web UI actions have MCP equivalents (Paprika import intentionally excluded — one-time migration)

### HTMX Frontend Patterns

All new grocery list buttons must follow these rules to prevent race conditions:

| Button | `hx-post` | `hx-target` | `hx-swap` | `hx-disabled-elt` | `hx-confirm` |
|--------|-----------|-------------|-----------|-------------------|--------------|
| Delete Item | `/grocery-lists/{id}/delete-item/{item_id}` | `#items-list` | `innerHTML` | `this` | `"Delete this item?"` |
| Clear Checked | `/grocery-lists/{id}/clear-checked` | `#items-list` | `innerHTML` | `this` | `"Remove all checked items?"` |
| Move to Pantry | `/grocery-lists/{id}/move-to-pantry` | `#items-list` | `innerHTML` | `this` | (no — shows inline warnings) |

**Critical:**
- **`hx-disabled-elt="this"`** on every mutating button — prevents double-click
- **All buttons target `#items-list` with `innerHTML` swap** — stays inside `hx-sync="this:replace"` queue
- **Inline warnings in template response** for move-to-pantry — no JS toast needed
- **Server routes return `block_name="items_list"` partial** — re-fetch full list after mutation
- **Call `_updateGroceryRemaining()` unconditionally** in `htmx:afterSettle` when `#items-list` changes

### Agent Context Injection

Update system prompts for agent consumers:

**Chef** (weekly meal planning cron):
```
After generating a grocery list, you can help the user manage it:
- check_grocery_item: mark individual items as purchased
- delete_grocery_item: remove wrong items from the list
- clear_checked_grocery_items: clean up after shopping
- move_checked_to_pantry: restock pantry from purchased items
Post-shopping flow: check purchased items -> move to pantry -> clear checked.
```

## Acceptance Criteria

- [x] `delete_grocery_item` — DB function (returns `bool`), REST endpoint, MCP tool (returns string), web UI button with `hx-confirm`
- [x] `clear_checked_grocery_items` — DB function (returns `dict | None`), REST endpoint, MCP tool, web UI button with `hx-confirm`
- [x] `move_checked_to_pantry` — DB function, REST endpoint, MCP tool, web UI button
- [x] `move_checked_to_pantry` uses `INSERT ... ON CONFLICT DO NOTHING` (no TOCTOU race)
- [x] `move_checked_to_pantry` uses `BEGIN IMMEDIATE` with `try/except/rollback`
- [x] `move_checked_to_pantry` uses `normalized_name` column directly (no re-parsing)
- [x] `add_pantry_item` and `update_pantry_item` sanitize `name` AND `category` — never `sanitize_field(x) or x`
- [x] `upload_recipe_photo` MCP tool — attaches photo to recipe via `save_photo`
- [x] All new web UI buttons use `hx-disabled-elt="this"` and target `#items-list`
- [x] MCP test count assertion updated
- [x] Tests for all new DB functions, REST endpoints, and MCP tools

## Testing Strategy

- **MCP tests:** Use `fastmcp.Client` with `_parse_result()` helper. Assert on dict keys, never string matching
- **New fixture:** Add `create_grocery_list` factory to `conftest.py`
- **Cross-domain test:** Add grocery → pantry lifecycle workflow test for both REST and MCP
- **Error responses:** Assert `"Traceback" not in resp.text` on all error paths
- **Sanitization test:** Verify HTML in pantry names is stripped via both API and `move_checked_to_pantry`

## Dependencies & Risks

| Dependency | Risk | Mitigation |
|---|---|---|
| Pantry UNIQUE constraint | Name collisions on move | `INSERT ... ON CONFLICT DO NOTHING` (atomic, no TOCTOU) |
| `photos.py` for upload | Already tested, no new deps | Reuse existing `save_photo` |

## Implementation Order

1. **Pantry sanitization fix** — pre-existing bug, exploitable today, two lines
2. **`delete_grocery_item`** — simplest new operation, all three layers + web UI
3. **`clear_checked_grocery_items`** — simple bulk delete with existence check
4. **`move_checked_to_pantry`** — cross-domain operation, depends on pantry sanitization
5. **`upload_recipe_photo` MCP tool** — closes photo parity gap

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-26-003-feat-agent-integration-completeness-brainstorm.md](docs/brainstorms/2026-03-26-003-feat-agent-integration-completeness-brainstorm.md)

### Internal References

- MCP server: `src/recipe_app/mcp_server.py`
- DB layer: `src/recipe_app/db.py`
- Grocery schema: `src/recipe_app/sql/schema.sql:81-103`
- Pantry schema: `src/recipe_app/sql/schema.sql:106-115`
- Photo processing: `src/recipe_app/photos.py`
- Sanitization: `src/recipe_app/sanitize.py`
- MCP tests: `tests/test_mcp_server.py`
- Normalizer: `src/recipe_app/normalizer.py`

### Institutional Learnings Applied

- **`sanitize(x) or x` bypass — NEVER USE** — empty string is falsy (from calendar-view solution)
- `BEGIN IMMEDIATE` + `try/except/rollback` for multi-statement writes (from `_save_grocery_list` pattern)
- Conservative failure mode: too many pantry items beats wrong quantities (from aggregation solution)
- MCP testing via `fastmcp.Client`, `_parse_result()` helper (from test-coverage solution)
- N+1 query smell: per-item INSERT/DELETE acceptable for <100 items (from aggregation solution)

### External References

- SQLite UPSERT: `INSERT ... ON CONFLICT DO UPDATE/NOTHING` (available since 3.24.0)
- SQLite RETURNING: `DELETE/INSERT ... RETURNING` (available since 3.35.0)
