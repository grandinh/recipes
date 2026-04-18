---
title: "feat: Paprika Workflow Parity — Global Calendar, Single Grocery List, Pantry Overhaul + Polish"
type: feat
status: completed
date: 2026-03-27
deepened: 2026-03-27
origin: docs/brainstorms/2026-03-27-001-feat-sprint5-polish-paprika-workflow-brainstorm.md
---

# Sprint 5: Paprika Workflow Parity + Polish

## Enhancement Summary

**Deepened on:** 2026-03-27
**Research agents used:** data-migration-expert, data-integrity-guardian, architecture-strategist, security-sentinel, performance-oracle, julik-frontend-races-reviewer, agent-native-reviewer, pattern-recognition-specialist, code-simplicity-reviewer, best-practices-researcher, framework-docs-researcher

### Critical Blockers Found

1. **Migration SQL has 5 bugs** — `schema.sql` resets `user_version` to 3 on restart (data loss loop), `updated_at` column doesn't exist on source table (hard fail), hardcoded `id=1` creates duplicate grocery list, `grocery_lists.meal_plan_id` FK references dropped table, `generate_grocery_list` queries dropped table. Corrected migration SQL provided below.
2. **FTS5 `highlight()` does NOT HTML-escape** — using `|safe` in Jinja2 is XSS. Must use non-HTML markers in SQL, escape in Python, then replace markers with `<mark>` tags.
3. **Export blocks event loop** — ZIP generation with photos must use `asyncio.to_thread()` or streaming.

### Scope Reduction (from simplicity review)

The following are **cut from this sprint** to focus on the core workflow fix:
- ~~Preview-and-confirm flow~~ → Direct add with flash message (add preview later if "add then delete" is annoying)
- ~~Pantry inline edit~~ → Expand add form only; delete and re-add to correct mistakes
- ~~Pantry category grouping~~ → Flat alphabetical list
- ~~Export (HTML + Paprika)~~ → Separate sprint
- ~~Dark mode~~ → Separate sprint
- ~~Search highlighting~~ → Separate sprint
- ~~Category management UI~~ → Separate sprint
- ~~Health & Beauty, Household, Pet aisles~~ → Defer (no food keywords, manual "Other" is fine)
- ~~`servings_override` on calendar_entries~~ → Drop (nothing reads/writes it; trivial to add later)

### What Remains

**Phase 1 (the actual fix):**
1. Schema migration v3→v4 (corrected SQL)
2. Global calendar (web + API + MCP)
3. Single global grocery list with direct-add (web + API + MCP)
4. Pantry add form expansion (all fields)
5. Aisle expansion: +2 (Deli, International/Ethnic) → 16 total
6. All MCP tools updated
7. Tests updated with each step

**Phase 2 (tiny, ship with Phase 1):**
1. Wake lock in cooking mode (~15 lines JS, huge value-to-effort ratio)

### Key Research Insights

- Use `VACUUM INTO` for pre-migration backup (WAL-safe, not `shutil.copy`)
- Use `PRAGMA foreign_keys = OFF` before table recreation, `PRAGMA foreign_key_check` before commit
- Use `executemany()` instead of loop in grocery item inserts (50-100ms savings)
- Pantry matching: Python set lookup on normalized names, not SQL LIKE
- FTS5 highlighting: use `\x00` markers in SQL, `markupsafe.escape()` in Python, replace markers with `<mark>`
- Wake lock: re-acquire on `visibilitychange`, use request counter to prevent orphaned locks
- `hx-push-url` should be via `HX-Push-Url` response header, not on request element (prevents history pollution on aborted requests)

## Overview

Replace the multi-plan/multi-list model with Paprika 3's single-calendar, single-grocery-list workflow. Then add polish features (export, dark mode, wake lock, search highlighting, category management). This is the largest structural change since initial build — it touches schema, every layer of the meal plan + grocery stack, and all three entry points (web, API, MCP).

## Problem Statement / Motivation

The current model is structurally wrong for how people actually plan meals:
- **Meal Plans**: Users must create named plans, then add entries to them. Paprika (and real life) uses a single global calendar — drop a recipe on Tuesday dinner, done.
- **Grocery Lists**: Users get a new list per generation. Paprika has one persistent shopping list that accumulates items and survives across trips.
- **Pantry**: Schema has all fields but the web UI only exposes name + expiration. No edit. No category grouping. Feels broken.

