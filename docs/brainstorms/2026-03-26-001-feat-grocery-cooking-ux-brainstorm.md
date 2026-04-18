---
title: "Sprint 2: Grocery List UX + Cooking Experience"
type: feat
status: ready
date: 2026-03-26
deepened: 2026-03-26
---

# Sprint 2: Grocery List UX + Cooking Experience

## What We're Building

Three feature areas that transform this app from "recipe database" to "daily cooking companion":

1. **Smart grocery aggregation + shopping UX** — Sum duplicate ingredient quantities ("2 eggs + 3 eggs = 5 eggs"), group items by store aisle, date-range generation from meal plans, swipe-to-check, pantry exclusion, and sort/filter controls for a best-in-class shopping experience.

2. **Cooking timers** — Auto-detect time references in recipe directions, render them as tappable timer triggers, and manage multiple simultaneous countdown timers in a collapsible floating panel with Web Audio alerts.

3. **Step-by-step direction navigation** — Highlight the current cooking step, navigate with tap/click or keyboard (arrow keys, spacebar), persist position in localStorage.

## Why This Approach

These are the features Paprika users reach for most. The backend plumbing largely exists — the ingredient parser returns structured `{qty, unit, name}` data, cooking mode CSS has `.active-step` styles ready, and the grocery list CRUD is complete. The gaps are in the UI layer and missing business logic.

All three features are independent enough to build in sequence within one sprint. Grocery is backend + frontend (fix aggregation in `db.py`, build shopping UX), while timers and step nav are frontend-focused (extend `app.js` cooking mode).

---

## Key Decisions

### Grocery: Aggregation Engine

- **Same-unit summing only.** When ingredient names match and units match, sum quantities. When units differ (e.g., "1 cup milk" + "200ml milk"), keep as separate line items. No unit conversion — always correct, ships fast, avoids edge case errors.

- **Ingredient name normalization.** Seven strategies applied to the parser's `name` field, all mechanical and conservative. **Failure mode is "too many items" (status quo), never "wrong quantities."**
  1. **Strip parentheticals from name** — Confirmed via testing that the parser already strips parentheticals from the `name` field (they go into `comment`). This is effectively a no-op — `re.sub(r'\([^)]*\)', '', name)` is a safety net only.
  2. **Normalize hyphens** — `name.replace('-', ' ')`. Prevents "extra-virgin olive oil" and "extra virgin olive oil" from being separate items.
  3. **Singularize last word only** — Apply singularization to the LAST word of multi-word names. "green onions" → "green onion", not "greens onion". Rules: `-ies` → `-y` (berries→berry), `-ves` → `-f` (loaves→loaf), `-oes` → `-o` (tomatoes→tomato), `-ches/-shes` strip `-es`, general `-s` strip. Exception set for words ending in 's' that are singular: `{asparagus, citrus, couscous, hibiscus, hummus, octopus, bass, grass, harissa, swiss, anise, hollandaise, bearnaise, mayonnaise, molasses, grits, oats, brussels}`.
  4. **Pre-split "salt and pepper" compound lines** — Use an exact-match dictionary of ~10 known compound patterns (safer than regex). e.g., `"kosher salt and freshly ground black pepper"` → `["kosher salt", "freshly ground black pepper"]`. Only split when both sides are known staples. "Bread and butter pickles" stays intact.
  5. **Protect identity words** — "fresh" and "dried" are part of ingredient identity, NOT prep. The parser already keeps them in the name field ("fresh basil" ≠ "dried basil" ≠ "basil"). Normalization must not strip these. Similarly: "unsalted butter" ≠ "butter", "kosher salt" ≠ "salt", "extra-virgin olive oil" ≠ "olive oil" — no equivalence mapping.
  6. **Flag "for serving" / "(optional)" items** — Scan raw text and parser `comment`/`purpose` fields. Mark as optional/garnish, visually dim on grocery list or group under "Garnishes" aisle.
  7. **Flag "to taste" / "as needed" items** — Mark as likely pantry staples. Good candidates for auto-exclusion via pantry cross-reference.
  - Note: comma-separated prep instructions are already handled by the ingredient parser (it extracts name separately from preparation). No manual comma stripping needed.

