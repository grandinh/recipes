---
status: pending
priority: p1
issue_id: "008"
tags: [code-review, ui-redesign, grocery, silent-bug, htmx]
dependencies: []
---

# Grocery aisle empty-state detection silently broken (two compounding bugs)

## Problem Statement
Two related issues break the "hide checked → collapse fully-checked aisles" behavior on the grocery page:

1. `app.js:948` `_updateAisleEmptyState()` queries `.aisle-section`. The redesign renamed that wrapper to `.grocery-aisle` in `grocery.html:69`. No `.aisle-section` nodes exist anymore → function is a no-op.
2. The `grocery_item` Jinja fragment at `grocery.html:78` uses `data-aisle="{{ aisle }}"`. Variable is only in scope during the full-page loop. When a single checkbox toggle calls the fragment with `block_name="grocery_item"` (`main.py:476`), the context is `{"item": item, "glist": {}}` — `aisle` is undefined, Jinja renders `data-aisle=""`. After any check, that row can no longer be grouped by aisle.

Combined effect: toggle "Hide checked" on a fully-checked aisle → the aisle header and `+` stay visible with no items underneath. Not a crash; silent behavioral degradation.

## Findings
- **architecture-strategist H1**: `.aisle-section` class rename not propagated to `app.js:948`.
- **architecture-strategist H2**: `grocery_item` scoped block fragment loses `aisle` context on per-item re-render.
- **learnings-researcher** flagged this matches a recurring theme: "class renames → JS queries + test assertions must move in lockstep" (from `docs/solutions/ui-bugs/fix-qa-display-bugs-scaling-escaping-jsonld-nutrition.md`).

## Proposed Solutions
**Fix both together:**
1. `app.js:948` — `.aisle-section` → `.grocery-aisle` (1-line change).
2. `main.py:476` — change fragment call from `{"item": item, "glist": {}}` to `{"item": item, "aisle": item["aisle"], "glist": {}}` (requires confirming `item["aisle"]` exists; if not, look up via `grocery.html:78`'s template logic and inline into the fragment).
   Alternative: drop `data-aisle` from the fragment entirely and derive the aisle at runtime in `app.js` by walking up to the closest `.grocery-aisle`.

## Acceptance Criteria
- [ ] After checking all items in an aisle, toggling "Hide checked" collapses that aisle
- [ ] `data-aisle="..."` has a real aisle name on items after a per-item check toggle (verify via DOM inspector)
- [ ] Regression test added under `tests/test_grocery_aggregation.py` that exercises the per-item check fragment and asserts `data-aisle` non-empty

## Technical Details
Files: `/root/recipes/static/app.js:948`, `/root/recipes/src/recipe_app/main.py:473-478`, `/root/recipes/src/recipe_app/templates/grocery.html:69,78`.
