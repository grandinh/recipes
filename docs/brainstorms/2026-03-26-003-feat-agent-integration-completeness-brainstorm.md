---
title: "Sprint 4: Agent Integration Completeness"
type: feat
status: stub
date: 2026-03-26
---

# Sprint 4: Agent Integration Completeness

## Context

The MCP server has 25 tools covering most features, but there are gaps that break key agent workflows. Chef's weekly meal planning cron and OpenClaw's conversational cooking assistant both hit dead ends when they can't check off grocery items or scan recipe cards. This sprint rounds out the agent API surface so both agents can complete full end-to-end workflows without falling back to the web UI.

## Problem Areas

### 1. Missing MCP Tools: Grocery Item Management

**Current state:** Agents can generate grocery lists and view them, but cannot check/uncheck items or add ad-hoc items to an existing list. The web UI can do both via HTMX endpoints (`POST /grocery-lists/{id}/items/{item_id}/toggle`, `POST /grocery-lists/{id}/items`), but these are HTML-returning routes, not MCP tools.

**Chef workflow gap:** Chef generates a weekly grocery list, delivers it via Slack. User shops and wants to tell Chef "mark the eggs as bought" or "add paper towels to the list." Currently impossible.

**Questions to explore:**
- Should MCP tools mirror the exact web UI endpoints, or have their own optimized interface? (e.g., bulk check multiple items in one call)
- `check_grocery_item` and `uncheck_grocery_item` as separate tools, or one `toggle_grocery_item` tool, or `update_grocery_item(is_checked=True)`?
- `add_grocery_item(list_id, text)` -- should it also accept structured input (name, quantity, unit, aisle)?
- Should there be a `clear_checked_items` tool for post-shopping cleanup?
- What about `move_to_pantry` -- Paprika moves purchased grocery items to pantry. Should the MCP tool do this?

### 2. OCR Recipe Scanning

**Current state:** `config.py` has `anthropic_api_key` field. Plan doc mentions OCR for v0.3. Nothing is implemented. The plan describes using Claude's vision API to extract recipe data from photos of cookbook pages or recipe cards.

**Agent workflow:** User photographs a recipe card, sends image to Chef via Slack or shares with OpenClaw. Agent calls `ocr_scan_recipe(image)` to extract structured data, then `create_recipe()` to save it.

**Questions to explore:**
- Input format: base64 image data, file path, or URL? MCP tools typically pass data, not file handles.
- Which vision model to use? Claude (via `anthropic_api_key` already in config) is the obvious choice. What prompt engineering is needed?
- Output structure: should OCR return a `RecipeCreate`-compatible dict, or raw extracted text that the agent then structures?
- Should OCR be one tool (`ocr_scan_recipe` returns a draft recipe) or two tools (`ocr_extract_text` + agent structures it)?
- Error handling: what if the image is blurry, not a recipe, or partially legible? Confidence scores?
- Should the web UI also have an OCR upload path, or is this agent-only?
- Cost considerations: Claude vision API calls have token costs. Rate limiting? Caching?
- Sanitization: plan doc flags that OCR output must pass through `sanitize_field()` before storage.

### 3. Webhook / Event Notifications

**Current state:** No event system. Agents poll for changes. Chef's cron runs on a schedule regardless of whether anything changed.

**Desired state:** Agents can subscribe to events (recipe created, meal plan updated, pantry item expiring) and react in real time.

**Questions to explore:**
- Is this actually needed now, or is polling sufficient? Chef runs weekly -- does it need real-time events?
- If yes: SSE from the FastAPI server? Webhook POST to a configured URL? MCP notification mechanism?
- What events matter? Recipe CRUD, meal plan changes, grocery list updates, pantry expiration warnings?
- Should this be an MCP resource subscription (MCP spec supports this) or a separate HTTP webhook system?
- OpenClaw connects via HTTP -- could it use SSE on a `/events` endpoint?
- Complexity vs. value: this might be over-engineering for a single-user app. Defer unless there's a concrete agent use case that polling can't serve.

## Dependencies

- Grocery item MCP tools depend on existing `db.py` functions (already implemented for web UI)
- OCR depends on `anthropic` SDK (would be a new dependency) and the Anthropic API key in config
- Webhooks/events would touch the core FastAPI app middleware -- higher blast radius

## Open Questions

- Priority ordering within this sprint: grocery MCP tools are clearly #1 (small effort, unblocks agents immediately). OCR is #2 (medium effort, high value for cookbook digitization). Webhooks are #3 (high effort, unclear ROI).
- Should OCR live in `mcp_server.py` or get its own module (`ocr.py`)? It has different dependencies (anthropic SDK) from the rest of the MCP server.
- Is there a way to test OCR without hitting the paid API? Mock responses? Local model?
