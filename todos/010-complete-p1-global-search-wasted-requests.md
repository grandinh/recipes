---
status: pending
priority: p1
issue_id: "010"
tags: [code-review, ui-redesign, htmx, performance, network]
dependencies: []
---

# Global search fires wasted ~50KB round-trips on /calendar and /grocery

## Problem Statement
`base.html:21-29` wires the global header search with `hx-trigger="input changed delay:300ms, search"` and `hx-target="#recipe-grid"`. On any non-recipes page (`/calendar`, `/grocery`, `/pantry`, `/import`, `/recipe/N`), `#recipe-grid` does not exist. HTMX still fires `GET /?q=...` on every debounced keystroke, receives the full recipes HTML (~50KB), fails `hx-select` for a missing target, and silently drops the response.

My `initGlobalSearchFallback` in `app.js` only catches the **Enter keypress** fallback — it does not intercept the 300ms debounced input-changed trigger. So typing "choco" from the calendar page = multiple wasted requests + pointless DB query + template render.

## Findings
- **performance-oracle #5**: "`initGlobalSearchFallback` does NOT fix this. It only fires on keydown Enter. The 300ms debounced input changed trigger fires without a keydown — it's HTMX's own timer."

## Proposed Solutions
**A. `htmx:configRequest` handler (recommended)** — one `document.body.addEventListener('htmx:configRequest', ...)` that calls `evt.preventDefault()` when source is `#globalSearch` and `#recipe-grid` is absent. Then navigate to `/?q=...` via `window.location`. Catches all triggers, not just Enter.

**B. Conditionally render `hx-*` attributes in `base.html`** — wrap the hx-get attributes in `{% if request.url.path in ('/', '') %}`. Clean but couples the header to route paths (worse for M3 in finding #013).

## Acceptance Criteria
- [ ] Load `/calendar`, type "choc" in global search, wait 500ms → Network panel shows zero GET to `/`
- [ ] Pressing Enter on `/calendar` with text still navigates to `/?q=...`
- [ ] On `/`, typing still triggers the debounced live filter (unchanged)

## Technical Details
Files: `/root/recipes/src/recipe_app/templates/base.html:21-29`, `/root/recipes/static/app.js:1085-1096, 1112-1114`.
