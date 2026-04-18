---
status: pending
priority: p2
issue_id: "014"
tags: [code-review, ui-redesign, performance, layout-shift, mobile]
dependencies: []
---

# Recipe card `<img>` missing `width`/`height` — causes layout shift on mobile lazy-load

## Problem Statement
`recipes.html:47, 52` renders recipe card thumbnails with `loading="lazy"` but no explicit `width`/`height`. The container (`.recipe-card-image`) has `height: 180px`, so the box is reserved, but the `<img>` element inside has no intrinsic dimensions. When the lazy image resolves on a mobile browser (slow 4G, Tailscale bridge), it triggers a recalc inside the fixed container — paint is still slow relative to "fully hinted" images.

Bonus finding: when a recipe has no `photo_path` but has `image_url` starting with `https`, the card fetches the **full-size original** remote image (no thumbnail). A 20-recipe grid page could mean 20 full-size jpegs.

## Findings
- **performance-oracle #3**: "no `width`/`height` attributes on the `<img>`. With `loading="lazy"`, this means every thumbnail triggers a layout shift when it resolves."
- Same finding: "For imported recipes that haven't had a thumbnail generated, this can mean 20 full-size remote jpegs on one grid page."

## Proposed Solutions
1. Add `width="280" height="180"` (or whatever matches the container) to every recipe-card `<img>`. Also add `decoding="async"` for good measure.
2. Separate follow-up (not this todo): generate thumbnails for external `image_url` at import time so the fallback branch doesn't serve originals.

## Acceptance Criteria
- [ ] Every recipe-card `<img>` on `recipes.html` has `width`, `height`, `decoding="async"`
- [ ] Lighthouse CLS score on `/` improves or stays at 0

## Technical Details
Files: `/root/recipes/src/recipe_app/templates/recipes.html:47, 52`.
