---
title: "Grocery Aggregation Pipeline + Code Review Patterns"
category: implementation-patterns
date: 2026-03-27
tags:
  - grocery-aggregation
  - fraction-arithmetic
  - normalization
  - aisle-mapping
  - code-review
  - dead-code
  - schema-versioning
  - n-plus-one
  - module-extraction
  - asyncio
modules:
  - recipe_app.aggregation
  - recipe_app.normalizer
  - recipe_app.aisle_map
  - recipe_app.db
  - recipe_app.ingredient_parser
  - recipe_app.scaling
pr: "https://github.com/grandinh/recipes/pull/4"
---

# Grocery Aggregation Pipeline + Code Review Patterns

## Problem

The grocery list generator had multiple issues:

1. **String concatenation instead of arithmetic**: Duplicate ingredients produced `"2 cups flour + 1 cup flour"` instead of `"3 cups flour"`
2. **Recipe multiplicity bug**: `WHERE id IN (...)` deduplicated recipe IDs, so the same recipe on Monday and Wednesday counted as single quantities
3. **No normalization**: "Onions (diced)" and "onion" were separate line items
4. **No aisle grouping**: Items listed in arbitrary order instead of by store section
5. **Missing sanitization**: `add_grocery_item()` wrote raw user input to DB

After building the fix, code review found 7 additional issues in the implementation.

## Solution: Aggregation Pipeline

### Architecture

Three new pure-function modules (no DB, no async) following the existing `scaling.py` pattern:

```
ingredient text
    -> parse_ingredient(preserve_fractions=True)   # Fraction, not float
    -> normalize_ingredient_name()                  # strip parens, hyphens, singularize
    -> assign_aisle()                               # 13 categories, longest-match-first
    -> bucket by (normalized_name, unit)            # Fraction summing
    -> format_quantity()                            # "1 1/2" display
```

### Key Design Decisions

**Fraction arithmetic, not float**: `Fraction(1,3) + Fraction(2,3) == Fraction(1)` exactly. Float arithmetic gives `0.33333 + 0.66666 = 0.99999`. For cooking quantities, exact fractions matter.

**`preserve_fractions=True` parameter**: Added to existing `parse_ingredient()` rather than creating a parallel function. Default `False` preserves backward compatibility for the scaling/JSON path.

**Same-unit-only merging**: "1 cup flour" + "200g flour" = two items. No unit conversion — wrong aisle assignment is acceptable (fails to "Other"), wrong quantities are not.

**Unquantified items don't merge with quantified**: "salt to taste" stays separate from "1 tsp salt".

**`asyncio.to_thread()`**: NLP parsing is CPU-bound (~0.5ms/ingredient). For 300 ingredients, that's 150ms blocking the event loop. Offload via `asyncio.to_thread()` matching the `pantry_matcher.py` pattern.

**`BEGIN IMMEDIATE` + rollback**: Multi-row INSERT wrapped in explicit transaction matching the `create_recipe()` pattern.

### normalizer.py (~50 lines)

Three strategies that fail to "too many items" (status quo), never "wrong quantities":

1. **Strip parentheticals**: `re.sub(r'\([^)]*\)', '', name)` — "flour (all-purpose)" -> "flour"
2. **Normalize hyphens**: `name.replace('-', ' ')` — "extra-virgin" -> "extra virgin"
3. **Singularize last word**: Rule-based with 14-word exception set (asparagus, couscous, hummus, etc.)

Returns frozen `NormalizedResult` dataclass with `.name` and `.original_name`.

### aisle_map.py (~95 lines)

- 13 categories, ~170 keywords, module-level dict constant
- Keywords sorted by descending length at import time
- Substring matching: `if keyword in lower_name`
- "coconut milk" matches Canned (len 12) before "milk" matches Dairy (len 4)
- Falls back to `("Other", 99)`

Known limitation: "rice" matches "licorice" via substring. Acceptable because wrong aisle != wrong quantity.

### Multiplicity Fix

Old (broken): `WHERE id IN (1, 1)` -> SQLite returns one row.

