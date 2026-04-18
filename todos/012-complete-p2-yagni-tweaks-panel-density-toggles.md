---
status: pending
priority: p2
issue_id: "012"
tags: [code-review, ui-redesign, simplicity, yagni]
dependencies: []
---

# YAGNI: drop card-size density + show-ratings/tags/meta toggles from tweaks panel

## Problem Statement
Per explicit user preference (memory: "keep it simple", "cut scope aggressively") and global CLAUDE.md ("Do not add features, abstractions, or configurability beyond what was asked"), three tweaks-panel sub-features are ceremony for a single-user app:

1. **Card-size density (compact/default/comfortable)** — one user doesn't need three card widths.
2. **Show ratings toggle** — if ratings are noise on the card, remove them from the card; don't add a toggle to hide them.
3. **Show tags toggle** — same argument.
4. **Show metadata toggle** — same argument.

Theme switcher (auto/light/dark) is justified and should stay — real CSS dark-theme vars exist, OS-default matches, cheap to implement.

## Findings
- **code-simplicity-reviewer #1**: "Paprika muscle memory but the user isn't switching them mid-session. Three body-class toggles + 3 localStorage keys + display:none rules for fields you chose to put on the card."
- **code-simplicity-reviewer summary**: ~50 lines CSS+JS+HTML can go.

## Proposed Solutions
Remove from `base.html`:
- `<select id="tweakCardSize">` block (lines 87-96)
- All three `<input type="checkbox" name="show{Ratings,Tags,Meta}">` blocks (lines 100-114)

Remove from `app.js`:
- `CARDSIZE_KEY`, `applyCardSize`, `sizeSel` references (lines 988, 998-1001, 1009-1015, 1036-1041)
- `displayMap` and its initialization block (lines 1044-1064)

Remove from `style.css`:
- `body.hide-ratings/.hide-tags/.hide-meta` rules (lines 803-805)
- `html[data-card-size="compact"] / "comfortable"` rules (lines 807-811)

Keep: theme radios + the Tweaks gear button.

## Acceptance Criteria
- [ ] Only theme radios remain in the tweaks panel
- [ ] No `localStorage` keys set for card size or display toggles
- [ ] Rendering unchanged on default settings (since they were defaults before)

## Technical Details
Files: `/root/recipes/src/recipe_app/templates/base.html:87-114`, `/root/recipes/static/app.js:988-1064`, `/root/recipes/static/style.css:803-811`.