Phase 1 fixes the model. Phase 2 adds polish that was deferred while the core workflow was wrong.

(See brainstorm: `docs/brainstorms/2026-03-27-001-feat-sprint5-polish-paprika-workflow-brainstorm.md`)

## Proposed Solution

### Phase 1: Model Shift (do first — everything depends on this)

#### Step 1: Schema Migration (v3 → v4)

SQLite cannot ALTER columns or drop FKs. Must create new tables, copy data, drop old.

> **WARNING (from migration review):** The original migration SQL had 5 blocking bugs. The corrected version below fixes all of them. See Enhancement Summary for details.

**Pre-migration:** Use `VACUUM INTO` for backup (WAL-safe):
```python
await db.execute(f"VACUUM INTO '{backup_path}'")
```

**Corrected migration SQL:**
```sql
-- Migration block in db.py: if version < 4:

-- Step 0: Disable FK enforcement for table recreation
PRAGMA foreign_keys = OFF;

-- Step 1: Calendar — meal_plan_entries → calendar_entries
CREATE TABLE calendar_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    date TEXT NOT NULL,          -- YYYY-MM-DD
    meal_slot TEXT NOT NULL CHECK(meal_slot IN ('breakfast','lunch','dinner','snack')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_calendar_entries_date ON calendar_entries(date);
CREATE INDEX idx_calendar_entries_recipe ON calendar_entries(recipe_id);

-- Copy entries (use created_at for updated_at — old table has no updated_at column)
INSERT INTO calendar_entries (recipe_id, date, meal_slot, created_at, updated_at)
    SELECT recipe_id, date, meal_slot, created_at, created_at
    FROM meal_plan_entries;

-- Step 2: Grocery — recreate grocery_lists WITHOUT meal_plan_id FK column
-- (meal_plan_id references meal_plans which we're about to drop)
CREATE TABLE grocery_lists_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Re-point all items to the lowest-id list (don't hardcode id=1)
UPDATE grocery_list_items SET grocery_list_id = (SELECT MIN(id) FROM grocery_lists)
    WHERE grocery_list_id != (SELECT MIN(id) FROM grocery_lists);

-- Copy the surviving list, renamed
INSERT INTO grocery_lists_new (id, name, created_at, updated_at)
    SELECT id, 'Grocery List', created_at, updated_at
    FROM grocery_lists
    WHERE id = (SELECT MIN(id) FROM grocery_lists);

-- If grocery_lists was empty, create a default row
INSERT OR IGNORE INTO grocery_lists_new (id, name) VALUES (1, 'Grocery List');

DROP TABLE grocery_lists;
ALTER TABLE grocery_lists_new RENAME TO grocery_lists;

-- Recreate grocery_lists trigger (DROP TABLE destroyed it)
CREATE TRIGGER trg_grocery_lists_updated
AFTER UPDATE ON grocery_lists FOR EACH ROW BEGIN
    UPDATE grocery_lists SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Recreate grocery_list_items FK index
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_list ON grocery_list_items(grocery_list_id);

-- Step 3: Drop old tables (child first, then parent)
DROP TABLE IF EXISTS meal_plan_entries;
DROP TABLE IF EXISTS meal_plans;

-- Step 4: Create calendar update trigger
CREATE TRIGGER trg_calendar_entries_updated
AFTER UPDATE ON calendar_entries FOR EACH ROW BEGIN
    UPDATE calendar_entries SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Step 5: Re-enable FK enforcement and verify integrity
PRAGMA foreign_key_check;
PRAGMA foreign_keys = ON;

PRAGMA user_version = 4;
```

**CRITICAL: Also update `schema.sql`** to match post-migration state:
- Remove `meal_plans` and `meal_plan_entries` table/index/trigger definitions
- Add `calendar_entries` table/index/trigger definitions (with `IF NOT EXISTS`)
- Remove `grocery_lists.meal_plan_id` column from the CREATE statement
- Change `PRAGMA user_version = 3` → `PRAGMA user_version = 4`

Without this, `init_schema()` recreates dropped tables and resets `user_version` on every restart, causing the migration to re-run against empty tables (silent data loss).