- **Use Fraction arithmetic for quantity summing.** The ingredient-parser-nlp library returns `Fraction` objects natively. `Fraction(1,3) + Fraction(2,3) = Fraction(1,1)` — exact, no float precision issues. The current `ingredient_parser.py` converts to float too early (line ~114). Need a parallel path that preserves Fractions for aggregation, then uses `scaling.py`'s existing `format_quantity()` (which already does `Fraction.limit_denominator(8)`) for display.

- **Fix `string_units` for aggregation.** Current parser call uses `string_units=True`, returning raw strings ("cups" vs "cup") that won't match. Need `string_units=False` so pint normalizes "cups"/"cup"/"c" to the same canonical unit. Use `str(unit)` as the grouping key component.

- **Hardcoded aisle keyword map — 13 categories.** Based on cross-referencing Instacart, GroceryGenius, and Paprika 3, using US supermarket perimeter-first ordering:

  | Sort | Category |
  |------|----------|
  | 1 | Produce |
  | 2 | Fresh Herbs |
  | 3 | Bread & Bakery |
  | 4 | Deli & Prepared |
  | 5 | Dairy & Eggs |
  | 6 | Meat & Seafood |
  | 7 | Canned & Jarred |
  | 8 | Pasta, Rice & Grains |
  | 9 | Baking |
  | 10 | Condiments & Sauces |
  | 11 | Spices & Seasonings |
  | 12 | International |
  | 13 | Frozen |
  | 99 | Other |

  Matching strategy: longest-keyword-substring-first (so "coconut milk" matches Canned & Jarred before "milk" matches Dairy). ~400 keywords across all categories. "Other" appears last in sort order.

- **Self-healing aisle overrides.** `aisle_overrides` table stores user corrections. When a user moves an item to a different aisle in the UI, save it. MCP tool `correct_aisle(ingredient, aisle)` for agent feedback. Check overrides before hardcoded map. Also cross-reference pantry item categories (already stored) as a secondary source.

- **Schema migration required.** The "parse-on-demand" approach conflicts with shopping UX needs. Sort-by-aisle, sort-by-recipe, hide-checked filter, and pantry badges all require structured data available at render time without re-parsing. Add to `grocery_list_items`: `aisle TEXT`, `recipe_id INTEGER`, `normalized_name TEXT`, `is_optional INTEGER DEFAULT 0`, `is_pantry_staple INTEGER DEFAULT 0`. Create `aisle_overrides` table. Bump `PRAGMA user_version` to 3.

### Grocery: Date-Range Generation

- **Generate from date range, not just whole plan.** Add `date_start` and `date_end` params to `generate_grocery_list()`. Filter `meal_plan_entries.date BETWEEN ? AND ?`. The schema already has a `date` field and index on `meal_plan_entries` — just unused today.
- **Fix duplicate recipe multiplicity.** Current code uses `WHERE id IN (...)` which deduplicates recipe IDs — a recipe scheduled Monday AND Wednesday produces single quantities. Fix: use a JOIN that preserves duplicates, and sum per-entry (each meal plan entry contributes its own ingredients). Also incorporate `servings_override` from `meal_plan_entries` when present.
- **Three entry points.** All support grocery list generation:
  1. **Meal plan page**: Date range pickers (start/end) alongside existing "Generate Grocery List" button. If no recipes in range, show empty state message (not an error).
  2. **Individual recipe page**: "Add to grocery list" button. If one list exists, append to it. If multiple, show a dropdown. If none, create new. If recipe ingredients already on list, show "already added" state.
  3. **MCP tool**: `generate_grocery_list()` gains `date_start`/`date_end` params for agent workflows (e.g., "Chef, make me a grocery list for this week").

