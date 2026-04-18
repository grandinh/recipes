---
status: pending
priority: p3
issue_id: "015"
tags: [code-review, ui-redesign, polish, cleanup]
dependencies: []
---

# UI-redesign polish bundle (inline styles, architecture nits, small cleanups)

## Problem Statement
A batch of low-priority polish items surfaced by the code review. Individually small; grouped to avoid PR churn.

## Findings

### Inline-style cleanups
- **8 redundant `style="display: inline;"` on `<form class="inline-form">`** — `.inline-form` already sets `display: inline` (`style.css:1579`). Files: `recipe_detail.html:51,61,68`; `calendar.html:21,83,116`; `pantry.html:49`; `grocery.html:58`.
- **Promote `.hint`-style inline `color: var(--text-tertiary)`** to the existing `.hint` class or a new `.muted` utility. ~4 occurrences.
- **Stat-tile boilerplate in `import_results.html:15-27`** — 3 identical inline-styled count tiles with only the color variable changing. Introduce `.stat-tile.success / .warning / .danger`.
- **Star color inline styles** — `color: var(--star-empty)`/`color: var(--star-filled)` appear in `recipe_detail.html:26,64` and `recipes.html:69`. Introduce `.star-empty` / `.star-filled` utility classes.

### Architecture nits (defer but record)
- **`base.html:32-38` nav-active via `request.url.path.startswith(...)`** — works but couples nav to URL shapes. Cleaner pattern is `{% block current_nav %}recipes{% endblock %}` in each child template + a single equality check in base.html. Low urgency.
- **Three separate `htmx:afterSettle` handlers** (`app.js:45`, `1112`, `1136`) — idempotent, but fragmentation smell. Fold `initRecipeTabs()` and tweaks re-bind into `initHtmxHandlers()`.
- **Nested-ID with `hx-swap="innerHTML"`** — pre-existing issue across `#items-list`, `#recipe-grid`, `#calendar-grid`, `#pantry-list`. Wrapper div inside `{% block %}` means the swap stuffs a `<div id="X">` inside an existing `<div id="X">`. Fix: move wrapper outside the block declaration or switch to `hx-swap="outerHTML"`. Not user-visible today, latent footgun.

### Misc
- **Inline `<style>` tag in `calendar.html:143-147`** — the media query belongs in `style.css` under Responsive.
- **`data-theme="auto"` hardcoded on `<html>` in `base.html:2`** — `applyTheme('auto')` removes the attribute on load. Cosmetic mismatch.
- **`<datalist id="unit-suggestions">` hardcodes 21 units in `pantry.html:26-35`** — fine for now, flag that dynamic unit suggestion would be nicer.

## Proposed Solutions
Batch into a single cleanup commit. Delete the 8 redundant inline `display: inline;`s first (zero risk, highest signal/effort ratio). Move the calendar media query next. Star + stat-tile utility classes if time permits. Architecture nits stay as notes.

## Acceptance Criteria
- [ ] `grep -rn 'style="display: inline;"' src/recipe_app/templates/ | grep inline-form` returns zero hits
- [ ] `calendar.html` has no `<style>` tag
- [ ] `grep -rn "color: var(--star-" src/recipe_app/templates/` returns zero hits (replaced by utility classes)

## Technical Details
Many small file edits — see Findings for specific locations.
