---
status: complete
priority: p2
issue_id: "020"
tags: [code-review, mcp, agent-native, last-cooked-history]
dependencies: []
---

# MCP cook-event tools have inconsistent return shapes and missing docstrings

## Problem Statement
Three small gaps that hurt agent usability:

1. **Return-shape inconsistency.** `record_recipe_cooked` returns `{"event": ..., "recipe": ...}` or `{"error": ...}`. `delete_recipe_cook_event` returns a plain string `"Cook event N deleted"` or `"Cook event N not found"`. An agent has to substring-match `"deleted"` to detect success — see `tests/test_cook_events.py:264`.

2. **REST/MCP disagreement on missing recipe.** `GET /api/recipes/{id}/cook-events` 404s for a non-existent recipe; MCP `get_recipe_cook_history` returns `[]` silently. Agent can't distinguish "no events yet" from "wrong recipe id."

3. **Docstrings undersell capability.**
   - `record_recipe_cooked` (mcp_server.py:60-67): no mention of `notes`, `calendar_entry_id`, the allowed `source` enum values, the silent downgrade-to-manual behavior, or the timezone contract for `cooked_at`.
   - `get_recipe_cook_history` (mcp_server.py:84-88): no mention of the return shape or default limit semantics.
   - `search_recipes` (mcp_server.py:31-36): "Sort options: name, rating, recent (default)" — `last_cooked` is now accepted but invisible to agents reading the docstring.

## Findings
- **agent-native-reviewer P1 #1, #2; P3 #5, #6**: docstring gaps + return shape divergence
- **pattern-recognition-specialist #7**: MCP/REST disagree on missing-recipe semantics

## Recommended Fix
- `delete_recipe_cook_event` → return `{"deleted": True, "event_id": id}` / `{"error": "..."}`
- `get_recipe_cook_history` → 404-equivalent (`{"error": "Recipe N not found"}`) when recipe missing
- Expand all three docstrings with full param + return shape + enum values

## Acceptance Criteria
- [ ] `delete_recipe_cook_event` returns dict shape
- [ ] `get_recipe_cook_history` errors on missing recipe
- [ ] `record_recipe_cooked` docstring documents `source` enum, `notes`, downgrade behavior, timezone
- [ ] `search_recipes` docstring lists `last_cooked` sort option
- [ ] `tests/test_cook_events.py:264` updated to match new shape