### Grocery: Shopping UX (Paprika improvements)

- **Swipe-to-check on mobile.** Implementation details from research:
  - 50px horizontal swipe threshold (below 30px = false positives, above 80px = too far on small screens)
  - `touch-action: pan-y` on swipeable items — browser handles vertical scroll, JS handles horizontal
  - 20px edge margin to avoid conflicting with iOS Safari back-swipe gesture
  - `{ passive: true }` on all touch listeners (no `preventDefault` needed)
  - Reveal-behind pattern: green background with checkmark icon revealed as item slides right
  - Animation: 200ms snap-back, 250ms slide-out (matches iOS micro-interaction timing)
  - Desktop fallback: visible checkbox (always present, works as tap target on mobile too)
  - Accessibility: `role="checkbox"`, `aria-checked`, `tabindex="0"`, Space/Enter keyboard toggle
  - Undo: swipe left or tap checkbox to uncheck. No timed undo toast (rapid check-off during shopping makes toasts noisy).

- **Sort toggle: aisle vs. recipe.** Client-side JavaScript DOM manipulation (all data present on initial render, no server round-trip). Aisle sort uses stored `aisle` field. Recipe sort uses stored `recipe_id` — aggregated items (multiple source recipes) go in an "All Recipes" group.

- **Filter: hide checked items.** Client-side CSS class toggle. When active: hide `[aria-checked="true"]` items, update count display to "X remaining", collapse empty aisle sections.

- **Auto-exclude pantry items — Paprika-style pre-check.** Don't remove pantry-matched items from the list. Instead, add them but mark as `is_checked = True` with a "in pantry" badge. Users can uncheck if they need more. Name-only matching (using shared normalization pipeline), no quantity awareness. Matches current `pantry_matcher.py` approach.

### Cooking Timers

- **Floating collapsible panel.** Small floating panel, collapsed by default, auto-expands when first timer starts. Positioned bottom-right with `env(safe-area-inset-bottom)` for iPhone home indicator. Collapsible back to a minimal badge showing active timer count. Auto-collapse when all timers dismissed, then hide entirely.

- **End-timestamp storage in localStorage.** Store `{ id, name, endTime, originalSeconds, recipeId, fired, createdAt }` — not countdowns. Calculate remaining time from `Date.now()` on each render tick. Handles phone sleep, incoming calls, and tab backgrounding correctly.

- **Timer cleanup.** On page load, remove timers whose `endTime` is more than 24 hours in the past. Auto-prune on every read to prevent unbounded localStorage growth.

- **Global panel in `base.html`.** Timer panel renders outside page content so timers persist across HTMX navigation. Reads timer state from localStorage on every page load. Timer labels should include recipe name to distinguish timers across recipes.

- **Wake Lock API** — automatic on cooking mode entry, released on exit. 96% browser support (Safari 16.4+). Auto-released by browser on tab background; must re-acquire on `visibilitychange` return. No separate toggle needed. Fallback for unsupported browsers: show a small notice ("keep your screen on manually").

- **Notification API** — progressive enhancement for desktop only. **Critical finding: does NOT work in iOS Safari tabs.** Only works in installed PWAs (iOS 16.4+). Request permission on first timer start. If denied, timers still work (audio only). Do not re-prompt.

- **Web Audio API beep** — primary alert mechanism (works everywhere including iOS Safari). Create `AudioContext` on first user gesture (Start Timer button click) to satisfy autoplay policy. 880Hz sine wave, 200ms on / 200ms off pattern via gain scheduling. Max 60 seconds of beeping, then auto-stop but leave visual "DONE" indicator. Note: iOS silent switch mutes Web Audio — no workaround.

- **`visibilitychange` catch-up.** When tab returns to foreground, immediately recalculate all timers, fire alarms for any that expired while backgrounded, and re-acquire Wake Lock if cooking mode is active.

