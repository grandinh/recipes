---
title: "Sprint 5: Polish + Full Paprika Parity"
type: feat
status: stub
date: 2026-03-26
---

# Sprint 5: Polish + Full Paprika Parity

## Context

By this point the core cooking companion features are in place. This sprint is about the long tail of Paprika features and UX polish that make the app feel complete rather than functional. These are individually small but collectively they're the difference between "I built a replacement" and "I don't miss Paprika."

## Problem Areas

### 1. Recipe-to-Recipe Linking

**Current state:** No way to reference one recipe from another. If a pie recipe uses a separate pie crust recipe, there's no connection between them.

**Paprika reference:** `[[Recipe Name]]` syntax in directions or notes renders as a clickable link to the referenced recipe. Enables component recipes (stocks, sauces, doughs) to be reused across dishes.

**Questions to explore:**
- Syntax: adopt Paprika's `[[Recipe Name]]` wiki-link style, or use something else?
- Resolution: exact title match? Case-insensitive? Fuzzy? What if the recipe doesn't exist (dead link styling)?
- Rendering: parse at display time (template filter) or store as actual links?
- Bidirectional: should the linked recipe show "used in: Apple Pie, Quiche Lorraine"?
- MCP relevance: should agents be able to query "what recipes use this recipe as a component"?

### 2. Reusable Menus (Meal Plan Templates)

**Current state:** Meal plans are one-off. No way to save a "Weeknight Rotation" template and stamp it onto different weeks.

**Paprika reference:** Named menus with N-day templates. Add entire menu to meal planner with a start date. Also supports adding a menu directly to the grocery list.

**Questions to explore:**
- Data model: separate `menus` table, or a `is_template` flag on `meal_plans`?
- "Apply template" flow: pick a menu + start date -> creates concrete meal plan entries offset from day 1?
- Should templates use relative days (Day 1, Day 2) or day-of-week (Monday, Tuesday)?
- Can a template be applied multiple times (different weeks)?
- Grocery list generation from a template (before it's applied to specific dates)?

### 3. Export (HTML / PDF / Paprika Format)

**Current state:** No export functionality. Data goes in but doesn't come out (except via the API).

**Paprika reference:** HTML export with schema.org microformat + index.html, `.paprikarecipes` bulk export, category-filtered export scope.

**Questions to explore:**
- Which formats matter most? HTML (universal), Paprika (round-trip), PDF (printing/sharing)?
- HTML: single recipe page, or full collection with index? Schema.org recipe markup for SEO if self-hosted?
- PDF: server-side generation (WeasyPrint, reportlab) or client-side (browser print-to-PDF is already decent with the print stylesheet)?
- Paprika format: reverse of the import -- gzip each recipe JSON, bundle into ZIP. Include photo_data?
- Selective export: all recipes, by category, by search results, individual recipe?
- Endpoint design: `GET /export?format=html&category=Desserts` with streaming response?

### 4. Screen Wake Lock in Cooking Mode

**Current state:** No wake lock. Screen can sleep while cooking, which is the exact moment you need it on.

**Implementation:** `navigator.wakeLock.request('screen')` when cooking mode activates, release on exit. ~10 lines of JS. Paprika has this as a toggle.

**Questions to explore:**
- Automatic (always on in cooking mode) or manual toggle?
- Browser support: Wake Lock API is well-supported in modern browsers. Fallback for older browsers?
- Should it also activate when timers are running (Sprint 2)?

### 5. Unit Conversion (Metric/Imperial)

**Current state:** Scaling multiplies quantities but doesn't convert units. "2 cups" x 2 = "4 cups", never "~950 ml."

**Paprika reference:** Toggle between US standard and metric measurement systems.

**Questions to explore:**
- `pint` library was explicitly removed from the plan ("YAGNI"). Is it time to reconsider, or can we use a lightweight conversion table?
- Where does conversion happen: client-side toggle, server-side per-request, or stored preference?
- Precision: cooking conversions should round to practical amounts (250ml not 236.588ml).
- Should this be a global user preference or per-recipe toggle?
- Interaction with scaling: scale first then convert, or convert then scale? (mathematically equivalent but UX differs)

### 6. Dark Mode

**Current state:** Light theme only. CSS custom properties are already used for colors, making theming straightforward.

**Questions to explore:**
- `prefers-color-scheme` media query for automatic, plus manual toggle?
- Scope: just swap CSS custom property values, or do some components need structural changes?
- Image handling: recipe photos in dark mode -- add subtle border/shadow to prevent float-in-dark effect?
- Persist preference: `localStorage` or cookie?

### 7. Search Result Highlighting

**Current state:** FTS5 search returns ranked results but no indication of which terms matched or where.

**Questions to explore:**
- SQLite FTS5 `highlight()` and `snippet()` auxiliary functions -- use these directly in the query?
- Apply to which fields: title, description, ingredients? All searchable fields?
- Rendering: `<mark>` tags in the result cards? Requires careful HTML sanitization to avoid XSS.
- Performance: does `highlight()` add meaningful overhead to the search query?

### 8. Category Management Web UI

**Current state:** Categories exist and can be assigned to recipes, but creating/renaming/deleting categories requires the API or MCP. No web UI for category administration.

**Questions to explore:**
- Dedicated settings/admin page, or inline management (e.g., create category from the recipe edit form)?
- Category renaming: update all junction table references, or is the name not the FK?
- Ordering: manual drag-to-reorder or alphabetical?
- Nesting: Paprika supports subcategories with ">" navigation. Worth implementing or overkill?

## Dependencies

- Paprika export depends on Paprika import (Sprint 3) for format knowledge
- Unit conversion interacts with scaling (already implemented)
- Dark mode is purely CSS -- no backend dependencies
- Wake lock is purely JS -- no backend dependencies

## Open Questions

- How many of these should be in one sprint vs. spread across multiple? Each is individually small but there are 8 items.
- Which of these does the user actually want vs. which are "completionist" features?
- Should we prioritize things that differentiate from Paprika (search highlighting, dark mode, recipe linking) over things that merely match it (export, unit conversion)?
