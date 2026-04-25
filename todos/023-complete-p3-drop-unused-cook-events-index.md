---
status: complete
priority: p3
issue_id: "023"
tags: [code-review, performance, last-cooked-history]
dependencies: []
---

# `idx_cook_events_cooked_at` has no current consumer

## Problem Statement
Two indexes were added to `recipe_cook_events`:
- `idx_cook_events_recipe_time(recipe_id, cooked_at DESC)` — used by `list_recipe_cook_events` (filter by recipe_id, sort by cooked_at) AND `_refresh_recipe_freshness` MAX/COUNT
- `idx_cook_events_cooked_at(cooked_at DESC)` — currently has zero callers in the codebase

The composite `recipe_id, cooked_at DESC` index serves all current queries. The standalone `cooked_at DESC` index would only matter for a "global cook timeline" query that doesn't exist.

## Findings
- **performance-oracle P2.2**: every INSERT pays maintenance cost for an index with no consumer; unused indexes imply a query that doesn't exist (smell)

## Recommended Fix
Drop `idx_cook_events_cooked_at` from both `schema.sql:140-141` AND the v5 migration in `db.py`. Add it back the day a global timeline query lands.

## Acceptance Criteria
- [ ] Index removed from `schema.sql`
- [ ] Index removed from v5 migration block
- [ ] Migration test still passes
