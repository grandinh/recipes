---
title: "Sprint 3: Calendar Meal Plan + Paprika Import"
type: feat
status: stub
date: 2026-03-26
---

# Sprint 3: Calendar Meal Plan + Paprika Import

## Context

These are the two structural features that complete the app's identity: a visual meal planner that makes weekly planning intuitive, and the ability to import from the app we're replacing. The meal plan data model already exists and works -- it just needs a calendar frontend. Paprika import is a format parsing problem with a well-documented spec.

## Problem Areas

### 1. Calendar-Based Meal Plan View

**Current state:** Meal plans render as a flat HTML table with columns: date, meal slot, recipe name, remove button. No visual calendar. No drag-and-drop. Chef agent creates plans by date/slot via MCP but users see a spreadsheet.

**Paprika reference:** Monthly/weekly/daily calendar views, drag-and-drop recipes to days, meal type color coding (breakfast/lunch/dinner/snack), navigation between time periods, configurable week start day.

**Questions to explore:**
- Which view(s) to build first? Weekly is probably highest value for meal planning. Monthly for overview. Daily might be overkill.
- Drag-and-drop: native HTML5 DnD, or a library? How does this interact with HTMX? Most DnD libraries assume SPA frameworks.
- Should we use a calendar library (e.g., FullCalendar) or build a simple CSS grid calendar? FullCalendar is heavy but feature-complete.
- HTMX approach: could meal slot cells be `hx-target` drop zones that POST to add/move entries?
- Mobile UX for calendar -- drag-and-drop doesn't work well on touch. Alternative interaction model?
- How to handle the "add recipe to day" flow: modal picker? Sidebar search? Inline dropdown?
- Color coding by meal type -- hardcoded palette or user-configurable?
- Should the calendar show recipes from ALL plans or just the selected plan? Paprika has one implicit calendar; we have named plans.
- `servings_override` is in the schema but unused -- surface it in the calendar entry UI?

### 2. Paprika 3 Import (.paprikarecipes)

**Current state:** No import from Paprika format. The app is described as a "Paprika 3 replacement" but can't migrate data from Paprika.

**Paprika format spec:** `.paprikarecipes` is a ZIP archive containing individually gzipped JSON files (one per recipe). Each JSON has: uid, name, ingredients, directions, servings, prep_time, cook_time, total_time, difficulty, rating, notes, source, source_url, categories, nutritional_info, description, photo_data (base64 JPEG), created, on_favorites, scale, etc.

**Questions to explore:**
- File upload UX: dedicated import page, or add to the existing "Add Recipe" form? Probably dedicated -- bulk import is a different flow.
- How to handle photo_data: decode base64, save to `data/photos/`, generate thumbnails? This couples with the photo upload feature (Sprint 1).
- Conflict resolution: what if a recipe with the same title or source_url already exists? Skip, overwrite, or create duplicate?
- Category creation: auto-create categories from the import, or map to existing categories?
- Progress feedback for large imports (1000+ recipes): streaming SSE progress, or batch with a results page?
- Should we also support `.paprikarecipe` (single recipe) in addition to `.paprikarecipes` (bulk)?
- Field mapping: Paprika's `on_favorites` -> `is_favorite`, `difficulty` string -> our enum, `rating` (0-5) -> our (1-5), `nutritional_info` text -> our JSON dict.
- Should we support export TO Paprika format for round-tripping? Or just one-way import?
- Other import formats to consider: plain text, YAML (Paprika supports this), JSON?

## Dependencies

- Photo upload handler (Sprint 1, item #1) should land before Paprika import, since imports include photo_data
- Meal plan data model is already complete -- calendar view is purely frontend
- May want to coordinate calendar view with Chef's meal plan generation to ensure plans created by the agent render well in the calendar

## Open Questions

- Should the calendar be a separate page or replace the current meal plan detail view?
- One unified calendar across all plans, or per-plan calendar views?
- Is FullCalendar worth the dependency weight, or can a lightweight CSS grid + HTMX approach cover the needed interactions?
- Import: batch size limits? Memory concerns for archives with 1000+ recipes with embedded photos?
