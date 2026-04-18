---
status: pending
priority: p1
issue_id: "007"
tags: [code-review, ui-redesign, cooking-mode, silent-bug]
dependencies: []
---

# Cooking-mode visual state broken — JS toggles CSS classes that don't exist

## Problem Statement
`app.js` cooking-mode code toggles `.strikethrough`, `.active-step`, `.completed-step` on ingredient checkboxes and direction steps. The redesigned `static/style.css` defines `.checked` on `.ingredient-item` and `.active` / `.completed` on `.direction-step` — **none of the class names match**. Cooking mode ingredient strike-through and step progression are silently non-visual: JS sets a class, CSS has no matching rule, nothing renders.

## Findings
- **performance-oracle**: `app.js:130-136` toggles `.strikethrough` on ingredient click; CSS has `.ingredient-item.checked { opacity: 0.5; text-decoration: line-through }` at `style.css:706-709`. Zero matches for `.strikethrough`.
- Same for `.active-step` / `.completed-step` at `app.js:180, 345, 383-392`. CSS defines `.direction-step.active` and `.direction-step.completed` (`style.css:743, 748`).
- CSP-regression test for `onchange=` still passes because the new ingredient checkbox delegation handles `.checked` correctly — but the pre-existing click-to-strikethrough path still uses the old class names.

## Proposed Solutions
**A. Rename JS to match new CSS (recommended)** — 4-6 lines in app.js. Replaces `.strikethrough` → `.checked`, `.active-step` → `.active`, `.completed-step` → `.completed`. Aligns with the new design-system naming.
- Pros: fewer CSS rules, consistent with redesign
- Cons: must touch all JS call sites (~6)
- Effort: Small

**B. Add legacy CSS rules** — 3 rules in style.css for the old names.
- Pros: zero JS changes
- Cons: perpetuates stale naming
- Effort: Small

## Acceptance Criteria
- [ ] Clicking a direction step in cooking mode visibly highlights it (blue border + accent bg)
- [ ] Prior steps show as completed (opacity 0.6)
- [ ] Clicking an ingredient strikes it through
- [ ] No `.strikethrough` / `.active-step` / `.completed-step` references remain in JS (or matching CSS exists)

## Technical Details
Files: `/root/recipes/static/app.js` lines 130, 180, 345, 383-392; `/root/recipes/static/style.css` lines 706, 743, 748.