**Also update `_KNOWN_TABLES`** in `db.py:167` — add `calendar_entries`, remove `meal_plans` and `meal_plan_entries`.

**Post-migration verification:**
```sql
SELECT COUNT(*) FROM calendar_entries;                    -- should match pre-migration meal_plan_entries count
SELECT COUNT(*) FROM grocery_lists;                       -- should be 1
SELECT COUNT(*) FROM grocery_list_items;                  -- should be unchanged
PRAGMA table_info(grocery_lists);                          -- should NOT have meal_plan_id
SELECT name FROM sqlite_master WHERE name IN ('meal_plans', 'meal_plan_entries');  -- should be empty
PRAGMA user_version;                                      -- should be 4
```

**Key decisions:**
- `servings_override` is **dropped** — nothing reads/writes it; trivial migration to add later if needed
- Grocery uses "recreate table" strategy to remove `meal_plan_id` FK column (avoids dangling FK to dropped table)
- Column types use `TEXT NOT NULL DEFAULT (datetime('now'))` to match existing codebase convention (not `TIMESTAMP`)
- No uniqueness constraint on `(date, meal_slot, recipe_id)` — multiple recipes per slot is allowed (existing behavior, template already handles it)
- `ON DELETE CASCADE` on `recipe_id` — deleting a recipe silently removes calendar entries. Acceptable for a personal app.

#### Step 2: Global Calendar (replaces Meal Plans)

**URL scheme:** `/calendar?week=YYYY-MM-DD` (replaces `/meal-plans` and `/meal-plans/{id}`)

**Files to modify:**

| Layer | File | Changes |
|-------|------|---------|
| DB | `db.py` | Replace 10 meal plan functions with: `add_calendar_entry()`, `get_calendar_week(date)`, `remove_calendar_entry(entry_id)`, `list_recipe_titles()` (keep) |
| Routes | `main.py` | Replace `/meal-plans/*` routes with `/calendar` routes. `_render_calendar_grid()` loses `plan_id` param |
| API | `routers/meal_plans.py` → split into `routers/calendar.py` + `routers/grocery.py` | `POST /api/calendar/entries`, `DELETE /api/calendar/entries/{id}`, `GET /api/calendar?week=` |
| Models | `meal_plan_models.py` → rename to `calendar_models.py` | Drop `MealPlanCreate`, `MealPlanUpdate`. Keep `CalendarEntryCreate(recipe_id, date, meal_slot, servings_override?)` |
| MCP | `mcp_server.py` | Replace 8 meal plan tools with: `add_to_calendar(recipe_id, date, meal_slot)`, `add_to_calendar_batch(entries)`, `get_calendar_week(date)`, `remove_from_calendar(entry_id)` |
| Templates | `meal_plan_detail.html` → `calendar.html` | Remove plan-scoped header. Remove "Back to Plans" link. Add "Generate Grocery List from This Week" button. Fix mobile "+" to show slot picker instead of hardcoding dinner |
| Templates | `meal_plans.html` | **Delete** (no list-of-plans page) |
| Nav | `base.html` | "Meal Plans" → "Calendar", href → `/calendar` |
| Tests | `tests/test_meal_plans.py` → `tests/test_calendar.py` | Rewrite for new model |

**Calendar → Grocery generation UI:**
- Button on calendar page: "Add This Week to Grocery List"
- Uses the currently visible week's date range (Monday–Sunday)
- Aggregates ingredients from all recipes in that range via existing `aggregation.py` pipeline
- Goes to the preview-and-confirm flow (see Step 3)

#### Step 3: Single Global Grocery List

**URL scheme:** `/grocery` (replaces `/grocery-lists` and `/grocery-lists/{id}`)

**Files to modify:**

