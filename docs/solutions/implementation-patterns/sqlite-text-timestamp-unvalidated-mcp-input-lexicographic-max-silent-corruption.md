---
title: "SQLite TEXT timestamps + unvalidated MCP input + lexicographic MAX = silent denorm corruption"
category: implementation-patterns
date: 2026-04-24
tags: [sqlite, aiosqlite, mcp, data-integrity, silent-failure, denormalization, boundary-validation, last-cooked-history]
module: db, mcp_server
symptom: "`recipes.last_cooked_at` shows raw garbage (e.g. the literal string `yesterday`); `?sort=last_cooked` returns recipes in nonsensical order; no error, no log line, full pytest suite still passes"
root_cause: "MCP tool surface accepts `cooked_at: str | None` and inserts verbatim into a TEXT column; SQLite's `MAX(cooked_at)` is lexicographic, so any non-ISO string outranks every legitimate ISO timestamp and silently overwrites the denormalized field"
---

# SQLite TEXT timestamps + unvalidated MCP input + lexicographic MAX = silent denorm corruption

## Problem

The MCP `record_recipe_cooked` tool typed `cooked_at` as `str | None` and inserted the raw string into the `recipe_cook_events.cooked_at` TEXT column, bypassing the Pydantic `datetime` coercion that protects the equivalent REST route. Because `recipes.last_cooked_at` is denormalized via `SELECT MAX(cooked_at) FROM recipe_cook_events WHERE recipe_id = ?` and SQLite's `MAX` over a TEXT column is **lexicographic**, any non-ISO string (e.g. `"yesterday"`) outranks every legitimate `2026-04-…` timestamp (`"y"` > `"2"`) and silently overwrites the denorm field, the `sort=last_cooked` ordering, and the `relative_time` Jinja render.

**Symptom you'd see:** `last_cooked_at` displays raw garbage in the UI (the word `yesterday` where a relative timestamp should be), `?sort=last_cooked` reorders the recipe list nonsensically, no error is logged anywhere (server or MCP), and the entire test suite stays green. The tip-off is the UI rendering — there is no other surfaced signal that the denorm field has been corrupted.

## Root Cause

Boundary mismatch between two ingress paths into the same persistence layer:

- **REST** (`routers/recipes.py:78`) — Pydantic `RecipeCookEventCreate.cooked_at: datetime | None` parses the value before it reaches the DB; malformed strings 422 at the API edge.
- **MCP** (`mcp_server.py:60-78`) — typed as `cooked_at: str | None = None` to accept agent-supplied ISO strings — but did **no parsing** — and `db.record_recipe_cooked` accepted `str | None` and bound the value verbatim into the `recipe_cook_events.cooked_at` TEXT column.

The downstream `UPDATE recipes SET last_cooked_at = (SELECT MAX(cooked_at) ...)` then sorts that column lexicographically as TEXT. `"yesterday"` > `"2026-04-20T18:30:00"` in string comparison, so garbage wins MAX and overwrites the denorm. The `relative_time` Jinja filter falls through to rendering the raw string when `fromisoformat` fails — autoescape protects against XSS but the UI displays nonsense.

It was silent because no exception fired, the denormalized fields updated successfully, no log line was written, and no test exercised the MCP path with garbage input. REST callers were fine; MCP callers (Hermes / chef tool) were the only reproduction path.

## Solution

A four-line guard added to `db.record_recipe_cooked` in `src/recipe_app/db.py`, immediately after the existing `_VALID_COOK_SOURCES` check:

```python
if source not in _VALID_COOK_SOURCES:
    raise ValueError(f"Invalid source: {source!r}")
if cooked_at is not None:
    try:
        cooked_at = datetime.fromisoformat(cooked_at).isoformat()
    except ValueError:
        raise ValueError(f"Invalid cooked_at: {cooked_at!r}") from None
```

The round-trip through `fromisoformat(...).isoformat()` both rejects garbage and normalizes the string, so what hits the INSERT is guaranteed lexicographically-sortable. **No handler changes required** — REST already wraps the call in `except ValueError as e: raise HTTPException(status_code=404, detail=str(e))` (`routers/recipes.py:93-94`) and MCP already wraps it in `except ValueError as e: return {"error": str(e)}` (`mcp_server.py:80-81`). The new failure mode rides existing rails.

### Why this layer (not REST, not MCP)

Validation lives in `db.record_recipe_cooked` — **one layer below the API surface** — rather than being duplicated at REST + MCP. The boundary mismatch *is* the bug (Pydantic at one entry point, raw `str` at the other), so the fix has to go where both paths converge, not at either entry. A single guard now covers REST, MCP, and any future caller (a fixture, a backfill script, a future tool) without re-deriving the contract.

Test coverage in `tests/test_cook_events.py::test_mcp_record_invalid_cooked_at_returns_error` exercises the MCP-with-garbage path specifically, locking the boundary against regression.

## Audit checklist for this codebase

The same shape exists in several other places. Each TEXT column below stores a date-like value AND is consumed by MAX/MIN/ORDER BY/`date()` filtering — same vulnerability class.

**TEXT columns at risk (`src/recipe_app/sql/schema.sql`):**
- `pantry_items.expiration_date` — `ORDER BY expiration_date ASC` and `date(expiration_date) <= date('now', '+? days')` filters; garbage breaks the date-window filter silently.
- `calendar_entries.date` — `ORDER BY ce.date, ce.meal_slot` and BETWEEN range filters; format mismatch silently excludes rows.
- `recipes.created_at` / `updated_at` — default sort `ORDER BY r.created_at DESC`. Today these are set by SQLite's `datetime('now')` so they're safe, but any future MCP/API path that supplies a string is exposed.

