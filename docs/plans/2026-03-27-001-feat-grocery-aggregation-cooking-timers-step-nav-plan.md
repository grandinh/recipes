---
title: "feat: Grocery Aggregation + Cooking Timers + Step Navigation"
type: feat
status: completed
date: 2026-03-27
deepened: 2026-03-27
origin: docs/brainstorms/2026-03-26-001-feat-grocery-cooking-ux-brainstorm.md
---

# feat: Grocery Aggregation + Cooking Timers + Step Navigation

## Enhancement Summary

**Deepened on:** 2026-03-27
**Sections enhanced:** All
**Agents used:** kieran-python-reviewer, performance-oracle, security-sentinel, architecture-strategist, julik-frontend-races-reviewer, data-migration-expert, data-integrity-guardian, pattern-recognition-specialist, agent-native-reviewer, code-simplicity-reviewer, best-practices-researcher, framework-docs-researcher, frontend-design-skill, agent-native-architecture-skill

### Key Changes from Deepening
1. **CRITICAL: Timer detection moved to client-side JS** -- Server-side HTML injection via regex creates XSS vector when combined with `|safe` filter. Client-side `document.createElement('button')` eliminates the trust boundary entirely.
2. **CRITICAL: Aggregation pipeline must use `asyncio.to_thread()`** -- NLP parsing is CPU-bound (~0.3-0.5ms/ingredient). 300 ingredients blocks the event loop for 100-150ms. Follow `pantry_matcher.py` pattern.
3. **CRITICAL: SQLite ALTER TABLE silently ignores FK constraints** -- `ON DELETE SET NULL` on `recipe_id` won't work via ALTER TABLE. Must enforce at application layer.
4. **Scope reduced for MVP** -- Deferred: swipe-to-check, Wake Lock, Notifications, aisle_overrides table, pantry pre-check, date-range pickers, normalization strategies 4-7. Ship working basics first, layer polish later.
5. **Missing MCP tool identified** -- `add_recipe_to_grocery_list` must be added for agent parity with the new web UI button.
6. **8 frontend race conditions identified** -- Zombie setInterval, ghost cooking mode across recipes, AudioContext GC, double beep stacking, localStorage read-modify-write across tabs. All have specific fixes.
7. **Transaction safety required** -- `generate_grocery_list()` must use `BEGIN IMMEDIATE` with rollback, not rely on implicit transactions.
8. **Parameterize parser instead of duplicating** -- Add `preserve_fractions: bool = False` parameter to existing `parse_ingredient()` instead of creating a parallel function.

### New Considerations Discovered
- `ingredient-parser-nlp` returns `ParsedIngredient` dataclass (not dict); `quantity` is always `Fraction` regardless of `string_units`
- SQLite ALTER TABLE with REFERENCES + ON DELETE SET NULL actually works (confirmed empirically) but only if `PRAGMA foreign_keys = ON` is set on the connection
- `format_quantity()` should accept `Fraction` directly to avoid float round-trip precision loss
- `_KNOWN_TABLES` in `db.py` must be updated with `"aisle_overrides"` or `_column_exists()` will raise `ValueError`
- MCP `connect()` does not run migrations -- if MCP starts before web server, new columns won't exist
- Per-timer localStorage keys (not a shared JSON array) prevent cross-tab read-modify-write races
- `aisle_map.py` must be a pure-function module (no DB access) to match codebase patterns; override lookup stays in `db.py`
- All new JS must use `var`/`function` (ES5 style) to match existing `app.js` conventions

---

## Overview

Three feature areas that transform the app from "recipe database" to "daily cooking companion":

1. **Smart grocery aggregation + shopping UX** -- Sum duplicate ingredient quantities (Fraction arithmetic, same-unit only), group by store aisle (13 categories), fix recipe multiplicity bug, sort/filter controls.
2. **Cooking timers** -- Auto-detect time references in directions (client-side), render as tappable timer triggers, manage multiple simultaneous countdown timers in a floating panel with Web Audio alerts.
3. **Step-by-step direction navigation** -- Highlight current step, keyboard/tap navigation, persist position in localStorage.

(see brainstorm: `docs/brainstorms/2026-03-26-001-feat-grocery-cooking-ux-brainstorm.md`)

## Problem Statement / Motivation

The backend plumbing largely exists -- ingredient parser returns structured `{qty, unit, name}` data, cooking mode CSS has `.active-step` styles, and grocery list CRUD is complete. But:
- Grocery generation concatenates duplicates with `" + "` instead of summing quantities
- `WHERE id IN (...)` deduplicates recipe IDs (same recipe on Monday + Wednesday = single quantities)
- No aisle grouping, no sort/filter, no mobile shopping UX
- No cooking timers or step navigation despite template/CSS scaffolding being in place
- The grocery list detail page has a CSP-violating inline `onchange` handler (broken in production)
- Existing `add_grocery_item()` in `db.py:958` has no sanitization (pre-existing bug)

---

## Technical Approach

### Phase 1: Schema Migration + Aggregation Engine

#### 1a. Schema Migration (v2 -> v3)

Add `if version < 3:` block in `db.py:run_migrations()`, following existing pattern (`_column_exists()` for idempotency). **Create DB backup before migration** (matching v0->v1 pattern).