| Layer | File | Changes |
|-------|------|---------|
| DB | `db.py` | `_save_grocery_list()` → `_append_to_grocery_list()` (append semantics, not create). Remove `list_grocery_lists()`. `get_grocery_list()` takes no ID. `generate_grocery_list()` takes `date_start, date_end` instead of `meal_plan_id`. All other functions lose `list_id` param. |
| Routes | `main.py` | `/grocery` shows the single list. `/grocery/add-from-recipe/{recipe_id}` for preview flow. `/grocery/add-from-calendar` for calendar generation flow. |
| API | **New:** `routers/grocery.py` | Grocery endpoints lose `list_id`. `GET /api/grocery`, `POST /api/grocery/items`, `DELETE /api/grocery/items/{id}`, `POST /api/grocery/generate-from-calendar`, `POST /api/grocery/add-from-recipe/{recipe_id}` |
| MCP | `mcp_server.py` | Replace 10 grocery tools with: `get_grocery_list()`, `add_grocery_item(name, aisle?)`, `add_recipe_to_grocery_list(recipe_id)`, `preview_grocery_additions(recipe_id)`, `generate_grocery_list_from_calendar(start, end)`, `check_grocery_item(item_id, is_checked)`, `clear_bought_items()`, `delete_grocery_item(item_id)`, `move_checked_to_pantry()` |
| Templates | `grocery_list_detail.html` → `grocery.html` | Remove list-specific header. Keep aisle-grouped display, checkbox toggle, bulk actions |
| Templates | `grocery_lists.html` | **Delete** (no list-of-lists page) |
| Nav | `base.html` | "Grocery Lists" → "Grocery List", href → `/grocery` |
| Tests | `tests/test_grocery_lists.py` → `tests/test_grocery.py` | Rewrite for new model |

**Simplified add-to-grocery flow (direct add, no preview):**

> Scope reduction: The preview-and-confirm flow was cut. Direct add is simpler, matches MCP behavior, and can be enhanced later if "add then delete" becomes annoying.

- "Add to Grocery List" on recipe detail: `POST /grocery/add-from-recipe/{recipe_id}` → adds all ingredients, redirect to `/grocery` with flash message "12 items added"
- "Add This Week to Grocery List" on calendar: `POST /grocery/add-from-calendar` → adds all ingredients from visible week, redirect to `/grocery` with flash message
- Users remove items they don't want from `/grocery` (they need this ability anyway)
- Pantry-matched items get `in_pantry` flag and visual indicator on the grocery list — but they are still added

**Pantry matching (in Python, not SQL):**
```python
# After aggregation, in the route handler:
pantry_names = {row["name"].lower() for row in await list_pantry_items(db)}
for item in aggregated:
    norm = item["normalized_name"]
    item["in_pantry"] = norm in pantry_names or any(p in norm for p in pantry_names)
```

**Use `executemany()` for batch inserts** (performance research finding):
```python
await db.executemany(
    "INSERT INTO grocery_list_items (...) VALUES (?, ?, ?, ?, ?, ?)",
    [(list_id, item["text"], ...) for item in aggregated],
)
```

**`sort_order` on append:** Query `MAX(sort_order)` from existing items and offset new items to prevent colliding sort positions across generations.

**Duplicate handling when appending:** No cross-generation deduplication. If "chicken breast" is already on the list and you add more, it appears as a second row. This matches Paprika behavior. The aggregation pipeline dedupes within a single generation.

**Protect the global list row:** Remove `delete_grocery_list()` endpoint/MCP tool entirely — deleting the only list breaks the system. Keep `clear_bought_items()` for list cleanup.

**REST API behavior:** Direct-add semantics (matching MCP). Return `{items_added: [...], pantry_flagged: [...], total_items: int}` so API consumers know what was added.

**MCP behavior for `add_recipe_to_grocery_list(recipe_id)`:** Adds all ingredients. Pantry-matched items flagged with `in_pantry=True`. Returns items added with pantry flags so agent can make follow-up decisions.

**New MCP tool: `preview_grocery_additions(recipe_id)`:** Read-only — returns what *would* be added without writing. Gives agent parity with future preview UI.

#### Step 4: Pantry Add Form Expansion (web UI only — no schema/API changes)

> Scope reduction: Inline edit and category grouping cut. Expand the add form to expose all fields. Delete and re-add to correct mistakes. Flat alphabetical list.

**Files to modify:**

| Layer | File | Changes |
|-------|------|---------|
| Templates | `pantry.html` | Full add form: name, quantity, unit, category, expiration date. Expiration warnings (already partially there). |
| CSS | `style.css` | Minor styling for expanded form fields |