**DB helpers accepting `str | None` destined for those columns (`db.py`):**
- `add_pantry_item(expiration_date: str | None)` — no `fromisoformat` validation
- `update_pantry_item(**kwargs)` — `expiration_date` flows through `_PANTRY_COLUMNS` allowlist with no datetime parse
- `add_calendar_entry(date: str)` — no validation; reachable from MCP

**MCP tools that pass-through with no re-validation (`mcp_server.py`):**
- `add_to_calendar(date: str, ...)` — straight pass-through
- `add_to_calendar_batch` — same shape, multiplied
- `add_pantry_item(expiration_date: str | None)`
- `update_pantry_item(expiration_date: str | None)`

**Good reference for the right pattern:**
- `get_calendar_week(date: str)` already calls `date.fromisoformat()` — this is the shape to mirror across the helpers above.

## Prevention

**Rule.** Validate datetime/date inputs at the **DB-layer boundary**, not at the API or MCP boundary, when more than one ingress path writes to the same TEXT column.

**Why:** SQLite TEXT accepts any string; lexicographic MAX/MIN/ORDER BY silently corrupts when one writer skips parsing. API-layer Pydantic validation only protects the HTTP ingress — MCP, importers, fixtures, and migrations bypass it. Putting the guard in the DB helper means every caller — present and future — gets the protection automatically.

**How to apply:** in the `db.py` write helper, wrap the param in `datetime.fromisoformat(...)` (or `date.fromisoformat(...)` for date-only columns) inside a try/except that raises `ValueError` with a clear message; the caller surfaces it as `{"error": "Invalid <field>: ..."}` (MCP) or 422 (REST). Mirror the `record_recipe_cooked` shape (`db.py:1042-1062`).

**Test pattern for future schema PRs.** Any PR touching a TEXT-typed timestamp/date column must add at least one MCP-with-garbage test before merge. Template:

```python
async def test_mcp_<tool>_invalid_<field>_returns_error(client, <fixture>):
    async with Client(mcp_mod.mcp) as mcp_client:
        result = _parse_mcp_result(await mcp_client.call_tool(
            "<tool_name>", {"<id>": <id>, "<field>": "not-a-date"}))
        assert "error" in result and "Invalid <field>" in result["error"]
```

The reference implementation lives at `tests/test_cook_events.py::test_mcp_record_invalid_cooked_at_returns_error`.

## What the driving plan missed

The plan at `docs/plans/2026-04-18-001-feat-last-cooked-history-schema-plan.md` has a thorough "Risks & mitigation" table that anticipated `schema.sql` drift, denorm count-vs-events drift, and timezone-mismatch on display. It explicitly noted timestamps are stored as ISO 8601 — but treated **write-side validity** as a given, not a risk.

The gap: SQLite TEXT plus `?sort=last_cooked` plus an MCP tool whose argument schema accepted any string created a corruption vector where a malformed `cooked_at` (e.g. `"yesterday"`, a missing `T`, a localized format) silently sorts lexicographically beside well-formed ISO strings, producing wrong "due again" recommendations with no error. **Future plans touching SQLite TEXT columns that participate in ordering or comparison should add a "boundary-validation" row to the risks table whenever a non-REST entry point (MCP, import, scraper) can write to that column** — the typed-language assumption that "Pydantic catches it" only holds if every entry point routes through the same Pydantic model, which the MCP boundary historically does not.

## See also

- [`implementation-patterns/sqlite-model-restructure-global-calendar-grocery.md`](sqlite-model-restructure-global-calendar-grocery.md) — v3→v4 migration patterns (PRAGMA `user_version`, `schema.sql` drift, idempotent column adds). The v5 migration that added `last_cooked_at` rides directly on these conventions; this doc is the cautionary tail to that pattern — a clean migration is necessary but not sufficient if the column's *write path* lacks a type guard.
- [`implementation-patterns/grocery-management-mcp-web-parity-code-review.md`](grocery-management-mcp-web-parity-code-review.md) — same shape of bug (MCP entry point bypasses validation present elsewhere) in the grocery/pantry domain. Reinforces the rule: validate at the DB-layer boundary, not per-router, so MCP and REST stay in lockstep automatically.
- [`runtime-errors/systemd-silent-crash-loop-port-already-in-use-eaddrinuse.md`](../runtime-errors/systemd-silent-crash-loop-port-already-in-use-eaddrinuse.md) — sibling "silent-failure" tag. Different layer (process supervision vs data integrity) but the same operator lesson: failures that don't raise look like success until a downstream consumer surfaces the corruption.

## Detection — how to confirm this isn't already happening

Run against the live DB to find any non-ISO `cooked_at` rows already written:

```sql
SELECT id, recipe_id, cooked_at
  FROM recipe_cook_events
 WHERE cooked_at NOT GLOB '????-??-??T??:??:??*'
   AND cooked_at NOT GLOB '????-??-??T??:??:??';
```

Empty result set = clean. Non-empty = at least one corrupt row, and the recipe(s) referenced have a corrupted `recipes.last_cooked_at` denorm. Re-derive after cleanup:

```sql
UPDATE recipes SET last_cooked_at = (
  SELECT MAX(cooked_at) FROM recipe_cook_events WHERE recipe_id = recipes.id
);
```
