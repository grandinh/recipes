---
status: pending
priority: p2
issue_id: "011"
tags: [code-review, ui-redesign, htmx, lifecycle]
dependencies: []
---

# HTMX afterSettle lifecycle bugs (3 related)

## Problem Statement
Three related issues with how init code runs after boosted navigation and HTMX partial swaps:

1. **`initAll()` never re-runs on boosted nav**: `app.js:48` gates re-init on `target.tagName === 'MAIN' || target.closest('main')`. `hx-boost` swaps `<body>` by default — the target is `<body>`, neither condition matches. After clicking any nav link, `initCalendar`, `initScaling`, `initCookingMode`, `initTimerTriggers`, `initGroceryFilter` are skipped. Widgets rely on their own idempotent guards or delegated listeners, which partially masks the bug.
2. **Tweaks panel doesn't re-bind**: `initTweaks()` only runs on `DOMContentLoaded`. The Tweaks button in `base.html:48` sits in the header — swapped on boosted nav. After any nav, clicking Tweaks does nothing.
3. **Pointless `afterSettle` for `initGlobalSearchFallback`**: `app.js:1112-1114` re-binds the search fallback on every settle, but `#globalSearch` lives in the header outside `<main>` and is never re-created. The re-bind is a no-op.

## Findings
- **architecture-strategist M4**: `initAll()` gate misses `<body>` target.
- **architecture-strategist M6**: Tweaks panel re-bind missing.
- **performance-oracle 2e**: Dead `afterSettle` → `initGlobalSearchFallback`.
- **learnings-researcher**: maps to `docs/solutions/implementation-patterns/calendar-view-paprika-import-fastapi-htmx.md` — "listeners double on re-attach, form fields outside swapped blocks hold stale state." Use `dataset.bound` flags and idempotent re-init.

## Proposed Solutions
1. Change `app.js:48` to `if (target.tagName === 'BODY' || target.tagName === 'MAIN' || target.closest('main'))`. All inner inits are idempotent.
2. Call `initTweaks()` from the `htmx:afterSettle` handler in the tweaks IIFE (already guarded by `dataset.bound`).
3. Delete the `htmx:afterSettle` → `initGlobalSearchFallback` line at `app.js:1112-1114`.

## Acceptance Criteria
- [ ] Navigate `/` → `/calendar` via header nav → calendar `+` buttons still work without full page refresh
- [ ] Navigate `/` → `/grocery` → click Tweaks gear → panel opens
- [ ] No duplicate event listeners accumulate (verify via DevTools → Elements → Event Listeners after 3 nav hops)

## Technical Details
Files: `/root/recipes/static/app.js` lines 45-86 (main lifecycle dispatcher), 1003-1115 (tweaks IIFE), 1112-1114 (dead handler).