**Category field:** Free-text input with `<datalist>` autocomplete (populated from existing pantry categories + the 16 aisle names). Not a strict dropdown — user can type anything.

**No inline edit.** Delete and re-add. This is a personal app with likely a few dozen pantry items. If inline edit becomes needed, add it later using the HTMX click-to-edit pattern (documented in research: `hx-swap="outerHTML"` with display/edit partials, cancel button with `type="button"` + `hx-get`).

#### Step 5: Aisle Expansion (14 → 16)

> Scope reduction: Only add aisles with food keywords. Health & Beauty, Household, Pet deferred — items land in "Other" which is fine.

Add 2 aisles to `aisle_map.py`:
- **Deli** — keywords: deli, rotisserie, prepared salad, cold cuts, sliced turkey/ham/salami
- **International/Ethnic** — keywords: curry paste, fish sauce, miso, rice paper, sriracha, soy sauce, hoisin, gochujang, tahini, harissa, sambal

Also update `add_grocery_item()` DB function to accept an optional `aisle` parameter (currently only takes `list_id` and `text`). All three entry points (web form, REST API, MCP) must pass the aisle through.

Manual add form gets an aisle `<select>` dropdown so users can override auto-assignment.

### Phase 2: Wake Lock Only

> Scope reduction: Export, dark mode, search highlighting, category management UI all cut from this sprint. See Enhancement Summary.

#### 2a. Wake Lock in Cooking Mode

**File:** `static/app.js` — add ~20 lines to `initCookingMode()`:

```javascript
// Race-safe wake lock (from frontend review: prevents orphaned locks on fast toggle)
var _wakeLockRequestId = 0;

function _acquireWakeLock() {
    if (!('wakeLock' in navigator) || !_cookingState.active) return;
    var myId = ++_wakeLockRequestId;
    navigator.wakeLock.request('screen').then(function(lock) {
        if (_wakeLockRequestId !== myId || !_cookingState.active) {
            lock.release();  // State changed while waiting — release immediately
            return;
        }
        _cookingState.wakeLock = lock;
    }).catch(function() { /* Permission denied or not supported */ });
}

function _releaseWakeLock() {
    _wakeLockRequestId++;  // Invalidate any pending acquisition
    if (_cookingState.wakeLock) {
        _cookingState.wakeLock.release();
        _cookingState.wakeLock = null;
    }
}

// In cooking mode enter: _acquireWakeLock();
// In cooking mode exit: _releaseWakeLock();
// On visibilitychange (already have handler): if active, _acquireWakeLock();
```

**Browser support:** Baseline 2025 — Chrome 84+, Firefox 126+, Safari 16.4+. HTTPS required (localhost is fine).

#### Deferred to Future Sprints

The following Phase 2 items were cut from this sprint to keep focus on the core workflow fix. Research findings are preserved here for when they are implemented:

**Search Result Highlighting** — FTS5 `highlight()` does NOT HTML-escape content. Do NOT use `|safe`. Instead: use non-HTML markers (`\x00HLOPEN\x00`, `\x00HLCLOSE\x00`) in the SQL query, escape the full output with `markupsafe.escape()` in Python, then replace markers with `<mark>` tags. This prevents XSS on pre-sanitization data.

**Dark Mode** — CSS custom properties already in place. Three-layer pattern: `:root` default, `@media (prefers-color-scheme: dark)` on `:root:not([data-theme="light"])`, `[data-theme="dark"]` for manual override. Inline `<script>` in `<head>` before stylesheet prevents FOUC. `@media print` forces light with `!important`. Clean up hardcoded colors first (`.plan-card background: white`, `var(--border, #ddd)`, etc.).

**Export (HTML + Paprika)** — Must use `asyncio.to_thread()` for ZIP generation (blocks event loop). Use temp file on disk for large exports (not in-memory). Schema.org Recipe JSON-LD: use `json.dumps()` with `</` → `<\/` escaping to prevent script breakout. Sanitize ZIP entry filenames to `recipe_{id}.paprikarecipe`. Paprika format: ZIP of gzipped JSON, reverse `map_paprika_recipe()` field mapping.

**Category Management UI** — Pre-existing bug: `create_category()` and `delete_category()` in db.py are missing `_write_lock` and `sanitize_field()`. Fix these before building a web UI on top. Add `update_category(id, name)` db function + `rename_category` MCP tool + `PATCH /api/categories/{id}`.

