---
status: pending
priority: p2
issue_id: "013"
tags: [code-review, ui-redesign, cleanup, dead-code]
dependencies: [012]
---

# Delete ~90 lines of dead CSS (advanced-filter prototype, timer-widget duplicate, misc)

## Problem Statement
The design-handoff prototype CSS was copied verbatim. Several selectors have zero references in any rebuilt template or in `app.js` (confirmed via grep by both simplicity and performance reviewers). Plus two selectors in my appended "compat" block that have no consumers.

## Findings (from simplicity + performance agents; grep-verified)

Advanced-filter UI (deferred feature, no template uses these):
- `.filter-group` (`style.css:406-412`)
- `.filter-operator` (`style.css:414-424`)
- `.filter-field`, `:focus` (`style.css:426-440`)
- `.filter-remove`, `:hover` (`style.css:442-457`)
- `.filter-actions` (`style.css:459-463`)
- `.active-filters` (`style.css:465-470`)
- `.active-filter-chip`, `:button`, `:button:hover` (`style.css:472-499`)
- `.filter-not` (`style.css:501-504`)

Unused prototype elements:
- `.cooking-mode-banner-text` (`style.css:785-788`) — no `.cooking-mode-banner` element rendered
- `.timer-widget`, `.timer-widget.hidden`, `.timer-header`, `.timer-display`, `.timer-controls` (`style.css:814-849`) — duplicate of `.timer-panel`
- `.view-controls`, `.view-btn`, `.view-btn.active` (`style.css:949-974`) — view-toggle feature deferred

My compat-block dead adds:
- `.btn-danger` (`style.css:1573-1578`) — zero references
- `.pantry-matches-list` (`style.css:1619-1623`) — pantry_matches.html uses `.recipe-grid`

Duplicates (one will shadow the other — keep the later / correct one):
- `.form-row` at `1495-1499` AND `1547-1553` (latter wins)
- `.form-actions` at `1508-1513` AND `1554-1559`
- `.btn-small` (`1571`) vs `.btn-sm` (`302`) — identical styling, alias not needed

## Proposed Solutions
Delete all selectors listed above. Keep the `.btn-sm` canonical rule (line 302), update `recipe_form.html` references from `.btn-small`/`.btn-large` to `.btn-sm`/... or define `.btn-lg` once in the design-system section.

## Acceptance Criteria
- [ ] `style.css` drops from ~1623 lines to ~1530
- [ ] `grep -r "filter-group\|filter-operator\|filter-field\|timer-widget\|view-btn\|btn-danger\|pantry-matches-list\|cooking-mode-banner-text" static/ src/` returns zero hits
- [ ] All 7 redesigned templates + recipe_form.html + import*.html render visually unchanged

## Technical Details
Files: `/root/recipes/static/style.css` (primary), possibly `/root/recipes/src/recipe_app/templates/recipe_form.html` for `.btn-small`/`.btn-large` → `.btn-sm`/`.btn-lg` rename.
