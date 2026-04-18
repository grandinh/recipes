---
title: "feat: Calendar Meal Plan View + Paprika Import"
type: feat
status: completed
date: 2026-03-26
deepened: 2026-03-27
origin: docs/brainstorms/2026-03-26-002-feat-calendar-mealplan-paprika-import-brainstorm.md
---

# feat: Calendar Meal Plan View + Paprika Import

## Enhancement Summary

**Deepened on:** 2026-03-27
**Sections enhanced:** All
**Agents used:** kieran-python-reviewer, performance-oracle, security-sentinel, architecture-strategist, agent-native-reviewer, code-simplicity-reviewer, julik-frontend-races-reviewer, data-integrity-guardian, pattern-recognition-specialist, framework-docs-researcher

### Key Changes from Deepening
1. **Import uses background task** — 15-min synchronous POST is not viable; `asyncio.create_task` + polling page (~20 lines extra)
2. **ZIP/gzip security hardening** — decompression size limits, entry count cap, path traversal guard
3. **Calendar frontend race fixes** — `hx-sync`, event delegation, stale form field clearing, history restore handler
4. **Simplified import scope** — dropped `.paprikarecipe` single-file, MCP import tool, `nutritional_info`/`total_time` mapping, configurable size limit
5. **Added `get_meal_plan_week` MCP tool** — agent parity for the core new feature
6. **Catch IntegrityError instead of SELECT-before-INSERT** — simpler and race-free duplicate detection
7. **Orphan photo cleanup** — delete photo files in except block if DB insert fails
8. **Pre-existing bug found** — `sanitize_field(i) or i` in `db.py:349,428` bypasses sanitization on empty strings

---

## Overview

Two features that complete the app's identity as a Paprika replacement: (1) a visual weekly calendar for meal plans replacing the flat table, and (2) Paprika 3 archive import to migrate existing recipe libraries. The meal plan data model is already complete — this is frontend + a new DB query. The import is a file-processing pipeline with field mapping and photo handling.

## Problem Statement / Motivation

The meal plan view is a flat HTML table (date, meal, recipe, remove). Users can't visualize their week at a glance or interact intuitively with their plan. The app claims to be a "Paprika 3 replacement" but offers no way to import data from Paprika. These are the two structural gaps blocking daily-driver usage.

(see brainstorm: `docs/brainstorms/2026-03-26-002-feat-calendar-mealplan-paprika-import-brainstorm.md`)

---

## Feature 1: Calendar Meal Plan View

### Proposed Solution

Replace `meal_plan_detail.html` with a **weekly CSS grid calendar** — 7 day columns x 4 meal slot rows. No external calendar library (FullCalendar is too heavy for an HTMX app). Pure CSS grid + vanilla JS + HTMX partials.

### Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Calendar scope | Weekly view only | Highest value for meal planning. Monthly/daily deferred. |
| Week start | Monday | ISO 8601, simpler `isocalendar()` math |
| URL state | `?week=YYYY-MM-DD` query param | Bookmarkable, browser back/forward works, HTMX `hx-push-url` |
| Empty plan default | Current week | Standard calendar behavior |
| Recipe picker | "+" button in cell -> pre-fills shared top form | Minimal JS. Click sets hidden date/slot fields, scrolls to form. |
| Recipe dropdown | Keep `<select>` with `list_recipe_titles()` | Lightweight `(id, title)` query vs loading full recipes. Trivial to add. |
| Mobile layout | Vertical day list at `max-width: 600px` | Matches existing breakpoint. 7-column grid is unusable at 375px. |
| HTMX swap strategy | Swap entire calendar grid block on any mutation | Simple, avoids stale cells. Per-cell swap deferred. |
| Multi-recipe cells | Vertical stack within cell, CSS overflow scroll | Schema allows multiple entries per (date, slot). No artificial limit. |
| Thumbnails | Text only for MVP | Keeps DOM light. `recipe_image_url` already in query for future use. |
| Servings override | Deferred | Schema supports it. Add the form field when someone actually wants it. |
| Today highlight | CSS class on today's column | Trivial, improves orientation. |
| Drag-and-drop | Not MVP | Touch-unfriendly, complex with HTMX. Future enhancement. |

