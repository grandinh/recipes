---
title: "Sprint 5: Paprika Workflow Parity + Polish"
type: feat
status: brainstorm
date: 2026-03-27
supersedes: docs/brainstorms/2026-03-26-004-feat-polish-parity-brainstorm.md
---

# Sprint 5: Paprika Workflow Parity + Polish

## What We're Building

The core cooking workflow doesn't match how Paprika works. This sprint fixes the three structural mismatches (meal planning, grocery lists, pantry) and then adds polish features.

### Phase 1: Model Shift — Make It Work Like Paprika

#### 1a. Global Calendar (replaces Meal Plans)

**Current model (wrong):** Create named meal plans → add entries → view calendar per plan. This is Paprika's "menus" feature, not its meal planning feature.

**Target model (Paprika-style):** One global calendar. Drop recipes onto dates and meal slots (breakfast/lunch/dinner/snack). Generate grocery lists from a date range. No "meal plan" abstraction in between.

**What changes:**
- `meal_plans` table goes away (or becomes vestigial)
- `meal_plan_entries` becomes `calendar_entries` — orphaned from a parent plan, just date + slot + recipe
- Calendar is the primary meal planning view (nav link: "Meal Plans" → "Calendar" or "Planner")
- "Generate Grocery List" takes a date range from the calendar, not a meal plan ID
- Calendar entries are recipes only (no free-text meals) — keeps data clean and grocery generation reliable
- MCP tools simplify: `add_to_calendar(recipe_id, date, slot)`, `get_calendar_week(date)`, `generate_grocery_list(date_start, date_end)`

#### 1b. Single Global Grocery List

**Current model (wrong):** Multiple named grocery lists, each generated from a specific meal plan. Heavyweight.

**Target model (Paprika-style):** One persistent grocery list. Add items from recipes, from the calendar, or manually. Items accumulate and persist — checking them off marks "bought" but doesn't remove them.

