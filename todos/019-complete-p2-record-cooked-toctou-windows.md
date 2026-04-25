---
status: complete
priority: p2
issue_id: "019"
tags: [code-review, concurrency, last-cooked-history]
dependencies: []
---

# `record_recipe_cooked` has two TOCTOU windows around the write transaction

## Problem Statement
Two related gaps in `db.record_recipe_cooked` (db.py:1037-1101):

1. **Pre-checks run before BEGIN IMMEDIATE.** Recipe-existence check (line 1066) and calendar-entry check (line 1071) execute in autocommit, then `BEGIN IMMEDIATE` opens the txn at line 1080. The `_write_lock` is process-local; the chef MCP runs in a separate process with its own connection. Sequence: web pre-check sees recipe → chef `DELETE recipes/42` commits → web `INSERT recipe_cook_events` raises `IntegrityError` (FK violation). User sees 500 instead of clean 404.

2. **Post-commit `get_recipe` runs OUTSIDE the lock.** After `await db.commit()` and the `async with _write_lock` block exits, `recipe = await get_recipe(db, recipe_id)` (line 1097) re-fetches without serialization. A concurrent edit can land between the cook event commit and the response, so the returned `recipe` may not reflect the freshness fields just written.

The plan explicitly stated: *"Return the updated recipe dict (re-fetched after the update so the caller sees consistent state)."* The current shape doesn't honor that.

## Findings
- **kieran-python-reviewer P2 #7**: pre-check inside lock but outside transaction — TOCTOU window
- **performance-oracle P1.1**: pre-checks before BEGIN IMMEDIATE → extra lock acquire round-trip
- **security-sentinel P3**: TOCTOU on FK pre-checks
- **architecture-strategist P1-2 + P2-1**: pre-checks outside txn, get_recipe outside lock
- **pattern-recognition-specialist #4**: inconsistent with `create_recipe` which puts checks inside BEGIN IMMEDIATE
- **codex (D3)** Medium: response assembly outside the write transaction

## Recommended Fix
Move both pre-checks AND the final `get_recipe` inside the locked transaction. Or rely on FK violation → catch `sqlite3.IntegrityError` and translate to `ValueError("Recipe not found")` (drops the recipe-existence pre-check entirely).

## Acceptance Criteria
- [ ] Pre-checks happen after `BEGIN IMMEDIATE`, or are replaced by FK-violation translation
- [ ] `get_recipe` (or equivalent) called inside the locked transaction so returned recipe reflects post-commit state
- [ ] No new tests required (race window is small) but optional regression test: INSERT cook event with deleted recipe_id should 404 cleanly