### Technical Approach

#### New/Modified Files

**`src/recipe_app/db.py`** — Add functions:
- `list_recipe_titles(db) -> list[dict]` — returns `[{"id": int, "title": str}]` (use `list[dict]` not tuples, matching codebase convention)
- `get_meal_plan_week(db, plan_id: int, week_start: date, week_end: date) -> dict | None` — entries filtered by date range, same JOIN as `get_meal_plan` but with `WHERE date BETWEEN ? AND ?`. Accept `date` objects, convert to ISO strings at query boundary.

**`src/recipe_app/main.py`** — Modify routes:

`meal_plan_detail_page`:
- Accept `week: date | None = Query(default=None)` — FastAPI auto-validates ISO 8601, returns 422 on bad format
- Snap to Monday: `week_start = week - timedelta(days=week.weekday())` if provided, else Monday of current week
- Compute `week_end`, `prev_week`, `next_week`, `days` list (7 date objects with weekday names)
- Call `get_meal_plan_week()` for entries, `list_recipe_titles()` for dropdown
- HTMX partial: return `calendar_grid` block when `hx-request`

`remove_entry_submit`:
- Add `plan_id` as URL parameter or hidden form field (needed to re-query the week for HTMX response)
- Change URL to `POST /meal-plans/{plan_id}/entries/{entry_id}/remove`
- Add `hx-request` check: return `calendar_grid` block for HTMX, 303 redirect for regular

`add_recipe_to_plan_submit`:
- Change HTMX response from `entries_list` block to `calendar_grid` block

**`src/recipe_app/templates/meal_plan_detail.html`** — Rewrite:
- Week navigation header: `< March 23 - 29, 2026 >` with prev/next as `hx-get` links
- **`hx-sync="this:replace"`** on `#calendar-grid` — serializes concurrent requests (prevents nav + add race)
- CSS grid calendar: 7 columns x 4 rows, meal slot labels on left
- Each cell: recipe entries (title + remove button) + "+" add button with `data-date` and `data-slot` attributes
- Add form: date (hidden), meal_slot (hidden), recipe dropdown
- `{% block calendar_grid %}` wrapping the grid for HTMX partial rendering
- HTMX: prev/next target `#calendar-grid` with `hx-push-url="true"`
- HTMX: add form targets `#calendar-grid`

**`static/style.css`** — Add calendar styles:
- `.calendar-grid` — CSS grid, `.calendar-header`, `.calendar-cell`, `.meal-slot-label`, `.calendar-entry`, `.today`
- `@media (max-width: 600px)` — collapse to vertical day list

**`static/app.js`** — Add `initCalendar()`:

```javascript
function initCalendar() {
  var grid = document.getElementById('calendar-grid');
  if (!grid || grid._calendarInitialized) return;
  grid._calendarInitialized = true;

  // Reset stale form fields on every grid swap
  var form = document.getElementById('add-recipe-form');
  if (form) {
    form.querySelector('[name="date"]').value = '';
    form.querySelector('[name="meal_slot"]').value = '';
  }

  // Event delegation on grid — survives cell content changes
  grid.addEventListener('click', function(e) {
    var addBtn = e.target.closest('.calendar-add-btn');
    if (!addBtn || !form) return;
    form.querySelector('[name="date"]').value = addBtn.dataset.date;
    form.querySelector('[name="meal_slot"]').value = addBtn.dataset.slot;
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// Add htmx:historyRestore handler for browser back/forward
document.body.addEventListener('htmx:historyRestore', function() {
  initAll();
});
```