**What changes:**
- `grocery_lists` table goes away (or retains one row as the global list)
- `grocery_list_items` becomes a flat table with `is_checked` (bought) state
- Items organized by aisle (category/aisle field on each item)
- Filter toggle in UI: "to buy" / "bought" / "all"
- **Manual add:** Free-text input to add arbitrary items (paper towels, diapers, etc.) — this is a general shopping list, not just recipe ingredients. Aisle auto-detected or manually assigned.
- **"Add to grocery list" from recipe:** Preview checklist of ingredients organized by aisle. Pantry matches pre-unchecked. User confirms what to add. NLP ingredient parser normalizes names (advantage over Paprika's unnormalized ingredient mess).
- **"Generate from calendar":** Takes date range, aggregates ingredients across recipes, shows same preview-and-confirm flow, appends to global list.
- Pantry items included but visually marked "in pantry" (not auto-excluded)
- Explicit "Clear bought items" action when done — cache-like, not auto-delete
- MCP: `add_recipe_to_grocery_list(recipe_id)`, `generate_grocery_list_from_calendar(start, end)`, `get_grocery_list()`, `add_grocery_item(name, aisle?)`

**Future-proofing:** Keep `grocery_list_id` FK in items table. For now, everything points to a single default list. Multiple lists can come later without schema change.

#### 1c. Pantry Overhaul

**Current state:** Schema has quantity, unit, category, expiration_date — but the UI only exposes name + expiration on add. No edit. No useful interaction. Feels empty and broken.

**Target:**
- Add form: name, quantity, unit, category (aisle/location), expiration date
- Inline edit: click to update any field
- Expiration warnings: visual indicators (already partially there), sort by expiry option
- Better layout: grouped by category/location, not just a flat list
- Integration: pantry items flagged in grocery list generation

### Phase 2: Polish + Export

#### 2a. Export (HTML + Paprika Format)

- HTML export with schema.org Recipe markup — single recipe or full collection with index
- Paprika format: reverse of import (gzip JSON per recipe, bundle ZIP). Include photos if present
- Selective export: all, by category, by search query
- Endpoint: `GET /export?format=html|paprika&category=X`
- Browser print-to-PDF already works via existing print stylesheet — no additional PDF work needed

#### 2b. Dark Mode

- CSS custom properties already in place — define dark color set
- `prefers-color-scheme` media query for auto-detection + manual toggle
- Toggle persisted in `localStorage`
- Recipe photos: subtle border/shadow to prevent float-in-dark effect

#### 2c. Wake Lock in Cooking Mode

- `navigator.wakeLock.request('screen')` when cooking mode activates
- Release on cooking mode exit
- ~10 lines of JS, no backend changes

#### 2d. Search Result Highlighting

- Use FTS5 `highlight()` auxiliary function in search queries
- Render matched terms with `<mark>` tags in result cards
- Careful sanitization to prevent XSS through highlight injection

#### 2e. Category Management UI

- Dedicated section or page for creating/renaming/deleting categories
- Currently only accessible via API/MCP — needs web UI
- Inline HTMX forms for CRUD operations

## Why This Approach

**Model shift first** because:
- The calendar/grocery/pantry workflow is the core of the app — everything else layers on top
- Polishing UI that's about to be restructured wastes effort
- The current model actively confuses usage (creating "meal plans" when you just want to plan meals)

**Single global list** because:
- Matches Paprika mental model
- Simpler UX — no list management overhead
- Schema keeps `grocery_list_id` FK for future multi-list without migration

**Pantry items shown (not excluded)** because:
- User wants visibility into what's already on hand
- Auto-exclusion hides information — marking is more informative
- User can manually uncheck items they don't need to buy

## Key Decisions

1. **Single global calendar** replaces the meal plans model
2. **Single global grocery list** (schema ready for future multi-list)
3. **Pantry items marked "in pantry"** in grocery list, not auto-excluded
4. **Full pantry CRUD** with quantity, unit, category, expiration
5. **Phase 1 (model shift) before Phase 2 (polish)** — get the workflow right first
6. **No unit conversion** — YAGNI for now
7. **No recipe-to-recipe linking** — not needed yet
8. **No meal plan templates** — the old meal_plans model was already template-like; the global calendar replaces it
9. **Export: HTML + Paprika** — PDF is free via browser print
10. **Manual grocery items** — grocery list is a general shopping list, not just recipe ingredients
11. **Preview + deselect** when adding recipe ingredients to grocery list — pantry items pre-unchecked
12. **Calendar entries are recipes only** — no free-text meals
13. **19 aisles** — current 14 + Deli, International/Ethnic, Health & Beauty, Household, Pet

## Aisle Expansion

Current 14 aisles cover recipe ingredients well. Add these to round out a full grocery/cooking logistics app:
- **Deli** — deli meats, prepared salads, rotisserie chicken
- **International/Ethnic** — curry paste, fish sauce, miso, tortillas (specialty), rice paper
- **Health & Beauty** — vitamins, medicine, personal care. Not recipe-related but part of a full grocery run.
- **Household** — paper towels, trash bags, cleaning supplies, etc. Same rationale.
- **Pet** — pet food, treats, litter. Common grocery list item.

Keep current 14 aisles + add these 5 (Deli, International/Ethnic, Health & Beauty, Household, Pet). User may expand further later. Aisles should be user-editable (add/rename/reorder) in a future sprint.

## Deferred / Not Included

- Unit conversion (metric/imperial) — YAGNI, revisit if needed
- Recipe-to-recipe linking (`[[Name]]` syntax) — nice-to-have, not workflow-critical
- Meal plan templates/menus — the old model was this; global calendar replaces it
- Multiple grocery lists — future feature, schema ready
- Aisle management / custom sort — can layer on later

## Resolved Questions

1. **Migration strategy:** Fresh start — drop old meal_plans/grocery_lists tables, new schema. No critical historical data to preserve. Existing MCP tools get replaced with new calendar/grocery APIs.
2. **Calendar navigation:** Week view only. Keep it simple, works on mobile. Month view can come later if needed.
3. **Grocery list behavior:** Cache-like (Paprika-style). Items have a "checked/bought" state and persist in the list. Filter toggle: "to buy" / "bought" / "all". Organized by aisle. Items are NOT deleted when checked — they stay until explicitly cleared. This is a shopping list you accumulate over time and clear when done.
4. **Aisles:** Keep current 14 + add 5 (Deli, International/Ethnic, Health & Beauty, Household, Pet). User-editable aisles deferred to future sprint.
5. **Manual grocery items:** Yes — this is a general shopping list. Users can add arbitrary items not from any recipe.
6. **Add-to-grocery flow:** Preview + deselect. Show ingredients by aisle, pantry items pre-unchecked, user confirms. NLP parser normalizes ingredient names.
7. **Calendar entries:** Recipes only. No free-text meals. Keeps grocery generation clean.
8. **App identity:** This is a cooking logistics app with Paprika 3-level recipe management, not just a recipe manager. The meal plan → grocery → shopping → pantry workflow is the core.