- **Display interval.** `setInterval` at 1000ms (once per second). Each tick reads `Date.now()` fresh and computes remaining from `endTime`. No accumulated drift because no accumulated state. Stop interval when no active timers remain.

- **Timer detection regex.** Five patterns checked in priority order with overlap prevention:
  1. Compound: "1 hour 30 minutes", "1h30m"
  2. Range: "10-15 minutes", "10 to 15 min" (use upper bound)
  3. Verb-context: cooking verb within 40 chars of "N unit" (anchored to prevent false matches on "9-inch pan", "350 degrees")
  4. "for X minutes" standalone
  5. "overnight" → 8 hours
  - Cooking verbs: bake, cook, roast, broil, grill, fry, saute, simmer, boil, steam, braise, poach, blanch, sear, rest, cool, chill, marinate, soak, rise, proof, reduce, microwave, toast, smoke, stew, warm, heat, preheat
  - Detected times rendered as inline `<button class="timer-trigger">` elements within direction step text

- **No custom timers this sprint.** Only auto-detected from direction text. Ad-hoc timers deferred.

- **No service worker.** Skip background push notifications for now. The catch-up-on-return pattern + Web Audio covers 90% of real cooking use.

### Step-by-Step Navigation

- **Auto-activate step 1** on cooking mode entry.
- **Tap + keyboard controls.** Click/tap any step to select it. Arrow keys (up/down) and spacebar to advance. No swipe gestures for now.
- **Boundary behavior.** At last step, "next" is a no-op. At first step, "previous" is a no-op. No wrap-around.
- **localStorage persistence.** Store current step index with key `cooking-{recipeId}-step`. Cleared when exiting cooking mode (consistent with ingredient strikethrough clearing).
- **Visual treatment.** Active step gets existing `.active-step` CSS (orange-tinted background, left border accent). Steps before active are "completed" — dimmed to 50% opacity but still tappable (tap to go back). Active step auto-scrolls into view.
- **Timer trigger / step click overlap.** Detected times within direction steps are wrapped in `<button class="timer-trigger">` with `event.stopPropagation()` to prevent the step click from also firing. The timer trigger has its own click handler that starts the timer.
- **No auto-linking between steps and ingredients.** Advancing steps does not auto-strikethrough ingredients. These are independent interactions.

---

## Target Devices

Desktop, iPad, iPhone. Mobile-first considerations:
- Touch targets for timer controls and step selection (min 44px per Apple HIG)
- Swipe gestures for grocery check-off (touch events with `touch-action: pan-y`)
- Wake Lock API for uninterrupted cooking mode
- Timer panel uses `env(safe-area-inset-bottom)` for iPhone home indicator
- Timer panel respects `max-height: 60svh` (small viewport height, excludes browser chrome)

---

## Schema Changes

```sql
-- grocery_list_items: add structured fields for shopping UX
ALTER TABLE grocery_list_items ADD COLUMN aisle TEXT DEFAULT 'Other';
ALTER TABLE grocery_list_items ADD COLUMN recipe_id INTEGER REFERENCES recipes(id);
ALTER TABLE grocery_list_items ADD COLUMN normalized_name TEXT;
ALTER TABLE grocery_list_items ADD COLUMN is_optional INTEGER DEFAULT 0;
ALTER TABLE grocery_list_items ADD COLUMN is_pantry_staple INTEGER DEFAULT 0;

-- aisle_overrides: self-healing aisle assignments
CREATE TABLE IF NOT EXISTS aisle_overrides (
    ingredient_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    aisle TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

PRAGMA user_version = 3;
```

---

## Existing Code to Extend