- Flag is on the `grid` element (gets destroyed on swap, so re-initializes correctly)
- Event delegation: one listener on grid, not per-button
- Stale form fields cleared on every re-init
- `htmx:historyRestore` handler for browser back/forward

**`src/recipe_app/templates/base.html`** — Register Jinja2 date filter:

```python
# In main.py after creating templates
templates.env.filters["weekday_name"] = lambda d: d.strftime("%a")
templates.env.filters["short_date"] = lambda d: d.strftime("%b %-d")
```

**`src/recipe_app/mcp_server.py`** — Add tool:
- `get_meal_plan_week(plan_id: int, week_start: str, week_end: str)` — agent parity for the core new feature. Wraps `db.get_meal_plan_week()`.

#### Data Flow

```
User clicks "+" in Wednesday/Dinner cell
  -> JS sets date="2026-03-25", meal_slot="dinner", scrolls to form
  -> User selects recipe, clicks Add
  -> POST /meal-plans/{id}/add-recipe (date, meal_slot, recipe_id)
     hx-target="#calendar-grid" hx-swap="innerHTML"
  -> Route adds entry, re-queries week, returns calendar_grid block
  -> Grid updates in place with new entry

User clicks Prev Week arrow
  -> hx-get="/meal-plans/{id}?week=2026-03-16"
     hx-target="#calendar-grid" hx-push-url="true"
  -> Route queries new week's entries, returns calendar_grid block

User clicks "+" then navigates to different week before submitting
  -> Grid swap triggers initCalendar() which clears hidden date/slot fields
  -> Form is blank — user must click "+" again on the new week (safe)
```

---

## Feature 2: Paprika 3 Import

### Proposed Solution

Dedicated `/import` page with file upload. Process via **background task** with redirect to polling status page. Show results with summary + error list. Support `.paprikarecipes` only (ZIP of gzipped JSONs).

### Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Processing model | Background `asyncio.create_task` + polling status page | Synchronous 15-min POST will timeout in browser. ~20 lines extra for correctness. |
| Max file size | 50MB hardcoded constant | Most Paprika exports are 10-30MB. No need for configurable setting. |
| File format | `.paprikarecipes` (ZIP) only | Single `.paprikarecipe` is edge case. User can add one recipe via web form. |
| Duplicate detection | Catch `IntegrityError` on `source_url` UNIQUE constraint | Simpler than SELECT-before-INSERT, race-free. Also deduplicate within batch in-memory. |
| Empty `source_url` | Normalize to NULL at DB layer | Add `source_url = source_url or None` in `create_recipe()` — defense-in-depth for all entry points. |
| `source` field | Use as `source_url` if non-empty; if not a URL, just store as-is | Don't build URL detection logic. The field is TEXT, not validated as URL. |
| Time string parsing | Simple regex parser -> minutes int, NULL on failure | Handle "X min", "X minutes", "X hour(s)", "X hr X min", "X:XX", bare ints. Empty -> None. |
| Rating mapping | 0 -> None, 1-5 -> 1-5 | Must happen BEFORE constructing RecipeCreate (Pydantic rejects 0 with ge=1). |
| `nutritional_info` | Discard | Pollutes notes with unreadable text. User can re-scrape if needed. |
| `total_time` | Discard | Verify if `total_time_minutes` is a generated column first. Either way, redundant with prep+cook. |
| `ingredients` | Split on `\n` to list | Paprika stores as newline-separated string. |
| Photo handling | base64 decode -> `save_photo()`, cleanup on failure | Delete orphan photo files in except block if DB insert fails. |
| Categories | Auto-create via existing `_ensure_categories` | Already handles `INSERT OR IGNORE`. |
| Results page | Summary counts + flat error list | No expandable per-recipe detail. Keep it simple for a one-time operation. |
| MCP import tool | Deferred | One-time migration. No realistic agent use case. Trivial to add later. |
| Export to Paprika | Not MVP | One-way import only. |

### Technical Approach