```sql
-- grocery_list_items: add structured fields for shopping UX
ALTER TABLE grocery_list_items ADD COLUMN aisle TEXT DEFAULT 'Other';
ALTER TABLE grocery_list_items ADD COLUMN recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL;
ALTER TABLE grocery_list_items ADD COLUMN normalized_name TEXT;

-- aisle_overrides: self-healing aisle assignments (deferred to future sprint)
-- CREATE TABLE IF NOT EXISTS aisle_overrides (...)

-- Index for "already added" check and recipe joins
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_recipe
    ON grocery_list_items(grocery_list_id, recipe_id);

PRAGMA user_version = 3;
```

**Key decisions:**
- `recipe_id` is nullable (manual items have no recipe)
- **FK enforcement is application-layer only.** SQLite ALTER TABLE silently ignores FK constraint clauses. The `REFERENCES recipes(id) ON DELETE SET NULL` is parsed but not stored. Must explicitly `UPDATE grocery_list_items SET recipe_id = NULL WHERE recipe_id = ?` when deleting a recipe.
- All new columns have defaults, so existing rows are safe
- `is_optional` and `is_pantry_staple` columns **deferred** -- strategies 6-7 are deferred to reduce scope
- Update `_KNOWN_TABLES` to include `"aisle_overrides"` for future use
- Update `schema.sql` for fresh installs but keep `PRAGMA user_version = 2` in schema.sql until migration is confirmed safe (migrations own the version bump)
- **MCP `connect()` must also call `run_migrations()`** -- currently only `init_schema()` runs

**Transaction safety:** All INSERTs in `generate_grocery_list()` wrapped in explicit `BEGIN IMMEDIATE` / `COMMIT` with rollback on error (matching `create_recipe()` pattern at `db.py:367`).

**Files:** `src/recipe_app/sql/schema.sql`, `src/recipe_app/db.py` (migration block + `_KNOWN_TABLES` update + `connect()` fix)

#### 1b. Ingredient Normalization Pipeline (MVP: 3 strategies)

New module: `src/recipe_app/normalizer.py`

**Failure mode: "too many items" (status quo), never "wrong quantities."** Ship 3 strategies now, add more when real duplicates are observed.

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class NormalizedResult:
    name: str
    original_name: str

def normalize_ingredient_name(name: str) -> NormalizedResult:
    """Apply normalization strategies to an ingredient name."""

def singularize(word: str) -> str:
    """Singularize the last word of a name. Separately testable."""
```

Three MVP strategies:
1. **Strip parentheticals** -- `re.sub(r'\([^)]*\)', '', name).strip()` safety net
2. **Normalize hyphens** -- `name.replace('-', ' ')` ("extra-virgin olive oil" = "extra virgin olive oil")
3. **Singularize last word** -- Rule-based with exception set: `{asparagus, citrus, couscous, hibiscus, hummus, octopus, bass, grass, harissa, swiss, anise, hollandaise, bearnaise, mayonnaise, molasses, grits, oats, brussels}`

**Deferred to future sprints:**
- Strategy 4: compound line splitting (~10 patterns)
- Strategy 5: identity word protection (no-op by design)
- Strategy 6: optional/garnish flagging
- Strategy 7: pantry staple flagging

**Design notes (from Python reviewer):**
- Returns frozen dataclass, not dict -- encodes the contract in a type
- `singularize()` extracted as its own function with its own tests
- Plain functions, not a class (no state between calls)

**Files:** New `src/recipe_app/normalizer.py` (~50 lines)

#### 1c. Aisle Keyword Map (MVP: ~100 keywords)

New module: `src/recipe_app/aisle_map.py` -- **pure function module, no DB access** (matching `scaling.py` pattern).

13 categories with ~8-10 keywords each (~100 total). "Other" catches everything else. Expand based on real grocery lists.

```python
def assign_aisle(normalized_name: str) -> tuple[str, int]:
    """Return (aisle_name, sort_order). Pure function, no DB."""
```

| Sort | Category | Example keywords |
|------|----------|-----------------|
| 1 | Produce | lettuce, tomato, onion, apple, banana, carrot, potato, celery, garlic, spinach |
| 2 | Fresh Herbs | basil, cilantro, parsley, thyme, rosemary, dill, mint, chive |
| 5 | Dairy & Eggs | milk, cheese, butter, yogurt, cream, egg, sour cream |
| 6 | Meat & Seafood | chicken, beef, pork, salmon, shrimp, turkey, lamb, bacon |
| 7 | Canned & Jarred | canned, coconut milk, tomato paste, broth, stock, beans |
| 8 | Pasta, Rice & Grains | pasta, spaghetti, rice, quinoa, noodle, couscous, oat |
| 9 | Baking | flour, sugar, baking powder, baking soda, vanilla, cocoa |
| 10 | Condiments & Sauces | soy sauce, mustard, ketchup, vinegar, hot sauce, mayo |
| 11 | Spices & Seasonings | cumin, paprika, oregano, cinnamon, pepper, chili, turmeric |
| 99 | Other | (fallback) |

Matching: sort keywords by descending length, substring match. "coconut milk" matches Canned before "milk" matches Dairy.

**Keyword data as module-level dict constant** (not loaded from file). ~80 lines total.

**Deferred:** `aisle_overrides` table and override priority chain. The keyword map with "Other" fallback is sufficient for v1.

**Files:** New `src/recipe_app/aisle_map.py` (~80 lines)

#### 1d. Parameterize Existing Parser (not duplicate)

Add a `preserve_fractions` parameter to `parse_ingredient()` in `ingredient_parser.py`:

```python
def parse_ingredient(
    text: str,
    *,
    preserve_fractions: bool = False,
) -> dict:
```

When `preserve_fractions=True`: skip `_fraction_to_float()` conversion, pass `string_units=False` to library for canonical unit matching. Returns `quantity` as `Fraction` and `unit` as `str(pint.Unit)`.

**Also update `format_quantity()`** in `scaling.py` to accept `Fraction` directly:

```python
def format_quantity(value: float | Fraction) -> str:
    if isinstance(value, Fraction):
        frac = value.limit_denominator(8)
    else:
        frac = Fraction(value).limit_denominator(8)