| What exists | Where | What to change |
|------------|-------|----------------|
| Ingredient parser (`qty, unit, name`) | `ingredient_parser.py` | Add `string_units=False` path for aggregation; preserve Fraction objects |
| Grocery list generation | `db.py:generate_grocery_list()` (line ~800) | Replace "+" concatenation with Fraction summing; fix duplicate recipe multiplicity; add date range filter; add pantry pre-check |
| Grocery list UI | `grocery_list_detail.html` | Add aisle groups, swipe-to-check, sort/filter controls |
| Pantry matching | `pantry_matcher.py` | Share normalization pipeline with grocery aggregation |
| Pantry data | `db.py` pantry functions | Cross-reference during grocery generation (pre-check pattern) |
| Meal plan entries with dates | `meal_plan_entries` table (indexed on date) | Use date field for range-based generation; use `servings_override` |
| Quantity formatting | `scaling.py:format_quantity()` | Reuse for aggregated quantity display (already does `Fraction.limit_denominator(8)`) |
| Cooking mode toggle + strikethrough | `app.js:initCookingMode()` | Extend for step nav + timer triggers |
| Direction step HTML | `recipe_detail.html` | Already has `.direction-step` + `data-step` — add timer trigger buttons inside |
| Step highlight CSS | `style.css` | `.active-step` and `.direction-step` styles exist |
| Scaling (client + server) | `app.js` + `scaling.py` | No changes needed (scaling doesn't re-render directions) |

## What Needs to Be Built New

| Feature | Scope | Key files |
|---------|-------|-----------|
| Schema migration (v2 → v3) | Add structured columns to grocery_list_items, create aisle_overrides | `schema.sql`, migration logic in `db.py` |
| Ingredient normalization pipeline | 7 strategies on parser name field (~80 lines) | New: `normalizer.py` |
| Singularization function | Rule-based with ~20-word exception set | Part of `normalizer.py` |
| Compound line splitter | Exact-match dict of ~10 known patterns | Part of `normalizer.py` |
| Aisle keyword map | 13 categories, ~400 keywords, longest-match-first | New: `aisle_map.py` |
| Aisle assignment function | Check overrides → pantry categories → keyword map → "Other" | Part of `aisle_map.py` |
| Quantity summing with Fractions | Replace "+" concatenation in `generate_grocery_list()` | `db.py` |
| Date-range grocery generation | Add `date_start`/`date_end` filtering, fix recipe multiplicity | `db.py`, models, router, MCP tool |
| Pantry pre-check during generation | Cross-ref pantry items, mark as checked with badge | `db.py:generate_grocery_list()` |
| Grouped grocery UI | Aisle section headers, collapse/expand, "in pantry" badge | `grocery_list_detail.html`, `style.css` |
| Swipe-to-check | Touch event handling, reveal-behind CSS, accessibility | `app.js`, `style.css` |
| Sort/filter controls | Client-side aisle/recipe toggle, hide-checked filter | `grocery_list_detail.html`, `app.js` |
| "Add to grocery list" from recipe | Button + append/create logic + dropdown picker | `recipe_detail.html`, router, `db.py` |
| Timer detection regex | 5-pattern detector (compound, range, verb, "for X", overnight) | `app.js` |
| Timer trigger rendering | Inline `<button>` wrappers in direction step text | `recipe_detail.html` or JS-side DOM injection |
| Timer floating panel | HTML + CSS + JS, `env(safe-area-inset-bottom)`, collapse/expand | `base.html`, `style.css`, `app.js` |
| Timer countdown engine | setInterval 1s + localStorage end-timestamps + cleanup | `app.js` |
| Timer audio | Web Audio API 880Hz beep, gain scheduling, 60s auto-stop | `app.js` |
| Wake Lock integration | Auto on cooking mode, re-acquire on visibilitychange | `app.js` |
| Notification API | Permission prompt, desktop-only progressive enhancement | `app.js` |
| Step navigation JS | Auto-activate step 1, track current, next/prev, keyboard, boundaries | `app.js` |
| `correct_aisle` MCP tool | Agent-facing aisle correction tool | `mcp_server.py` |

---

## Resolved Questions

- **Scope**: All three feature areas in one sprint.
- **Unit mismatch**: Same-unit summing only — no conversion. Use `string_units=False` for canonical unit matching.
- **Quantity arithmetic**: Fraction objects (exact), not floats. Reuse `scaling.py:format_quantity()` for display.
- **Ingredient normalization**: 7-strategy pipeline on parser's `name` field: strip parens (no-op, parser does it), normalize hyphens, singularize last word, pre-split compounds (exact-match dict), protect fresh/dried identity words, flag garnishes, flag pantry staples. No equivalence mapping. Failure mode = status quo.
- **Aisle assignment**: 13-category hardcoded keyword map (perimeter-first order) + `aisle_overrides` table + pantry category cross-reference. Longest-match-first. "Other" last.
- **Schema**: Migration required — add structured fields to `grocery_list_items`, create `aisle_overrides`. User_version 2 → 3.
- **Duplicate recipes**: Fix multiplicity bug so same recipe scheduled twice produces double quantities. Incorporate `servings_override`.
- **Date-range generation**: Yes, all three entry points (meal plan page, recipe page, MCP tool).
- **Shopping UX**: Swipe-to-check (50px threshold, `touch-action: pan-y`, 20px edge margin), sort by aisle/recipe toggle (client-side), hide checked filter (CSS toggle), pantry pre-check (Paprika style, not removal).
- **Add to grocery list from recipe**: Append to existing if one list, dropdown if multiple, create new if none.
- **Production review**: In-app feedback button (deferred to Linear integration sprint).
- **Timer UI**: Floating collapsible panel, collapsed by default, bottom-right with safe-area insets. Auto-expand on first timer, auto-collapse when all dismissed.
- **Timer state**: localStorage with end-timestamps. 24-hour stale cleanup.
- **Timer persistence**: Survives page nav (global panel) and phone sleep (timestamp-based).
- **Timer sound**: Web Audio API 880Hz beep, 200ms on/200ms off, 60s max then auto-stop. Primary alert on all platforms.
- **Timer detection**: 5-pattern regex (compound, range, verb-context, "for X", overnight). Inline `<button>` triggers with `stopPropagation()`.
- **Notifications**: Desktop-only progressive enhancement. Does NOT work on iOS Safari tabs.
- **Wake Lock**: Automatic on cooking mode entry. Re-acquire on visibilitychange. 96% browser support.
- **Custom timers**: Deferred — only auto-detected from directions this sprint.
- **Service worker**: Skip for now.
- **Step controls**: Auto-activate step 1. Tap + keyboard (arrow keys, spacebar). No-op at boundaries.
- **Step/timer overlap**: Timer triggers are inline buttons with `stopPropagation()`.
- **Step exit**: Clear step position on cooking mode exit (consistent with ingredient strikethrough).
- **Step-ingredient linking**: None — independent interactions.
- **Sort/filter**: Client-side JS, no server round-trips.
- **Mobile**: Desktop + iPad + iPhone. Touch targets 44px, Wake Lock, swipe-to-check, safe-area insets.

## Open Questions

None — all key decisions resolved. Ready for `/ce:plan`.

---

## Research Insights (from deepening)

### Browser API Reality Check (2025-2026)

| API | Desktop Chrome/FF/Edge | iOS Safari (tab) | iOS Safari (PWA) |
|-----|----------------------|-------------------|-------------------|
| Web Audio API | Full | Full (muted by ringer switch) | Full |
| Wake Lock API | Full | Full (16.4+) | Full (fixed in 18.4) |
| Notification API | Full | **No** | Yes (16.4+) |
| visibilitychange | Full | Full | Full |
| localStorage | Full | Full | Full |
| touch-action: pan-y | Full | Full (13+, 97.3% global) | Full |

### Key Implementation Patterns Discovered

1. **Swipe: `touch-action: pan-y` replaces `preventDefault()`** — CSS handles scroll/swipe disambiguation at engine level. All touch listeners can be `{ passive: true }`. No need for `preventDefault()` which requires `{ passive: false }` and hurts scroll performance.

2. **Timer: gain scheduling > start/stop cycling** — Schedule the full beep pattern (200ms on, 200ms off × 60 cycles) as gain values on a single `OscillatorNode`. Avoids creating/destroying oscillators and gives a clean beep pattern.

3. **Timer: `AudioContext` must be created on user gesture** — Create it on the "Start Timer" button click to satisfy browser autoplay policy. Reuse the same context for all timers.

4. **Floating panel: `60svh` max-height** — `svh` (small viewport height) excludes mobile browser chrome, preventing the panel from being hidden behind the URL bar.

5. **Aisle map: longest-match-first** — Sort keywords by length descending and substring-match. "coconut milk" matches Canned & Jarred before "milk" matches Dairy.

6. **Aggregation: preserve Fraction objects** — `1/3 + 2/3 = 1` exactly. Current code converts to float too early. Need a parallel parser path with `string_units=False` that returns Fractions and canonical units.

7. **Paprika-style pantry pre-check** — Don't remove matched items. Add them as `is_checked=True` with a badge. Users can uncheck if running low. Better UX than silent removal.

8. **Singularize only the last word** — "green onions" → "green onion". Modifier words stay unchanged.

### Ingredient Normalization: What Other Apps Do

- **Paprika 3**: Normalize name via lowercasing, merge items with identical names and compatible units. Same-unit items summed, different-unit items concatenated with "+". No fuzzy matching.
- **Whisk**: Two-layer architecture — individual items plus a `combined_items` array for dedup. Preserves recipe lineage while presenting merged view.
- **Mealime**: "Intelligent ingredient bundling" — rounds up fractional whole items (two recipes need half an onion → list one onion).
- **Plan to Eat**: Manual "merge" feature where users select items to combine. Acknowledges automated merging is hard.
- **Tandoor**: Drag-and-drop aisle categorization that persists globally. Users build their own mapping over time.

---

## Research Sources

- [Paprika User Guide for iOS](https://www.paprikaapp.com/help/ios/)
- [Paprika App Review: Pros and Cons - Plan to Eat](https://www.plantoeat.com/blog/2023/07/paprika-app-review-pros-and-cons/)
- [Using Paprika 3 for menu planning and grocery shopping](https://www.sarahdarkmagic.com/content/using-paprika-3-menu-planning-and-grocery-shopping)
- [Best Grocery List Apps 2026 - NerdWallet](https://www.nerdwallet.com/finance/learn/best-grocery-list-apps)
- [Paprika complaints and customer claims](https://www.complaintsboard.com/paprika-recipe-manager-3-b149019)
- [Touch Events - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Touch_events)
- [touch-action: pan-y - Can I Use](https://caniuse.com/mdn-css_properties_touch-action_pan-y)
- [WCAG 2.5.1 Pointer Gestures](https://www.w3.org/WAI/WCAG22/Understanding/pointer-gestures.html)
- [Blocking Navigation Gestures on iOS - PQINA](https://pqina.nl/blog/blocking-navigation-gestures-on-ios-13-4/)
- [Web Audio API Best Practices - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices)
- [Screen Wake Lock API - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)
- [Wake Lock browser support - Can I Use](https://caniuse.com/wake-lock)
- [Notification API - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Notification)
- [Page Visibility API - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)
- [Instacart: 17 Grocery List Categories](https://www.instacart.com/company/ideas/grocery-list-categories)
- [GroceryGenius (open source)](https://github.com/DanielRendox/GroceryGenius)
- [Tandoor Shopping Documentation](https://docs.tandoor.dev/features/shopping/)
- [Whisk Shopping List API](https://docs.whisk.com/api/shopping-lists)
- [ingredient-parser-nlp on PyPI](https://pypi.org/project/ingredient-parser-nlp/)
- [Python fractions module](https://docs.python.org/3/library/fractions.html)
- [env() Safe Area Insets - CSS Tricks](https://css-tricks.com/almanac/functions/e/env/)