#### Typed Intermediate Model

```python
# In paprika_import.py
from pydantic import BaseModel, Field

class MappedRecipe(BaseModel):
    recipe_data: dict  # RecipeCreate-compatible fields
    photo_bytes: bytes | None = None
    warnings: list[str] = Field(default_factory=list)
    source_name: str  # original Paprika name, for results reporting

class ImportResult(BaseModel):
    imported: list[dict] = Field(default_factory=list)   # [{"id": N, "title": "..."}]
    skipped: list[dict] = Field(default_factory=list)     # [{"title": "...", "reason": "..."}]
    errors: list[dict] = Field(default_factory=list)      # [{"title": "...", "error": "..."}]
```

#### New/Modified Files

**`src/recipe_app/paprika_import.py`** — New module:

- `MAX_IMPORT_SIZE = 50 * 1024 * 1024` — hardcoded constant (50MB)
- `MAX_ENTRY_SIZE = 50 * 1024 * 1024` — per-entry decompression limit
- `MAX_RECIPES_PER_IMPORT = 2000` — entry count cap
- `MAX_PHOTO_BASE64_SIZE = 20 * 1024 * 1024` — base64 string limit (~15MB decoded)

- `safe_gzip_decompress(data: bytes, max_size: int) -> bytes` — incremental decompression with size limit (prevents gzip bombs)

- `parse_paprika_archive(file_bytes: bytes) -> list[dict]`:
  - Try `zipfile.ZipFile()` — let stdlib validate (no manual magic bytes)
  - Reject entries with `..` or absolute paths (zip-slip defense)
  - Check `ZipInfo.file_size` per entry and reject > `MAX_ENTRY_SIZE`
  - Cap total entries at `MAX_RECIPES_PER_IMPORT`
  - For each entry: `safe_gzip_decompress()` -> `json.loads()`
  - Run in `asyncio.to_thread()` (CPU-bound, would block event loop)

- `parse_time_string(s: str) -> int | None`:
  - Handle: "15 min", "15 minutes", "1 hour", "1 hr 30 min", "1 hour 30 minutes", "1:30", "90", ""
  - Return `None` for empty/unparseable (not 0)

- `map_paprika_recipe(paprika_json: dict) -> MappedRecipe`:
  - Construct `RecipeCreate`-compatible dict with field mapping
  - Photo: check `len(photo_data) < MAX_PHOTO_BASE64_SIZE`, `base64.b64decode(data, validate=True)`, catch errors -> skip photo with warning
  - Rating: 0 -> None **before** dict (critical: Pydantic rejects 0)
  - `source_url`: use Paprika's `source_url` if non-empty, else try `source` field. Empty -> None.
  - `ingredients`: split on `\n`, filter empty lines

- `import_paprika_recipes(db, recipes: list[MappedRecipe]) -> ImportResult`:
  - Deduplicate within batch: `seen_urls = set()`, skip later entries with same `source_url`
  - For each recipe:
    1. Construct `RecipeCreate(**recipe.recipe_data)` — Pydantic validates
    2. If `photo_bytes`: `filename = await save_photo(photo_bytes)`
    3. Call `create_recipe(db, recipe_create)` with `photo_path`
    4. On `IntegrityError`: mark as skipped (duplicate), **delete orphan photo if saved**
    5. On any other error: mark as errored, **delete orphan photo if saved**, continue
  - Return `ImportResult`

**`src/recipe_app/main.py`** — Add routes + background task:

