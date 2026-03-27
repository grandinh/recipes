---
title: "Calendar Meal Plan View + Paprika Import — FastAPI/HTMX Patterns"
category: implementation-patterns
date: 2026-03-27
tags: [htmx, fastapi, calendar, import, zip, background-task, css-grid, aiosqlite]
module: meal_plans, paprika_import
problem_type: implementation-patterns
severity: medium
symptoms:
  - Flat meal plan table unusable for weekly planning
  - No way to import data from Paprika 3
root_cause: Missing features — calendar UI and import pipeline
---

# Calendar Meal Plan View + Paprika Import

## Problem

The meal plan view was a flat HTML table (date|meal|recipe|remove) with no visual week structure. The app claimed to replace Paprika 3 but had no import capability.

## Key Patterns Discovered

### 1. HTMX Calendar Grid — Race Conditions and State Management

**Problem:** A calendar grid with per-cell "+" buttons that pre-fill a shared form has several frontend race conditions:

- **Stale form fields after week navigation:** The form lives outside the swapped `#calendar-grid` block. When the grid swaps via HTMX, hidden date/slot fields retain stale values from the previous week.
- **Concurrent requests:** User clicks "+" then navigates before submitting, or submits while navigation is in flight.
- **Event listener doubling:** Re-attaching listeners after HTMX swaps can create duplicates.
- **Browser back/forward:** `hx-push-url` pushes history, but `htmx:historyRestore` (not `htmx:afterSettle`) fires on back/forward.

**Solutions:**

```html
<!-- hx-sync serializes concurrent requests targeting the same element -->
<div id="calendar-grid" hx-sync="this:replace">
```

```javascript
// Flag on the grid element itself (destroyed on swap, auto-resets)
function initCalendar() {
  var grid = document.getElementById('calendar-grid');
  if (!grid || grid._calendarInitialized) return;
  grid._calendarInitialized = true;

  // Clear stale form fields on every grid swap
  var form = document.getElementById('add-recipe-form');
  if (form) {
    form.querySelector('[name="date"]').value = '';
    form.querySelector('[name="meal_slot"]').value = '';
  }

  // Event delegation on grid — one listener, survives content changes
  grid.addEventListener('click', function(e) {
    var btn = e.target.closest('.calendar-add-btn');
    if (!btn || !form) return;
    form.querySelector('[name="date"]').value = btn.dataset.date;
    form.querySelector('[name="meal_slot"]').value = btn.dataset.slot;
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// htmx:historyRestore fires on browser back/forward (not afterSettle)
document.body.addEventListener('htmx:historyRestore', function() {
  initAll();
});
```

**Key insight:** `hx-sync="this:replace"` is essential on any HTMX container that can receive concurrent requests (navigation + mutation). Without it, response ordering is unpredictable.

### 2. Background Tasks in Single-Process FastAPI

**Problem:** A synchronous import of 1000+ recipes would block the HTTP request for 15-30 minutes, causing browser timeouts.

**Solution:** `asyncio.create_task()` + polling status page (~20 extra lines):

```python
_import_tasks: dict[str, tuple[float, ImportResult | None]] = {}
_import_task_refs: set[asyncio.Task] = set()  # prevent GC

# Must store task reference or it gets garbage collected
task = asyncio.create_task(_run_import())
_import_task_refs.add(task)
task.add_done_callback(_import_task_refs.discard)
```

