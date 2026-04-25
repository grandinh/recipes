---
status: complete
priority: p1
issue_id: "017"
tags: [code-review, data-integrity, mcp, last-cooked-history]
dependencies: []
---

# MCP `record_recipe_cooked` accepts arbitrary `cooked_at` string, no validation

## Problem Statement
The REST path validates `cooked_at` via Pydantic `datetime` and re-serializes via `.isoformat()` (`routers/recipes.py:82`). The MCP tool (`mcp_server.py:60-78`) and the underlying `db.record_recipe_cooked` (`db.py:1041`) accept `cooked_at: str | None` and INSERT it verbatim. SQLite's TEXT column stores anything.

A misbehaving (or naïve) agent passing `cooked_at="yesterday"` corrupts:
- `recipes.last_cooked_at` — derived via `MAX(cooked_at)` lexicographically, so garbage outranks real ISO timestamps
- `sort=last_cooked` ordering
- `relative_time` filter renders the raw string when `fromisoformat` fails

Same gap covers timezone semantics: naive ISO strings are stored verbatim and treated as UTC by the filter; a "today, 22:00 local" cook can render as "yesterday."

## Findings
- **kieran-python-reviewer P1 #2**: timezone contract implicit and subtly wrong; document or normalize at the boundary
- **security-sentinel P2**: MCP path bypasses Pydantic boundary present on REST — data integrity, not RCE
- **codex (D3)** High: MAX/ORDER BY are lexicographic; malformed timestamps corrupt freshness state and ordering

## Recommended Fix
Validate at the DB layer (catches both MCP and REST in one place):
```python
if cooked_at is not None:
    cooked_at = datetime.fromisoformat(cooked_at).isoformat()
```
Raise `ValueError` on parse failure; the existing handler maps it to 422 (REST) / `{"error": ...}` (MCP).

## Acceptance Criteria
- [ ] `db.record_recipe_cooked` rejects non-ISO `cooked_at`
- [ ] Test: MCP `record_recipe_cooked(cooked_at="yesterday")` returns an error
- [ ] Document the expected timezone contract in the MCP tool docstring (covered by todo 020)