```python
_import_tasks: dict[str, ImportResult | None] = {}  # task_id -> result or None (in-progress)

@app.get("/import")
async def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {})

@app.post("/import")
async def import_upload(request: Request):
    # Stream-validate file size (read in chunks, reject if > MAX_IMPORT_SIZE)
    # Validate with zipfile.is_zipfile()
    task_id = uuid4().hex
    _import_tasks[task_id] = None
    db = get_db(request)
    asyncio.create_task(_run_import(task_id, file_bytes, db))
    return RedirectResponse(f"/import/status/{task_id}", status_code=303)

@app.get("/import/status/{task_id}")
async def import_status(request: Request, task_id: str):
    result = _import_tasks.get(task_id)
    if result is None:
        # Still processing — render progress page with auto-refresh
        return templates.TemplateResponse(request, "import_progress.html",
            {"task_id": task_id})
    # Done — render results, clean up task
    del _import_tasks[task_id]
    return templates.TemplateResponse(request, "import_results.html",
        {"result": result})
```

**`src/recipe_app/templates/import.html`** — New template:
- File input accepting `.paprikarecipes`
- Upload button with JS disable-on-submit + double-submit guard (check `form._submitting` flag)
- Info text: "Import your recipe library from Paprika 3."

**`src/recipe_app/templates/import_progress.html`** — New template:
- "Import in progress..." message
- `<meta http-equiv="refresh" content="5">` or `hx-trigger="every 5s"` polling
- No JS required

**`src/recipe_app/templates/import_results.html`** — New template:
- Summary: "Imported X recipes, Skipped Y duplicates, Z errors"
- If errors: flat list of recipe names + error messages
- "View Recipes" and "Import More" buttons

**`src/recipe_app/templates/base.html`** — Add "Import" link to nav

**`src/recipe_app/db.py`** — Fix pre-existing bug + add normalization:
- Lines 349, 428: change `sanitize_field(i) or i` to `sanitize_field(i)` (the `or i` fallback bypasses sanitization when bleach strips content to empty string)
- In `create_recipe()` and `update_recipe()`: normalize `source_url` empty string to `None` — defense-in-depth for all entry points

#### File Processing Pipeline

```
POST /import (.paprikarecipes file)
  -> Stream-read upload in chunks, reject if > 50MB
  -> Validate: zipfile.is_zipfile()
  -> Create background task, redirect to /import/status/{task_id}

Background task:
  -> asyncio.to_thread: zipfile.ZipFile(BytesIO(file_bytes))
     -> For each entry (max 2000):
        -> Reject path traversal (.. or absolute)
        -> Check file_size < 50MB
        -> safe_gzip_decompress(entry_bytes) with size limit
        -> json.loads(decompressed) -> paprika_dict
        -> map_paprika_recipe(paprika_dict) -> MappedRecipe
  -> import_paprika_recipes(db, mapped_recipes)
     -> Deduplicate within batch by source_url
     -> For each recipe:
        -> RecipeCreate(**recipe_data) — Pydantic validates
        -> save_photo(photo_bytes) if present -> filename
        -> create_recipe(db, recipe_create)
        -> On IntegrityError: skip, delete orphan photo
        -> On other error: log, delete orphan photo, continue
  -> Store ImportResult in _import_tasks[task_id]

GET /import/status/{task_id}
  -> If still None: render progress page (auto-refreshes every 5s)
  -> If ImportResult: render results page
```

### Field Mapping Reference

| Paprika Field | App Field | Transform |
|---|---|---|
| `name` | `title` | Direct |
| `ingredients` | `ingredients` | Split on `\n`, filter empty |
| `directions` | `directions` | Direct (preserve newlines) |
| `servings` | `servings` | Direct (string) |
| `prep_time` | `prep_time_minutes` | `parse_time_string()` |
| `cook_time` | `cook_time_minutes` | `parse_time_string()` |
| `rating` | `rating` | 0 -> None, 1-5 -> 1-5 (map BEFORE RecipeCreate) |
| `on_favorites` | `is_favorite` | Direct boolean |
| `categories` | `categories` | Direct list of strings |
| `source_url` | `source_url` | Empty -> None. Prefer over `source` field. |
| `source` | `source_url` (fallback) | Use if `source_url` is empty. Empty -> None. |
| `notes` | `notes` | Direct |
| `description` | `description` | Direct |
| `photo_data` | `photo_path` | base64 decode -> `save_photo()`. Skip on error. |
| `total_time` | -- | Discard (verify `total_time_minutes` is not generated column) |
| `nutritional_info` | -- | Discard |
| `difficulty` | -- | Not in app schema, discard |
| `uid`, `hash`, `photo_hash`, `scale` | -- | Internal Paprika fields, discard |

