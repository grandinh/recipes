---
title: "SQLite Model Restructure: Multi-Plan/Multi-List → Global Calendar + Single Grocery List"
category: implementation-patterns
date: 2026-03-27
tags: [sqlite, migration, aiosqlite, fastapi, htmx, mcp, schema-restructure, calendar, grocery]
module: db, main, mcp_server, routers
symptom: "Meal planning workflow requires creating named plans before adding entries; grocery lists are ephemeral per-generation"
root_cause: "Data model copied from a generic meal planner, not from Paprika 3's single-calendar, single-persistent-list workflow"
---

# SQLite Model Restructure: Global Calendar + Single Grocery List

## Problem

The app's meal planning and grocery workflow used a parent-child model (named `meal_plans` → `meal_plan_entries`, multiple `grocery_lists` → `grocery_list_items`) that didn't match Paprika 3's mental model. Users had to create named plans and got a new grocery list per generation. Paprika uses a single global calendar and one persistent shopping list.

## Root Cause

The original schema was designed generically rather than matching the target UX. The `meal_plans` parent table and `grocery_lists.meal_plan_id` FK created unnecessary indirection that complicated every layer (DB, web, API, MCP).

## Solution

### Migration Strategy (v3 → v4)

SQLite cannot `ALTER TABLE DROP COLUMN` or rename columns with FKs. The safe pattern:

```sql
PRAGMA foreign_keys = OFF;

-- 1. Create new table with desired schema
CREATE TABLE calendar_entries (...);

-- 2. Copy data (transform as needed)
INSERT INTO calendar_entries (...) SELECT ... FROM meal_plan_entries;

-- 3. Recreate dependent tables without unwanted FK columns
CREATE TABLE grocery_lists_new (...);  -- without meal_plan_id
INSERT INTO grocery_lists_new ... SELECT ... FROM grocery_lists WHERE id = (SELECT MIN(id) ...);
DROP TABLE grocery_lists;
ALTER TABLE grocery_lists_new RENAME TO grocery_lists;

-- 4. Drop old tables (child first)
DROP TABLE IF EXISTS meal_plan_entries;
DROP TABLE IF EXISTS meal_plans;

-- 5. Verify integrity before re-enabling FKs
PRAGMA foreign_key_check;  -- MUST fetch results and check for violations
PRAGMA foreign_keys = ON;
PRAGMA user_version = 4;
```

### Critical Migration Bugs Found (and fixed)

1. **`schema.sql` resets `user_version` on every restart.** `init_schema()` runs `schema.sql` via `executescript` before `run_migrations()`. If `schema.sql` still has the old tables with `IF NOT EXISTS` and ends with `PRAGMA user_version = 3`, it recreates dropped tables and resets the version counter, causing the migration to re-run against empty tables (silent data loss). **Fix: update `schema.sql` to match post-migration state.**

2. **`updated_at` column doesn't exist on source table.** `meal_plan_entries` had no `updated_at`. The `INSERT INTO calendar_entries ... SELECT ..., updated_at FROM meal_plan_entries` hard-fails. **Fix: use `created_at` as both values.**

3. **Hardcoded `id = 1` in grocery consolidation.** Production data had grocery list with `id = 3`. `INSERT OR IGNORE INTO grocery_lists (id, name) VALUES (1, ...)` creates a duplicate row instead of consolidating. **Fix: use `SELECT MIN(id) FROM grocery_lists` dynamically.**

4. **Dangling FK after table drop.** `grocery_lists.meal_plan_id` references `meal_plans(id)`. Dropping `meal_plans` while `grocery_lists` still has the FK column causes `PRAGMA foreign_keys = ON` to reject future inserts. **Fix: recreate `grocery_lists` without the FK column.**

5. **`VACUUM INTO` with f-string is SQL injection.** `await db.execute(f"VACUUM INTO '{backup}'")` — if the path contains `'`, it breaks. **Fix: escape single quotes or always use `shutil.copy2` fallback.**

### Backup Strategy

```python
# VACUUM INTO is WAL-safe (shutil.copy is not)
backup_safe = backup.replace("'", "''")
await db.execute(f"VACUUM INTO '{backup_safe}'")
```

Fallback to `asyncio.to_thread(shutil.copy2, ...)` if VACUUM INTO fails (e.g., older SQLite).

### Caching Singleton IDs

The single global grocery list has one row. Every grocery operation called `_get_global_list_id()` which queried the DB. With module-level caching:

```python
_cached_global_list_id: int | None = None

async def _get_global_list_id(db):
    global _cached_global_list_id
    if _cached_global_list_id is not None:
        return _cached_global_list_id
    # ... query and cache ...
```

**Test isolation caveat:** The cache persists across tests (each gets a fresh DB). Reset it in test fixtures:
```python
db_mod._cached_global_list_id = None
```

### Pantry Matching Performance

O(G*P) substring scan (`any(p in norm for p in pantry_names)`) produces false positives and is slow at scale. Exact set lookup is correct and O(G):

```python
pantry_names = {row["name"].lower() for row in pantry_rows}
item["in_pantry"] = norm in pantry_names  # not substring!
```

### Three-Entry-Point Pattern

Every feature must work through web UI, REST API, and MCP tools, all calling the same `db.py` functions. When restructuring:

1. Update `db.py` functions first (single source of truth)
2. Update all three entry points atomically
3. Never register both old and new MCP tools simultaneously
4. All write tools must return rich output (not just `"ok"`)
5. Batch operations (e.g., `add_to_calendar_batch`) are justified for agent ergonomics even when the web UI doesn't need them

### Dead Code Cleanup

After a model restructure, delete dead files immediately — don't leave them "for reference":
- Old router files with broken imports cause confusion
- Old templates with stale URL patterns mislead developers
- `_KNOWN_TABLES` allowlists need updating for pre-migration compat

## Prevention

1. **Always update `schema.sql` alongside migrations.** The two must stay in sync — `schema.sql` is for fresh installs, migrations are for upgrades.
2. **Test migration on a populated DB** — not just empty DBs in test fixtures.
3. **Use `PRAGMA foreign_key_check` and actually check the results** — the pragma returns rows describing violations, it doesn't raise errors.
4. **Never hardcode IDs in migration SQL** — use `SELECT MIN(id)` or similar dynamic queries.
5. **Validate date inputs with Pydantic `date` type** — not `str`. Free validation, prevents garbage data.

## Related

- `docs/solutions/implementation-patterns/calendar-view-paprika-import-fastapi-htmx.md` — HTMX calendar patterns (hx-sync, event delegation, historyRestore)
- `docs/solutions/implementation-patterns/grocery-aggregation-pipeline-and-code-review-fixes.md` — Fraction arithmetic, aisle matching, asyncio.to_thread
- `docs/solutions/implementation-patterns/grocery-management-mcp-web-parity-code-review.md` — Entry-point parity checklist, sanitization patterns