## Technical Considerations

### Migration Risk

This is the riskiest part of the sprint. Mitigations:
- DB is backed up before migration (existing pattern in `run_migrations()`)
- Migration runs in a single transaction with rollback on error
- Test migration with a populated DB before deploying
- `user_version` bump (3 → 4) is the last statement — if anything fails, version stays at 3

### MCP Tool Design (from agent-native review)

**New calendar tools (4):**
- `add_to_calendar(recipe_id, date, meal_slot)` — use `meal_slot` not `slot` (matches schema CHECK constraint). Docstring lists valid values.
- `add_to_calendar_batch(entries: list[{recipe_id, date, meal_slot}])` — batch add for weekly planning. Single transaction. The web UI doesn't need this but the agent does (7-21 sequential calls otherwise).
- `get_calendar_week(date)` — docstring: "Pass any date; returns the full Monday-through-Sunday week containing that date."
- `remove_from_calendar(entry_id)` — remove single entry.

**New grocery tools (9):**
- `get_grocery_list()` — returns all items with `is_checked` and `in_pantry` flags.
- `add_grocery_item(name, aisle?)` — auto-assigns aisle when None; explicit aisle overrides.
- `add_recipe_to_grocery_list(recipe_id)` — adds all ingredients. Returns `{items_added: [...with in_pantry bool...], pantry_match_count: int}`.
- `preview_grocery_additions(recipe_id)` — read-only, returns what *would* be added. Agent parity for future preview UI.
- `generate_grocery_list_from_calendar(start, end)` — returns `{items_added: [...], pantry_flagged: [...], total_items: int}`.
- `check_grocery_item(item_id, is_checked)` — toggle.
- `delete_grocery_item(item_id)` — remove single item.
- `clear_bought_items()` — no `list_id` param (single list model).
- `move_checked_to_pantry()` — no `list_id` param.

**Removed:** `delete_grocery_list` (protect the single global list row), `list_grocery_lists` (only one list).

**All write tools must return rich output** — the resulting state, not just `{"status": "ok"}`. This is critical for agent follow-up reasoning.

**Atomically replace old tools** — never register both old and new meal plan/grocery tools simultaneously. Remove all old tool registrations in the same PR that adds new ones.

### Entry-Point Parity Checklist

Per documented learning (see `docs/solutions/implementation-patterns/grocery-management-mcp-web-parity-code-review.md`): every feature exposed through web UI, REST API, and MCP must enforce identical validation, size limits, sanitization, and error handling. Apply this to every new calendar and grocery endpoint.

### Known Gotchas from Prior Sprints

1. **Never `sanitize_field(x) or x`** — XSS bypass, documented 3 times. Use direct assignment.
2. **`hx-sync="this:replace"`** on calendar grid container — prevents race conditions on concurrent swaps.
3. **Event delegation with `_initialized` flag on the grid element** — survives HTMX content swaps.
4. **`asyncio.to_thread()` for CPU-bound NLP parsing** in grocery generation pipeline.
5. **Fraction arithmetic, never float** for ingredient quantities.
6. **Same-unit-only merging** — no unit conversion.
7. **`asyncio.create_task()` return values must be stored** to prevent GC collection.

### Frontend Race Conditions to Fix (from HTMX reviewer)

1. **Grocery remaining count not updated on per-item check** — `htmx:afterSettle` only triggers counter updates when target is `#items-list`, but per-item check swaps target `#item-N`. Fix: add check in `htmx:afterSettle` for `.grocery-item` targets to call `_updateGroceryRemaining()`.

2. **Calendar form fields not cleared after week navigation** — `_calendarInitialized` guard on surviving `#calendar-grid` prevents field-clearing on subsequent swaps. Fix: move field-clearing to `htmx:afterSettle` handler (always runs), not inside the guarded `initCalendar()`.

3. **`hx-push-url` fires before request completes** — rapid navigation pollutes browser history with phantom entries. Fix: remove `hx-push-url="true"` from prev/next buttons; use `HX-Push-Url` response header from the server instead.

4. **Beep chain not cancellable** — timer alert beeps continue after navigating away. Fix: add cancel token pattern to `_doBeep()`.