```

**Library note:** `ingredient-parser-nlp` v2.6.0 returns `ParsedIngredient` dataclass. `quantity` is always `Fraction` when numeric, regardless of `string_units`. Add defensive `isinstance(qty, Fraction)` assertion in the aggregation path.

**Files:** `src/recipe_app/ingredient_parser.py`, `src/recipe_app/scaling.py`

#### 1e. Rewrite `generate_grocery_list()` in `db.py`

**Architecture: extract pure aggregation logic** into a sync function, call via `asyncio.to_thread()`.

```python
# Pure CPU-bound function (sync, no DB, no async)
def _aggregate_ingredients(
    raw_ingredients: list[tuple[str, int, int | None]],  # (text, recipe_id, servings_override)
) -> list[AggregatedItem]:
    """Parse, normalize, classify, and aggregate. Testable without DB."""

# In generate_grocery_list():
async def generate_grocery_list(db, name, meal_plan_id, recipe_ids, ...):
    # 1. Fetch data (async, on event loop)
    ingredients_data = await _fetch_ingredients(db, meal_plan_id, recipe_ids)

    # 2. CPU-bound aggregation (off event loop)
    aggregated = await asyncio.to_thread(_aggregate_ingredients, ingredients_data)

    # 3. DB writes (async, inside write lock + explicit transaction)
    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")
            # ... INSERT list + items ...
            await db.commit()
        except Exception:
            await db.rollback()
            raise
```

**Pre-load lookups before aggregation** (avoid N+1):
- Aisle overrides: N/A (deferred)
- Pantry items: N/A (deferred)

**Fix recipe multiplicity bug:** Replace `WHERE id IN (...)` with JOIN that preserves duplicates. Incorporate `servings_override` from `meal_plan_entries`.

**Aggregation key:** `(normalized_name, canonical_unit)`. For `quantity=None` items, use `(normalized_name, None)` -- never merge with quantified items.

**Edge cases:**
- Items with `quantity=None` ("salt to taste"): store with no quantity, don't aggregate
- Same name + different units: separate line items (no unit conversion)
- Empty meal plan: create empty grocery list with message, not error
- Use **LEFT JOIN** to recipes for grocery items (not INNER JOIN) -- handles deleted recipes and manual items

**Sanitization:** `sanitize_field()` on all text fields (`text`, `normalized_name`, `aisle`) at the DB write layer. Never use `sanitize(x) or x`.

**Files:** `src/recipe_app/db.py`

#### 1f. Update Models

```python
from datetime import date

class GroceryListGenerate(BaseModel):
    meal_plan_id: int | None = None
    recipe_ids: list[int] | None = None
    name: str | None = None
    date_start: date | None = None  # Not str — Pydantic handles parsing
    date_end: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (self.date_start is None) != (self.date_end is None):
            raise ValueError("date_start and date_end must both be provided or both omitted")
        if self.date_start and self.date_end and self.date_start > self.date_end:
            raise ValueError("date_start must be <= date_end")
        return self
```

Create `GroceryItemResponse` model (does not exist yet):

```python
class GroceryItemResponse(BaseModel):
    id: int
    grocery_list_id: int
    text: str
    is_checked: bool
    sort_order: int
    aisle: str = "Other"
    recipe_id: int | None = None
    normalized_name: str | None = None