New (correct): JOIN on `meal_plan_entries` preserving every row:
```sql
SELECT r.id, r.ingredients, r.base_servings, e.servings_override
  FROM meal_plan_entries e
  JOIN recipes r ON r.id = e.recipe_id
 WHERE e.meal_plan_id = ?
```

## Code Review Findings (Fixed)

### P1: Dead DOM Loop in `_renderTimerPanel()`

The function built timer entry DOM nodes, appended them to the list, then immediately cleared the list and rebuilt identical nodes. The first loop was dead code executing every 1-second tick.

**Fix**: Delete the first loop. Keep only the clear-and-rebuild block.

**Prevention**: When writing render functions called on intervals, search for duplicate loops before merging. If you see two loops over the same data in sequence, the first is likely dead.

### P1: Schema Version Mismatch

`schema.sql` set `PRAGMA user_version = 2` but included v3 columns. Fresh databases got v3 schema at version 2, triggering an unnecessary migration + backup on first connect.

**Fix**: Set `PRAGMA user_version = 3` in schema.sql to match the latest migration.

**Prevention**: When adding columns to schema.sql for fresh installs, always bump the `PRAGMA user_version` to match the migration that introduces them.

### P1: Duplicate HTML `class` Attribute

Replacing `onchange="this.form.submit()"` produced `class="input" ... class="auto-submit-select"`. Browsers silently ignore the second `class` attribute.

**Fix**: Merge into `class="input auto-submit-select"`.

**Prevention**: When replacing inline handlers with class-based delegation, merge the new class into the existing `class` attribute, don't add a second one.

### P2: N+1 Query

`generate_grocery_list()` with `recipe_ids` did a per-recipe `SELECT` in a loop.

**Fix**: Single `WHERE id IN (...)` query with placeholder list.

**Prevention**: Any loop containing `db.execute()` is a code smell. Batch with `IN (...)` or JOIN.

### P2: Duplicated DB Write Logic

`generate_grocery_list()` and `add_recipe_to_grocery_list()` had near-identical 25-line transaction blocks.

**Fix**: Extracted `_save_grocery_list(db, name, aggregated, meal_plan_id=None)` shared helper.

**Prevention**: If you copy-paste a write block, extract a helper immediately. Don't wait for review.

### P2: Pure Function in Wrong Layer

`_aggregate_ingredients()` had zero DB dependencies but lived in `db.py`.

**Fix**: Extracted to `aggregation.py` with top-level imports.

**Prevention**: If a function in `db.py` doesn't call `db.execute()` or touch `aiosqlite`, it belongs elsewhere. Test smell: importing from `db.py` without using a database fixture.

### P2: Unused Code

- `_TIMER_PATTERNS` module-level var: declared but never referenced (patterns were inlined as local vars)
- `GroceryItemResponse` Pydantic model: defined but never used as a type annotation

**Prevention**: Run dead code detection before merging. Search for the symbol name — if only the definition appears, delete it.

## Cross-References

- [Calendar View & Paprika Import Patterns](calendar-view-paprika-import-fastapi-htmx.md) — HTMX event delegation, `hx-sync`, sanitize_field bypass bug
- [Test Coverage Patterns](../test-failures/comprehensive-test-coverage-fastapi-recipe-app.md) — Factory fixtures, per-test DB isolation, MCP testing
- [Brainstorm](../../brainstorms/2026-03-26-001-feat-grocery-cooking-ux-brainstorm.md) — Design decisions for normalization strategies, aisle categories, timer patterns
- [Plan](../../plans/2026-03-27-001-feat-grocery-aggregation-cooking-timers-step-nav-plan.md) — Full implementation spec
- [PR #4](https://github.com/grandinh/recipes/pull/4)

## Key Takeaways

1. **Fraction arithmetic for quantities** — never use float for cooking math
2. **`preserve_fractions` flag** — parameterize existing functions instead of duplicating them
3. **Longest-match-first** — sort keywords by descending length for substring matching
4. **Pure functions get their own modules** — `db.py` is for DB operations only
5. **Schema version must match schema content** — bump `user_version` when adding columns
6. **Every loop with `db.execute()` is suspect** — batch with `IN (...)` or JOIN
7. **Conservative failure mode** — "too many items on list" beats "wrong quantities" every time