### State Consistency

- **Calendar → grocery is a snapshot.** Removing a recipe from the calendar does not remove its items from the grocery list. This matches Paprika behavior.
- **Recipe deletion cascades to calendar entries** (ON DELETE CASCADE) but **sets grocery items to NULL recipe_id** (ON DELETE SET NULL). Grocery items survive recipe deletion.
- **No cross-generation deduplication** on the grocery list. Each "add from recipe" or "generate from calendar" appends new rows.

## System-Wide Impact

- **Interaction graph**: Calendar add/remove → HTMX partial swap of calendar grid. Grocery add → preview page → POST → redirect to /grocery. Check/uncheck → per-item HTMX swap.
- **Error propagation**: DB write errors → 500 in route → HTMX error swap. Migration errors → rollback, version stays at 3, app falls back to old schema.
- **State lifecycle risks**: Partial migration failure is the main risk — mitigated by transaction + version gate. Grocery "preview then confirm" has no intermediate state to corrupt.
- **API surface parity**: Web UI, REST API, and MCP all need updating for calendar and grocery. Pantry API/MCP already complete — only web UI changes.

## Acceptance Criteria

### PR 1: Model Shift

- [ ] `schema.sql` updated to match post-migration state (no `meal_plans`/`meal_plan_entries`, has `calendar_entries`, `user_version=4`)
- [ ] Migration v3→v4 runs cleanly on populated DB — post-migration verification queries all pass
- [ ] Migration does NOT re-run on restart (schema.sql user_version matches migration version)
- [ ] `/calendar` shows global week view with all entries (no plan selection step)
- [ ] Can add/remove recipes on calendar via web UI, REST API, and MCP
- [ ] `add_to_calendar_batch` MCP tool works for weekly meal planning
- [ ] `/grocery` shows single persistent grocery list grouped by aisle
- [ ] Can add items to grocery list from: recipe detail (direct add), calendar "Add This Week" button, manual entry
- [ ] Pantry-matched items flagged with "in pantry" indicator on grocery list
- [ ] Grocery list filter: "to buy" / "bought" / "all" (client-side CSS toggle)
- [ ] "Clear bought items" and "Move to pantry" work on global list
- [ ] `delete_grocery_list` endpoint/tool removed (protect single global list)
- [ ] All MCP tools updated: old meal plan/grocery tools removed, new calendar/grocery tools work, all return rich output
- [ ] REST API updated: `routers/grocery.py` split from calendar, old endpoints removed
- [ ] Frontend race conditions fixed: grocery count, calendar form fields, hx-push-url
- [ ] All existing tests pass (updated for new model), new tests for calendar + grocery

### PR 2: Pantry + Wake Lock

- [ ] Pantry add form exposes all fields (name, quantity, unit, category, expiration)
- [ ] Category field has datalist autocomplete
- [ ] Wake lock: screen stays on during cooking mode, released on exit, no orphaned locks on fast toggle
- [ ] Wake lock gracefully degrades (feature detection, try-catch on request)

## Implementation Order

> Updated based on architecture and simplicity reviews. Key changes: MCP tools ship with each step (not deferred), tests update with each step (not batched), aisle expansion moves before grocery.

```
1. Schema migration (v3→v4) + update schema.sql     — everything depends on this
   ↓
2. Calendar model + web UI + API + MCP tools         — uses new schema, tests included
   ↓
3. Aisle expansion (14→16)                           — before grocery (used by add flow)
   ↓
4. Grocery model + web UI + API + MCP tools          — uses new schema + calendar, tests included
   ↓
5. Pantry add form expansion                         — independent, low risk
   ↓
6. Frontend race condition fixes                     — calendar + grocery JS fixes
   ↓
7. Wake lock                                         — ~20 lines JS, zero backend
```

**PR breakdown (2 PRs, not 5):**

> From simplicity review: fewer PRs = fewer context switches. Each PR leaves all three entry points (web, API, MCP) in a working state.

- **PR 1: Model Shift** — Schema migration + calendar + aisle expansion + grocery + MCP tools for both + tests (Steps 1-4, 6)
- **PR 2: Pantry + Wake Lock** — Pantry add form expansion + wake lock (Steps 5, 7)