---

## Pre-existing Bug Fix (include in this PR)

**`db.py` lines 349 and 428:** `sanitize_field(i) or i` in ingredient sanitization falls back to the raw unsanitized value when bleach strips content to an empty string. Fix:

```python
# Before (broken):
data.ingredients = [sanitize_field(i) or i for i in data.ingredients]

# After (correct):
data.ingredients = [sanitize_field(i) for i in data.ingredients]
```

This affects all write paths (web, API, MCP), not just import. Fix as a separate commit.

---

## Acceptance Criteria

### Calendar View
- [ ] Weekly grid renders with 7 day columns x 4 meal slot rows
- [ ] Week navigation (prev/next) works via HTMX, updates URL with `?week=`
- [ ] `?week=` parameter validated as ISO date via FastAPI `date` type (422 on bad format)
- [ ] Non-Monday dates snapped to Monday of that week
- [ ] Empty plan defaults to current week
- [ ] "+" button in cell pre-fills add form with correct date and meal slot
- [ ] Adding a recipe updates the calendar grid via HTMX partial
- [ ] Removing a recipe updates the calendar grid via HTMX partial (not full-page redirect)
- [ ] `hx-sync="this:replace"` on `#calendar-grid` prevents concurrent request races
- [ ] Stale form fields cleared on every grid swap (initCalendar resets hidden fields)
- [ ] Event delegation on grid (not per-button listeners) — survives swaps
- [ ] Browser back/forward works (`htmx:historyRestore` handler calls `initAll()`)
- [ ] Multiple recipes in one cell display as vertical stack
- [ ] Today's column is visually highlighted
- [ ] Mobile: collapses to vertical day list at 600px
- [ ] MCP tool `get_meal_plan_week()` provides agent parity
- [ ] Existing meal plan API endpoints unchanged (backward compatible)

### Paprika Import
- [ ] `/import` page accessible from nav bar
- [ ] Accepts `.paprikarecipes` (ZIP) files only
- [ ] File size validated: stream-read in chunks, reject > 50MB
- [ ] Invalid files (corrupted ZIP) show clear error message
- [ ] ZIP entries validated: no path traversal, no entry > 50MB decompressed, max 2000 entries
- [ ] Gzip decompression uses size-limited incremental reader (no decompression bombs)
- [ ] Background task processes import; user redirected to polling status page
- [ ] Status page auto-refreshes until import completes
- [ ] Results page shows summary counts + flat error list
- [ ] Recipes imported with correct field mapping (see table above)
- [ ] `RecipeCreate` model constructed before DB insert (Pydantic validates)
- [ ] Photos decoded from base64 with size cap (20MB base64 limit), saved via `save_photo()`
- [ ] Orphan photo files cleaned up if DB insert fails
- [ ] Malformed base64 photos skipped with warning (recipe still imports)
- [ ] Duplicate recipes caught via `IntegrityError` on UNIQUE `source_url`, marked as skipped
- [ ] Within-batch deduplication via in-memory `seen_urls` set
- [ ] Empty `source_url` normalized to NULL (at DB layer, defense-in-depth)
- [ ] Categories auto-created from import
- [ ] Per-recipe errors caught and reported (import continues)
- [ ] Double-submit guard on import form (not just button disable)
- [ ] Pre-existing `sanitize_field(i) or i` bug fixed in `db.py`

## Dependencies & Risks

**Dependencies:**
- Photo upload infrastructure (Sprint 1) -- Already landed
- Meal plan data model -- Already complete
- `_write_lock` serialization pattern -- Established

