---
status: pending
priority: p1
issue_id: "009"
tags: [code-review, ui-redesign, timer, css-js-mismatch]
dependencies: []
---

# Timer dismiss button unstyled — CSS defines `.timer-entry-remove`, JS creates `.timer-dismiss-btn`

## Problem Statement
In the "baseline + compat" CSS block I appended to `static/style.css`, I defined `.timer-entry-remove` styling. But `app.js` creates timer-entry close buttons with class `.timer-dismiss-btn`. Result: when a cooking timer is running and the user opens the floating timer panel, the × button is completely unstyled (browser-default `<button>`).

## Findings
- **code-simplicity-reviewer #6**: "`.timer-entry-remove` is defined; JS creates `.timer-dismiss-btn`. Rename the CSS selector to match the JS, don't rename the JS."

## Proposed Solutions
**Rename CSS, not JS** (single edit, `style.css:1463-1473`): `.timer-entry-remove` → `.timer-dismiss-btn` (+ `:hover` variant).

## Acceptance Criteria
- [ ] Run a cooking-mode timer; the × dismiss button has the ghost-button hover treatment
- [ ] No remaining `.timer-entry-remove` references in the codebase

## Technical Details
Files: `/root/recipes/static/style.css:1463-1473`. Verify JS class name at `/root/recipes/static/app.js` (search for `timer-dismiss-btn` to confirm).