## Resolved Questions (from SpecFlow analysis + deepening)

1. **Migration strategy**: Create new tables, copy data, recreate `grocery_lists` without `meal_plan_id`, drop old. VACUUM INTO for backup. PRAGMA foreign_keys = OFF during recreation, foreign_key_check before commit.
2. **`servings_override`**: Dropped — nothing reads/writes it. Trivial to add later if needed.
3. **Calendar uniqueness**: No UNIQUE constraint — multiple recipes per date+slot allowed. Template already handles this.
4. **Recipe deletion**: CASCADE for calendar entries, SET NULL for grocery items. Acceptable for personal app.
5. **Calendar date range for grocery**: Default to currently visible week. "Add This Week to Grocery List" button. No date range picker (YAGNI).
6. **Grocery append vs create**: `_save_grocery_list()` becomes `_append_to_grocery_list()` with `executemany()`. Query `MAX(sort_order)` and offset new items.
7. **MCP add-from-recipe**: Adds all ingredients, pantry items flagged but included. Returns items with flags. New `preview_grocery_additions` for read-only preview.
8. **Pantry matching**: Python set lookup on normalized names (not SQL LIKE). Fetch all pantry names once, match in-memory.
9. **Duplicate handling**: No cross-generation dedup. Matches Paprika.
10. **Aisle expansion**: +2 only (Deli, International/Ethnic). Health & Beauty, Household, Pet deferred.
11. **Pantry category input**: Free-text with datalist autocomplete, not a strict dropdown.
12. **Grocery filter**: Client-side CSS toggle (extend existing "Hide checked" pattern).
13. **Preview-and-confirm**: Cut from v1. Direct add with flash message. Add preview later if needed.
14. **Pantry inline edit**: Cut from v1. Delete and re-add. Add click-to-edit later if needed.
15. **URL scheme**: `/calendar?week=YYYY-MM-DD` and `/grocery`.
16. **Router split**: `routers/meal_plans.py` → `routers/calendar.py` + `routers/grocery.py` (don't couple them).
17. **PR count**: 2 PRs, not 5. Model shift is one atomic PR. Pantry + wake lock is the second.
18. **FTS5 highlighting (deferred)**: Must use non-HTML markers + Python escaping. Never `|safe` on highlight() output.
19. **`create_category()` bug**: Missing `_write_lock` and `sanitize_field()`. Fix before building category UI.
20. **Global grocery list protection**: Remove `delete_grocery_list()` — deleting the only list breaks the system.

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-27-001-feat-sprint5-polish-paprika-workflow-brainstorm.md](docs/brainstorms/2026-03-27-001-feat-sprint5-polish-paprika-workflow-brainstorm.md) — Key decisions carried forward: single global calendar (replaces meal plans), single global grocery list with preview-and-confirm flow, pantry items marked "in pantry" not auto-excluded, 19 aisles.

### Internal References

- Schema: `src/recipe_app/sql/schema.sql` (current v3)
- DB functions: `src/recipe_app/db.py:738-1165` (meal plan + grocery functions)
- Calendar grid template: `src/recipe_app/templates/meal_plan_detail.html`
- Calendar grid helper: `src/recipe_app/main.py:389-428`
- Aggregation pipeline: `src/recipe_app/aggregation.py`
- Aisle mapping: `src/recipe_app/aisle_map.py`
- Paprika import (reverse for export): `src/recipe_app/paprika_import.py:170-232`
- CSS variables: `static/style.css:4-19`
- Cooking mode JS: `static/app.js:294-340`
- FTS5 search: `src/recipe_app/db.py:602-680`

### Documented Learnings Applied

- `docs/solutions/implementation-patterns/calendar-view-paprika-import-fastapi-htmx.md` — HTMX calendar patterns, hx-sync, event delegation
- `docs/solutions/implementation-patterns/grocery-aggregation-pipeline-and-code-review-fixes.md` — Fraction arithmetic, aisle matching, asyncio.to_thread
- `docs/solutions/implementation-patterns/grocery-management-mcp-web-parity-code-review.md` — Entry-point parity checklist, sanitization
- `docs/solutions/test-failures/comprehensive-test-coverage-fastapi-recipe-app.md` — Per-test DB isolation, factory fixtures, MCP testing patterns