**Risks:**
- **Large imports (1000+ recipes with photos) will be slow** — photo processing is ~1-2 sec/photo sequentially. 1000 recipes = 15-30 minutes. Background task makes this tolerable (user can close tab and check back). Future optimization: parallel photo processing with `asyncio.Semaphore(4)`.
- **Per-recipe transaction overhead** — 1000 separate lock-acquire-commit cycles. Correctness is fine; speed is the tradeoff. Future optimization: `bulk_import_recipes()` with single transaction. Not worth the complexity for MVP.
- **Write lock starvation during import** — other write operations (favorites, grocery checks) will queue behind import's repeated lock acquisitions. Reads unaffected (WAL mode).
- **Memory** — 50MB file read into memory + one decoded photo at a time. Manageable. Future optimization: stream to temp file.

## Implementation Phases

### Phase 1: Calendar View (~55% of effort)
1. Add `list_recipe_titles()` and `get_meal_plan_week()` to `db.py`
2. Register Jinja2 date filters in `main.py`
3. Update `meal_plan_detail_page` route: `week: date | None` param, snap-to-Monday, HTMX partial
4. Fix `remove_entry_submit`: add `plan_id` to URL, add `hx-request` branch
5. Update `add_recipe_to_plan_submit`: return `calendar_grid` block instead of `entries_list`
6. Rewrite `meal_plan_detail.html` with calendar grid template (incl. `hx-sync`)
7. Add calendar CSS to `style.css` (including mobile breakpoint)
8. Add `initCalendar()` to `app.js` (event delegation, form clearing, history restore)
9. Add `get_meal_plan_week` MCP tool
10. Tests: week navigation, add/remove via HTMX, empty states, bad `?week=` param, stale form clearing

### Phase 2: Paprika Import (~40% of effort)
1. Fix `sanitize_field(i) or i` bug in `db.py` (separate commit)
2. Add empty `source_url` normalization to `create_recipe()` and `update_recipe()` in `db.py`
3. Create `paprika_import.py` (security guards, parse, map, import functions, typed models)
4. Add `/import`, `/import/status/{task_id}` routes to `main.py` (background task pattern)
5. Create `import.html`, `import_progress.html`, `import_results.html` templates
6. Add "Import" to nav in `base.html`
7. Tests: archive parsing, field mapping, duplicate handling (IntegrityError), orphan photo cleanup, decompression limits, path traversal rejection, background task lifecycle

### Phase 3: Quick wins (~5% of effort)
1. Verify `total_time_minutes` is not a generated column (if it is, remove from field mapping)
2. Smoke test with a real Paprika export file if available

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-03-26-002-feat-calendar-mealplan-paprika-import-brainstorm.md](docs/brainstorms/2026-03-26-002-feat-calendar-mealplan-paprika-import-brainstorm.md) — key decisions: weekly view first, CSS grid over FullCalendar, per-cell add interaction, skip duplicates by source_url
- Existing meal plan detail template: `src/recipe_app/templates/meal_plan_detail.html`
- Photo infrastructure: `src/recipe_app/photos.py`
- Meal plan DB functions: `src/recipe_app/db.py:698-793`
- Meal plan API router: `src/recipe_app/routers/meal_plans.py`
- Web UI routes: `src/recipe_app/main.py:166-230`
- MCP meal plan tools: `src/recipe_app/mcp_server.py:277-332`
- CSS styles: `static/style.css`
- JS patterns: `static/app.js`
- FastAPI UploadFile docs: streaming size validation, SpooledTemporaryFile for files >1MB
- HTMX: `hx-sync` for request serialization, `htmx:historyRestore` for back/forward, `htmx:afterSettle` for reinit timing
- Python `zipfile`: no built-in path traversal protection — must validate entry names manually
- Pillow: `Image.MAX_IMAGE_PIXELS` already set to 50M in `photos.py:16`