```

**Files:** `src/recipe_app/meal_plan_models.py`

---

### Phase 2: Shopping UX

#### 2a. Fix CSP-Violating Inline Handlers

**Pre-existing bug:** `grocery_list_detail.html:40` has `onchange="this.form.requestSubmit()"` and `pantry_matches.html:22` has `onchange="this.form.submit()"`. Both violate `script-src 'self'` CSP policy.

Fix: Delegated event listener on `document` (bound once, survives HTMX swaps):

```javascript
// Bound once in initAll(), guarded with static flag
if (!_groceryCheckboxDelegated) {
    _groceryCheckboxDelegated = true;
    document.addEventListener('change', function(e) {
        var checkbox = e.target;
        if (checkbox.type !== 'checkbox') return;
        var form = checkbox.closest('form');
        if (!form) return;
        if (form.closest('.grocery-item') || form.closest('.filter-row')) {
            form.requestSubmit();
        }
    });
}
```

**Also fix:** Add `sanitize_field()` to existing `add_grocery_item()` in `db.py:958` (pre-existing sanitization gap).

**Files:** `static/app.js`, `src/recipe_app/templates/grocery_list_detail.html`, `src/recipe_app/templates/pantry_matches.html`, `src/recipe_app/db.py`

#### 2b. Grouped Grocery List UI

Rebuild `grocery_list_detail.html`:

- Group items by aisle using native `<details>` elements (zero-JS collapse, accessible by default)
- Aisle headers: bold compact text with item count badge, sorted by aisle sort order
- Items show: quantity, unit, name, recipe source badge (via LEFT JOIN to recipes)
- `hx-sync="this:replace"` on `#items-list` container (rapid check-off safety)
- Per-item `hx-target` for check/uncheck (individual swap, not full list re-render)
- Update aisle section counts **client-side** after item check (don't re-render section from server)

**Design (from frontend-design review):**
- Aisle headers: `font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em` with accent band
- Item padding: at least `0.75rem 1rem` on mobile for 48px touch targets
- Checked item flash: brief 150ms green-tint `@keyframes` before fading to muted state

**Files:** `src/recipe_app/templates/grocery_list_detail.html`, `static/style.css`

#### 2c. Swipe-to-Check -- DEFERRED

Checkbox already works after the CSP fix. Swipe-to-check adds 60-80 lines of touch event handling with iOS gesture conflicts. Defer until the user reports checkbox as inadequate on mobile.

#### 2d. Sort/Filter Controls

Client-side JavaScript, no server round-trips:

- **Sort: aisle only** (default, natural grocery store order). Recipe-sort toggle deferred.
- **Filter: hide checked** -- CSS class toggle on container. Hide checked items, update remaining count ("3 of 12 remaining"), collapse empty aisle sections.
- Controls: sticky bar below navbar (`position: sticky; top: 52px; z-index: 99`), `font-size: 0.8rem`
- Re-apply sort/filter state in `htmx:afterSettle` handler when items container is swapped
- Batch DOM updates using `DocumentFragment` (prevents layout thrashing on mobile)

**Files:** `static/app.js`, `src/recipe_app/templates/grocery_list_detail.html`, `static/style.css`

#### 2e. "Add to Grocery List" from Recipe Page -- SIMPLIFIED

Simple button that always creates a new grocery list named after the recipe. One code path, one behavior.

Route: `POST /recipes/{recipe_id}/add-to-grocery-list` -- creates new list, runs normalization + aisle assignment on recipe's ingredients, returns redirect (or HTMX partial).

Dropdown/append/already-added logic **deferred**. If user complains about too many lists, add the picker.

**TOCTOU guard:** The "already added" check (deferred) must happen inside the write lock and transaction when implemented.

**Files:** `src/recipe_app/templates/recipe_detail.html`, `src/recipe_app/main.py`, `src/recipe_app/db.py`

#### 2f. Date-Range Grocery Generation -- DEFERRED

The multiplicity bug fix (JOIN instead of WHERE IN) is the core improvement. Date-range pickers add template complexity. Ship the fix without date pickers; the MCP tool gets date params for agent workflows.

---

### Phase 3: Cooking Timers

#### 3a. Timer Detection -- CLIENT-SIDE JS (security requirement)

**CRITICAL CHANGE:** Timer detection moved from server-side Jinja2 to client-side JavaScript to eliminate XSS vector.

Server-side regex injection wraps user-controlled recipe text in `<button>` HTML, requiring `|safe` in the template. If the matched text contains quotes, it can break out of `data-label` attributes. Client-side detection using `document.createElement('button')` and `textContent` eliminates the trust boundary entirely.

**Two MVP patterns** (start simple, add more later):
1. **Standalone:** `for X minutes/hours` -- the "for" anchor prevents false positives
2. **Compound:** `N hour(s) N minute(s)`, `NhNm`

Regex compiled once at module scope. Detection runs on each `.direction-step` element's `textContent`. Matched text wrapped with `document.createElement('button')` + `textContent` (never `innerHTML`).

**Validation:** Reject times <= 0 or > 24 hours.

**Deferred patterns:** verb-context (complex, most false-positive-prone), range, "overnight".

**Files:** `static/app.js` (timer detection in `initTimerTriggers()`)

#### 3b. Floating Timer Panel

Global panel in `base.html`, outside HTMX swap targets:

```html
<div id="timer-panel" class="timer-panel" style="display:none"
     aria-label="Cooking timers" role="region">
  <button class="timer-panel-toggle" aria-expanded="false">
    <span class="timer-count">0</span> timers
  </button>
  <div class="timer-list"></div>
</div>
```

**Design (from frontend-design review):**
- `position: fixed; bottom: calc(1rem + env(safe-area-inset-bottom, 0)); right: 1rem; z-index: 200`
- `max-height: 60svh; min-width: 280px; max-width: 360px`
- Collapsed state: compact pill with timer count (`border-radius: 99px`)
- Expanded: card surface with `box-shadow: 0 4px 20px rgba(44, 36, 32, 0.15)`
- Countdown digits: `font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums` (prevents width jitter)
- Expired: "DONE" in `var(--color-danger)` with pulsing CSS animation
- Mobile (<600px): full-width `left: 0.5rem; right: 0.5rem`
- `display: none` when no timers exist, materializes on first timer

**Files:** `src/recipe_app/templates/base.html`, `static/style.css`

#### 3c. Timer Countdown Engine

**Per-timer localStorage keys** (not a shared JSON array) -- prevents cross-tab read-modify-write races.

```
localStorage key: "timer-{uuid}"
value: JSON { id, name, endTime, originalSeconds, recipeId, fired, createdAt }
```

**Module-level state (declared once, never re-declared):**
```javascript
var _timerIntervalId = null;   // Single setInterval ID
var _timers = [];              // In-memory array (NOT read from localStorage each tick)
var _audioCtx = null;          // AudioContext (created on user gesture)
var _isBeeping = false;        // Prevent double-beep on simultaneous expiry
```

**Guard against zombie intervals** (CRITICAL race condition fix):
```javascript
function _ensureTimerTick() {
    if (_timerIntervalId !== null) return;
    _timerIntervalId = setInterval(_tickAllTimers, 1000);
}
function _stopTimerTick() {
    if (_timerIntervalId === null) return;
    clearInterval(_timerIntervalId);
    _timerIntervalId = null;
}
```

- Timer tick reads from in-memory `_timers` array, NOT `localStorage.getItem()` each tick
- Sync to localStorage only on mutation (start, dismiss, expire, cleanup)
- Startup hydration: on `DOMContentLoaded`, scan localStorage for `timer-*` keys, populate `_timers`, rebuild panel, fire alerts for already-expired
- 24-hour stale cleanup on every hydration
- `visibilitychange` catch-up: recalculate all timers, fire alarms for expired, re-acquire Wake Lock
- **Multiple simultaneous expiry:** collect all newly-expired in one tick, fire single beep sequence (use `_isBeeping` flag to prevent re-entry)
- **localStorage error handling:** try/catch around all `setItem` calls
- **Timer panel init**: runs once on `DOMContentLoaded` only (panel is outside `<main>`, never replaced by HTMX). Timer trigger button bindings use document-level event delegation.
- **Validate on hydration:** reject timer objects where `endTime` is not a positive integer or `originalSeconds` is not between 1 and 86400

**Files:** `static/app.js`

#### 3d. Web Audio Alert

- Store `AudioContext` in module-level `_audioCtx` variable (prevents GC during navigation)
- Create on first timer start button click (satisfies autoplay policy)
- Check `.state` before use: if `'closed'`, create new; if `'suspended'`, call `.resume()` (returns Promise -- schedule beep in `.then()`)
- 880Hz sine wave, gain scheduling: 200ms on / 200ms off pattern
- Max 60 seconds, then auto-stop but leave visual "DONE" pulsing indicator
- Fallback: if Web Audio unavailable, visual-only alert
- All dynamic DOM content in timer panel inserted via `textContent`, never `innerHTML`

**Files:** `static/app.js`

#### 3e. Wake Lock API -- DEFERRED

Most users won't notice screen dimming during a 25-minute timer. If reported as a problem, it's a 15-line addition. Defer.

#### 3f. Desktop Notifications -- DEFERRED

Web Audio beep already handles the alert. Notifications are progressive enhancement on top of progressive enhancement. Defer.

---

### Phase 4: Step-by-Step Navigation

#### 4a. Step Navigation JS

Extend existing `initCookingMode()` in `static/app.js`:

- **Auto-activate step 1** on cooking mode entry
- **Click/tap** any step to select it (event delegation on `document`, guarded with static flag)
- **Keyboard:** Arrow up/down to navigate, spacebar to advance
- **Boundaries:** No-op at first/last step (no wrap-around)
- **Visual:** Active step gets `.active-step` CSS. Completed steps get `.completed-step` (50% opacity, gray left-border). Auto-scroll with `scrollIntoView({ behavior: 'smooth', block: 'nearest' })`. Add `scroll-margin-top` equal to navbar height to avoid scrolling behind sticky elements.
- **Timer trigger overlap:** Timer buttons use `event.stopPropagation()`
- **Transition:** `transition: opacity 200ms ease, background 200ms ease` on `.direction-step`
- **Step state also restored after scaling section swap** (add `_restoreStepState()` alongside `_restoreCookingState()`)

**Ghost cooking mode fix (CRITICAL):** On `htmx:afterSettle`, detect if recipe ID changed and reset cooking mode:
```javascript
var newBtn = document.getElementById('cookingModeBtn');
var newRecipeId = newBtn ? newBtn.dataset.recipeId : null;
if (_cookingState.active && newRecipeId !== _cookingState.recipeId) {
    _cookingState.active = false;
    document.body.classList.remove('cooking-mode');
}
```

**Files:** `static/app.js`

#### 4b. Step State Persistence

- localStorage key: `cooking-{recipeId}-step` (recipe-scoped)
- Restore on cooking mode entry, clear on exit
- `_restoreStepState()` is idempotent, called from both `initCookingMode()` and scaling swap handler

**Files:** `static/app.js`

#### 4c. Completed Step Styling

```css
.direction-step {
    transition: opacity 200ms ease, background 200ms ease;
}
.direction-step.completed-step {
    opacity: 0.5;
    border-left: 3px solid var(--color-border);
    padding-left: 8px;
    cursor: pointer;
}
.direction-step.completed-step:hover {
    opacity: 0.75;
}
```

**Files:** `static/style.css`

---

### Phase 5: MCP + API Updates

#### 5a. Update `generate_grocery_list` MCP Tool

Add `date_start` and `date_end` optional params. No changes to call path needed -- tool already delegates to `db.generate_grocery_list()` which is being rewritten in Phase 1e.

Return **structured data** with aisle grouping:
```python
return {
    "list_id": 42,
    "name": "Weekly Shopping",
    "items": [{"text": "5 eggs", "aisle": "Dairy & Eggs", "is_checked": False, ...}],
    "aisle_summary": {"Produce": 8, "Dairy & Eggs": 3},
    "total_items": 23,
}
```

**Files:** `src/recipe_app/mcp_server.py`

#### 5b. New `add_recipe_to_grocery_list` MCP Tool (PARITY FIX)

```python
@mcp.tool
async def add_recipe_to_grocery_list(
    recipe_id: int,
    list_id: int | None = None,
) -> dict:
    """Add a recipe's ingredients (normalized, with aisle assignments) to a grocery list.
    If list_id is None, creates a new list named after the recipe."""
```

Uses same `db.add_recipe_to_grocery_list()` as the web route.

**Files:** `src/recipe_app/mcp_server.py`

#### 5c. `correct_aisle` MCP Tool -- DEFERRED

Deferred along with `aisle_overrides` table. Will be added when the override table ships.

#### 5d. Update API Routes

- `POST /api/grocery-lists/generate` -- accept `date_start`, `date_end`
- `GET /api/grocery-lists/{list_id}` -- return structured item data with aisle grouping

**Files:** `src/recipe_app/routers/meal_plans.py`

---

## System-Wide Impact

### Interaction Graph

- `generate_grocery_list()` -> `asyncio.to_thread(_aggregate_ingredients)` -> `parse_ingredient(preserve_fractions=True)` -> `normalize_ingredient_name()` -> `assign_aisle()` -> `Fraction` summing -> `format_quantity()` -> DB insert (inside `BEGIN IMMEDIATE`)
- Timer detection runs **client-side** in `app.js` on `.direction-step` text content (no server-side HTML injection)
- Timer panel in `base.html` is outside all HTMX swap targets -- persists across navigation
- Application-layer FK enforcement: recipe deletion must SET NULL on `grocery_list_items.recipe_id`

### Error Propagation

- Ingredient parse failure: fall back to raw text as item (status quo behavior)
- Normalization failure: fall back to unnormalized name (more items, never wrong quantities)
- Aisle assignment failure: default to "Other"
- Timer localStorage failure: timers work in-memory for current session only
- Web Audio failure: visual-only alert (pulsing "DONE" CSS animation)
- AudioContext suspended: `.resume()` before scheduling beep
- Transaction failure: `BEGIN IMMEDIATE` + rollback prevents partial grocery list inserts

### State Lifecycle Risks

- Schema migration: `ALTER TABLE ADD COLUMN` with defaults is safe for existing rows. **Backup before migration.**
- Timer localStorage: 24-hour cleanup prevents unbounded growth; try/catch on writes; per-timer keys prevent cross-tab races
- Cooking mode ghost state: explicit reset on recipe navigation (check recipeId change in afterSettle)
- Zombie setInterval: module-level `_timerIntervalId` with guard prevents duplicate intervals

### API Surface Parity

| Feature | Web UI | API | MCP |
|---------|--------|-----|-----|
| Grocery generation (new pipeline) | Yes | Yes | Yes (updated, structured return) |
| Date-range grocery generation | Deferred UI | Yes | Yes (new params) |
| Add recipe to grocery list | Yes | Yes | Yes (`add_recipe_to_grocery_list`) |
| Aisle override | Deferred | Deferred | Deferred |
| Timers | Yes (client-side) | N/A | N/A (client-only) |
| Step navigation | Yes (client-side) | N/A | N/A (client-only) |

---

## Acceptance Criteria

### Feature 1: Grocery Aggregation + Shopping UX

- [x] Schema migrates cleanly from v2 to v3 (idempotent, existing data preserved, backup created)
- [x] "2 eggs" + "3 eggs" from different recipes = "5 eggs" on grocery list (Fraction arithmetic)
- [x] Same recipe scheduled Monday + Wednesday = double quantities (multiplicity bug fixed)
- [x] `servings_override` from meal plan entries is respected in aggregation
- [x] "1 cup flour" + "200g flour" = two separate line items (no cross-unit conversion)
- [x] "salt to taste" + "1 tsp salt" = two separate items (quantified vs. unquantified)
- [x] Items grouped by aisle sections (13 categories + Other)
- [x] "coconut milk" -> Canned & Jarred (longest-match-first, not Dairy)
- [x] Desktop checkbox works (CSP fix applied)
- [x] "Hide checked" filter hides checked items and collapses empty sections (client-side)
- [x] "Add to grocery list" button on recipe detail creates new list with normalized items
- [x] CSP-violating inline `onchange` handlers removed and replaced with delegated listeners
- [x] All grocery item writes go through `sanitize_field()` (including pre-existing `add_grocery_item`)
- [x] Aggregation pipeline runs via `asyncio.to_thread()` (doesn't block event loop)
- [x] Recipe deletion sets `grocery_list_items.recipe_id` to NULL (application-layer FK)
- [x] Grocery list items use LEFT JOIN to recipes (handles NULL recipe_id)
- [x] MCP `generate_grocery_list` returns structured data with aisle grouping
- [x] MCP `add_recipe_to_grocery_list` tool works for agent parity

### Feature 2: Cooking Timers

- [x] Time references in directions rendered as tappable timer buttons (client-side detection)
- [x] "bake for 25 minutes" -> timer button; "350 degrees" -> no timer button
- [x] "1 hour 30 minutes" compound pattern detected
- [x] Floating timer panel appears when first timer starts
- [x] Timer countdown displays correctly (no drift, survives phone sleep)
- [x] Web Audio beep plays on timer expiry (880Hz, 200ms on/off, 60s max)
- [x] Timer state persists across HTMX page navigation (per-timer localStorage keys)
- [x] Expired timers caught up on tab return (visibilitychange)
- [x] 24-hour stale timer cleanup on every page load
- [x] Timer panel has `aria-live` region, keyboard-accessible dismiss
- [x] AudioContext stored in module-level variable (not garbage collected)
- [x] Single setInterval guarded against zombie duplication
- [x] Multiple simultaneous timer expiry plays one beep (not stacked)
- [x] Timer labels inserted via `textContent`, never `innerHTML`
- [x] Timer data validated on localStorage hydration

### Feature 3: Step Navigation

- [x] Step 1 auto-activated on cooking mode entry
- [x] Click any step to select it; arrow keys + spacebar for navigation
- [x] No-op at first/last step boundaries
- [x] Active step has orange tint + left border; completed steps dimmed with gray left-border
- [x] Active step scrolls into view smoothly (with `scroll-margin-top` for sticky elements)
- [x] Timer button click inside a step does NOT change the active step
- [x] Step position persisted in localStorage, cleared on cooking mode exit
- [x] Step position is recipe-scoped (ghost cooking mode fixed on recipe navigation)
- [x] Step state restored after scaling section swap

---

## New Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `src/recipe_app/normalizer.py` | 3-strategy ingredient name normalization + singularizer (frozen dataclass return) | ~50 |
| `src/recipe_app/aisle_map.py` | 13-category keyword map (~100 keywords) + pure assignment function | ~80 |

## Modified Files

| File | Changes |
|------|---------|
| `src/recipe_app/sql/schema.sql` | Add columns to `grocery_list_items`, add index, keep user_version=2 |
| `src/recipe_app/db.py` | Migration v3 block, rewrite `generate_grocery_list()` with `asyncio.to_thread` + `BEGIN IMMEDIATE`, add `add_recipe_to_grocery_list()`, fix `add_grocery_item()` sanitization, update `_KNOWN_TABLES`, add recipe deletion FK cleanup, fix `connect()` to run migrations |
| `src/recipe_app/ingredient_parser.py` | Add `preserve_fractions` parameter to `parse_ingredient()` |
| `src/recipe_app/scaling.py` | Widen `format_quantity()` to accept `Fraction` directly |
| `src/recipe_app/meal_plan_models.py` | Add `date_start`/`date_end` (as `datetime.date`) with validator, create `GroceryItemResponse` |
| `src/recipe_app/main.py` | "Add to grocery list" route, recipe deletion FK cleanup |
| `src/recipe_app/routers/meal_plans.py` | Update API grocery generation to accept date range |
| `src/recipe_app/mcp_server.py` | Update `generate_grocery_list` params + structured return, add `add_recipe_to_grocery_list` tool |
| `src/recipe_app/templates/grocery_list_detail.html` | Aisle groups with `<details>`, sort/filter controls, remove inline handlers |
| `src/recipe_app/templates/recipe_detail.html` | "Add to grocery list" button |
| `src/recipe_app/templates/base.html` | Global timer panel HTML |
| `src/recipe_app/templates/pantry_matches.html` | Fix inline `onchange` CSP violation |
| `static/app.js` | Timer engine (detection + countdown + audio), step navigation, grocery checkbox delegation, sort/filter, ghost cooking mode fix. All new code uses `var`/`function` (ES5 style). |
| `static/style.css` | Timer panel (fixed, pill-to-card), aisle headers, completed step (gray border), safe-area-insets, `tabular-nums` for countdown |

---

## Testing Plan

### Pure Function Unit Tests (sync def, parametrized)

- [x] `test_normalizer.py` -- 3 strategies in separate test classes: `TestStripParentheticals`, `TestNormalizeHyphens`, `TestSingularize` (with exception set via `pytest.param(..., id=...)`)
- [x] `test_aisle_map.py` -- keyword matching, longest-match-first (coconut milk != Dairy), "Other" fallback, parametrized input/expected pairs
- [x] `test_ingredient_parser_aggregation.py` -- `preserve_fractions=True` returns `Fraction` (assert `isinstance`), canonical unit matching, `None` quantity handling
- [x] `test_aggregation.py` -- pure `_aggregate_ingredients()` function: Fraction summing, multiplicity, mixed units, unquantified items

### Integration Tests (async)

- [x] `test_grocery_aggregation.py` -- full pipeline with `create_meal_plan_entry` factory fixture
- [x] Recipe multiplicity: same recipe on two meal plan days = double quantities
- [x] `servings_override` respected in aggregation
- [x] Empty date range: creates list with no items (not error)
- [x] "Add to grocery list" from recipe: creates new list with aisle-grouped items
- [x] Schema migration: v2->v3 with pre-existing data (create v2 DB manually, run migrations)
- [x] FK cleanup: deleting recipe sets grocery_list_items.recipe_id to NULL
- [x] Grocery detail page renders 200 (regression for known bug)
- [x] CSP regression: assert `onchange=` does not appear in grocery detail HTML

### HTMX Partial Tests

- [x] Grocery list detail with `hx-request: true` returns partial (no `<html` tag), aisle sections present
- [x] Check-item returns single `<li>` fragment, not full list

### MCP Tests

- [x] `generate_grocery_list` accepts `date_start`/`date_end`, returns structured items with `aisle`
- [x] `add_recipe_to_grocery_list` creates list with normalized items
- [x] Tool discovery includes new tools

### Existing Tests

- [x] All existing grocery list tests in `tests/test_grocery_lists.py` still pass

---

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| Ingredient parser library changes break Fraction path | Pin `ingredient-parser-nlp` version; assert `isinstance(qty, Fraction)` |
| Aisle keyword map has wrong categorizations | Conservative "Other" default; expand keywords based on real lists |
| Timer regex false positives (temperatures) | "for X minutes" anchor prevents most; reject near "degrees"; negative test suite |
| NLP parsing blocks event loop | `asyncio.to_thread()` for all CPU-bound aggregation work |
| SQLite FK not enforced via ALTER TABLE | Application-layer FK enforcement in recipe deletion |
| Zombie setInterval on HTMX navigation | Module-level `_timerIntervalId` with guard check |
| Ghost cooking mode across recipes | Explicit recipeId check + state reset in `htmx:afterSettle` |
| AudioContext garbage collected | Module-level `_audioCtx` variable + state check before use |
| Cross-tab timer localStorage race | Per-timer keys instead of shared JSON array |
| Partial transaction failure | `BEGIN IMMEDIATE` + rollback on error |

---

## Deferred Items (Future Sprints)

These items were scoped out during deepening to keep the MVP focused:

| Item | Reason | Effort to Add Later |
|------|--------|-------------------|
| Swipe-to-check mobile | Checkbox works; 60-80 lines of touch handling | Independent addition, no rework |
| Wake Lock API | Most users won't notice; 15 lines when needed | Bolt-on, no rework |
| Desktop Notifications | Web Audio already alerts; iOS doesn't support | Bolt-on, no rework |
| Normalization strategies 4-7 | 3 strategies cover common cases; add when duplicates observed | Incremental additions to `normalizer.py` |
| ~300 additional aisle keywords | ~100 keywords cover obvious items; expand based on real lists | Append to dict constant |
| Timer patterns 3-5 | "for X minutes" + compound covers majority; verb-context most false-positive-prone | Add patterns to client-side regex |
| `aisle_overrides` table + MCP tool | Keyword map + "Other" fallback sufficient for v1 | Independent schema migration |
| Pantry pre-check during generation | User can check items manually | Add to `_aggregate_ingredients` |
| Date-range picker UI | Multiplicity fix is the core improvement; MCP gets date params | Template addition only |
| "Add to grocery list" dropdown/append | Always-create-new is simpler; add picker if too many lists | Route logic change |
| Sort by recipe toggle | Aisle sort is natural grocery order | Client-side JS addition |

---

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-26-001-feat-grocery-cooking-ux-brainstorm.md](docs/brainstorms/2026-03-26-001-feat-grocery-cooking-ux-brainstorm.md) -- Key decisions: same-unit summing only, normalization pipeline, aisle map, Fraction arithmetic, floating timer panel with end-timestamps

### Internal References

- Grocery list CRUD: `src/recipe_app/db.py:837-910`
- Ingredient parser: `src/recipe_app/ingredient_parser.py` (Fraction->float at line ~78)
- Scaling/format: `src/recipe_app/scaling.py:format_quantity()` (line 24-50)
- Pantry matcher: `src/recipe_app/pantry_matcher.py` (imports library directly, not app wrapper -- pre-existing inconsistency)
- Cooking mode JS: `static/app.js:111-200`
- Direction step HTML: `src/recipe_app/templates/recipe_detail.html:148-159`
- Active step CSS: `static/style.css:318-320`
- Migration pattern: `src/recipe_app/db.py:178-290` (`_column_exists()` + `_KNOWN_TABLES`)
- CSP middleware: `src/recipe_app/main.py:42-63`
- Jinja2 filter registration: `src/recipe_app/main.py:90-93`

### Institutional Learnings Applied

- `hx-sync="this:replace"` on `#items-list` container (from calendar view learnings -- placed on the element that is the `hx-target`)
- Event delegation with `_initialized` flag on element (destroyed on HTMX swap, auto-re-inits)
- Document-level delegation with static flag for listeners that survive navigation
- Guard `sanitize(x) or x` anti-pattern -- use `field = sanitize_field(field)` only, never `or original`
- `_column_exists()` for idempotent migrations
- `BEGIN IMMEDIATE` for multi-INSERT write paths (matching `create_recipe()` pattern)
- `asyncio.to_thread()` for CPU-bound work (matching `pantry_matcher.py` pattern)
- LEFT JOIN to recipes for grocery items (handles NULL recipe_id from deletion or manual items)

### External References

- [ingredient-parser-nlp v2.6.0 API](https://pypi.org/project/ingredient-parser-nlp/) -- `ParsedIngredient` dataclass, `quantity` always `Fraction`
- [Web Audio API Best Practices - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices) -- AudioContext on user gesture, gain scheduling
- [Screen Wake Lock API - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API) -- 95.9% browser support, auto-released on visibility change
- [HTMX hx-sync documentation](https://htmx.org/attributes/hx-sync/) -- `this:replace` aborts in-flight, issues new
- [SQLite ALTER TABLE](https://www.sqlite.org/lang_altertable.html) -- FK constraints silently ignored on ADD COLUMN
- [Python fractions module](https://docs.python.org/3/library/fractions.html) -- `limit_denominator(8)` for cooking-friendly display