**Gotchas discovered:**
- `asyncio.create_task()` return value MUST be stored — Python GC will collect unreferenced tasks
- In-memory task dict needs TTL cleanup (entries persist forever if user never checks status)
- The background task uses the shared `app.state.db` connection — safe because `_write_lock` serializes all writes, but document that the connection must outlive the task (don't close DB during shutdown while import runs)

### 3. ZIP Archive Security for Untrusted Files

**Problem:** `.paprikarecipes` is a ZIP of individually gzipped JSON files. ZIP/gzip processing has multiple attack vectors.

**Required guards (all applied):**

| Guard | Attack | Implementation |
|-------|--------|---------------|
| Entry count cap | Resource exhaustion | `len(entries) > 2000` |
| Path traversal | Zip-slip | Reject `..` and leading `/` in filenames |
| Decompression size limit | Gzip bomb | Incremental read with byte counter |
| File size limit | Memory exhaustion | Stream-read upload in chunks |
| Base64 size limit | Photo decode bomb | Check `len(photo_data)` before `b64decode` |
| Context manager | Resource leak | `with zipfile.ZipFile(...) as zf:` |

**Key insight:** Python's `zipfile` module does NOT protect against path traversal. You must manually validate entry filenames. Also, `gzip.decompress()` loads everything into memory — use incremental `GzipFile.read(chunk_size)` with a size counter instead.

### 4. sanitize_field() Bypass via Falsy Empty String

**Pre-existing bug found during import development:**

```python
# BROKEN — bleach strips content to "" (falsy), falls through to raw input
data.ingredients = [sanitize_field(i) or i for i in data.ingredients]

# FIXED
data.ingredients = [sanitize_field(i) for i in data.ingredients]
```

`sanitize_field()` returns `""` (empty string) when bleach strips all content. Since `""` is falsy in Python, `or i` evaluates to the unsanitized original. This is a real XSS bypass affecting all write paths.

**Prevention:** Never use `sanitize(x) or x` patterns. If sanitization returns empty, that IS the correct value.

### 5. HTMX Partial Optimization — Don't Query Data for Elements Outside the Swap Target

**Problem:** `_render_calendar_grid()` was calling `list_recipe_titles()` on every HTMX partial swap, but the recipe `<select>` dropdown lives OUTSIDE the `#calendar-grid` block and isn't re-rendered.

**Fix:** Only load `all_recipes` when rendering the full page:

```python
all_recipes = await list_recipe_titles(db) if block_name is None else []
```

**Prevention:** When building HTMX partial render helpers, audit which template variables are actually inside the rendered block. Don't query for data that won't be used.

### 6. Paprika Field Mapping — Rating 0 Must Be None Before Pydantic

Paprika uses `rating: 0` for unrated recipes. The app's Pydantic model has `rating: int | None = Field(None, ge=1, le=5)`. Passing `rating=0` to `RecipeCreate()` raises a ValidationError.

**Fix:** Map 0 to None in the field mapping step, BEFORE constructing the Pydantic model:

```python
raw_rating = paprika.get("rating")
rating = None
if raw_rating and isinstance(raw_rating, (int, float)) and 1 <= raw_rating <= 5:
    rating = int(raw_rating)
```

### 7. source_url Empty String vs NULL in UNIQUE Columns

SQLite's UNIQUE constraint treats each NULL as distinct (multiple NULLs allowed) but treats empty strings as equal (second `""` violates UNIQUE). Paprika recipes without URLs need `source_url = None`, not `""`.

**Defense-in-depth:** Normalize at the DB layer so all entry points (web, API, MCP, import) are covered:

```python
if data.source_url is not None and not data.source_url.strip():
    data.source_url = None
```

## Prevention

- Always use `hx-sync` on HTMX containers that can receive concurrent requests
- Store `asyncio.create_task()` return values to prevent GC
- Use context managers for `zipfile.ZipFile` — don't rely on manual `.close()`
- Never use `sanitize(x) or x` patterns
- Validate ZIP entry filenames manually (Python doesn't protect against zip-slip)
- Normalize empty strings to NULL for UNIQUE columns at the DB layer
- Test Pydantic model construction with edge values (0, empty string) before the DB layer

## Files Changed

- `src/recipe_app/db.py` — sanitize_field fix, source_url normalization, get_meal_plan_week, list_recipe_titles
- `src/recipe_app/main.py` — calendar routes, import routes with background task, _render_calendar_grid
- `src/recipe_app/paprika_import.py` — new module: archive parsing, field mapping, import orchestration
- `src/recipe_app/mcp_server.py` — get_meal_plan_week tool, grocery item MCP tools
- `src/recipe_app/templates/meal_plan_detail.html` — calendar grid template
- `static/app.js` — initCalendar with event delegation, historyRestore handler
- `static/style.css` — calendar grid styles with mobile responsive

## Related

- PR: grandinh/recipes#3
- Plan: `docs/plans/2026-03-26-002-feat-calendar-mealplan-paprika-import-plan.md`
- Brainstorm: `docs/brainstorms/2026-03-26-002-feat-calendar-mealplan-paprika-import-brainstorm.md`
- Prior test coverage learnings: `docs/solutions/test-failures/comprehensive-test-coverage-fastapi-recipe-app.md`
