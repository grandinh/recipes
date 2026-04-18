---
title: "fix: Sprint 1 — Fix Broken and Stubbed Features"
type: fix
status: completed
date: 2026-03-26
deepened: 2026-03-26
---

# Sprint 1: Fix Broken and Stubbed Features

## Enhancement Summary

**Deepened on:** 2026-03-26
**Agents used:** 10 (security-sentinel, architecture-strategist, performance-oracle, kieran-python-reviewer, julik-frontend-races-reviewer, pattern-recognition-specialist, agent-native-reviewer, best-practices-researcher, framework-docs-researcher, data-integrity-guardian)

### Key Improvements
1. **Photo upload: `asyncio.to_thread()` is mandatory** — Pillow is CPU-bound and blocks the event loop for 200-500ms on a 10MB photo. Also must handle RGBA→RGB conversion for PNG/WebP inputs.
2. **Favorite toggle: send desired state, not server-side flip** — read-then-flip has a race condition. Send `is_favorite=true/false` from client (match grocery checkbox pattern). Alternatively, use atomic `UPDATE SET is_favorite = 1 - is_favorite` in a dedicated DB function.
3. **Star rating: single HTMX element, not 5 forms** — 5 separate forms cause out-of-order response overwrites. Use one container with `hx-trigger="click from:find .rating-star-btn"` and a hidden input. CSS `:has()` handles hover preview without JS.
4. **JS lifecycle: all inits must be idempotent and re-run on `htmx:afterSettle`** — `DOMContentLoaded` fires once but `hx-boost` navigation replaces content without reloading. Cooking mode's DOM references die after scaling section swap.
5. **MCP parity: `base_servings` must be added to `mcp_server.py` manually** — MCP tools enumerate params explicitly, not derived from Pydantic. Also need `upload_recipe_photo` MCP tool for agent photo upload.

### New Considerations Discovered
- `form.get("photo")` returns `""` (not `None`) when no file selected — must guard with `isinstance(photo, UploadFile) and photo.filename`
- RGBA images (PNG, WebP) crash on JPEG save — must composite onto white background first
- Omit `exif=` kwarg when saving JPEG to strip metadata — passing `exif=img.info.get("exif")` preserves GPS data
- Use temp-file-then-rename pattern for photo writes — prevents orphaned files on DB failure
- `htmx:afterSettle` (not `afterSwap`) for JS re-init — afterSwap fires before settle phase completes
- Template block nesting confirmed working — jinja2-fragments flattens all blocks into single dict
- `.pantry-expiry.expired` CSS class is a bug fix — template already emits the class but CSS rule is missing
- Rating CHECK constraint already exists in schema (`CHECK(rating BETWEEN 1 AND 5)`) — no migration needed
- Category CRUD functions missing `_write_lock` — pre-existing bug, noted but not in scope

## Overview

Five features in the recipe app are broken or stubbed out — the UI suggests they work but they don't. This sprint fixes all five, prioritized by impact. The backend data model and DB layer are solid; the gaps are in form handlers, template wiring, and missing endpoints.

## Problem Statement / Motivation

The Paprika parity gap analysis identified these as Tier 1 issues — partially built features that create a broken UX. Photo upload has a form that silently drops files. The scaling base servings button 405s. The favorite heart is decorative. Stars require a full form edit to change. Pantry expiration dates never highlight. Each is a small fix individually but collectively they make the app feel unfinished.

## Proposed Solution

Fix each feature with the minimum viable change, following existing codebase patterns (HTMX partials via `block_name`, dual-mode routes with `hx_request` check, Pydantic models for validation, `_write_lock` for DB writes).

---

## Technical Approach

### Feature 1: Photo Upload Handler

**Problem:** `recipe_form.html` has `enctype="multipart/form-data"` and `<input type="file" name="photo">` but neither `_form_to_recipe_create()` nor `_form_to_recipe_update()` reads the file. Pillow is already a dependency (`Pillow==12.1.1` in pyproject.toml).

**Implementation:**

- [ ] Add `photo_path: str | None = None` and `base_servings: int | None = Field(None, ge=1, le=100)` to `_RecipeFields` base class in `models.py` (so both Create and Update inherit them). Add both to `RecipeResponse` as well.
- [ ] Create `src/recipe_app/photos.py` module with `from __future__ import annotations` and module docstring (matching `scaling.py`/`scraper.py` pattern):

  ```python
  """Photo upload processing — validation, re-encoding, and thumbnail generation."""
  from __future__ import annotations

  import io
  import uuid
  from pathlib import Path

  from PIL import Image, ImageOps

  from .config import settings

  # Tighten decompression bomb guard (default is ~179M pixels)
  Image.MAX_IMAGE_PIXELS = 50_000_000

  def process_photo_sync(raw_bytes: bytes) -> tuple[str, bytes, bytes]:
      """Validate, sanitize, and re-encode an uploaded image.

      Returns (filename, original_bytes, thumbnail_bytes).
      Raises ValueError on invalid/corrupt input.
      """
      # Step 1: verify() for fast structural rejection
      try:
          probe = Image.open(io.BytesIO(raw_bytes))
          probe.verify()  # checks header, consumes file handle
      except Exception as e:
          raise ValueError(f"Invalid image file: {e}")

      # Step 2: re-open and fully decode (catches truncated files)
      try:
          img = Image.open(io.BytesIO(raw_bytes))
          img.load()
      except Exception as e:
          raise ValueError(f"Corrupt image data: {e}")

      # Step 3: EXIF transpose (fixes phone rotation) — must call before resize
      img = ImageOps.exif_transpose(img)

      # Step 4: convert to RGB (RGBA/CMYK/P/L can't save as JPEG)
      if img.mode in ("RGBA", "PA"):
          background = Image.new("RGB", img.size, (255, 255, 255))
          background.paste(img, mask=img.split()[3])
          img = background
      elif img.mode == "P":
          img = img.convert("RGBA")
          background = Image.new("RGB", img.size, (255, 255, 255))
          background.paste(img, mask=img.split()[3])
          img = background
      elif img.mode != "RGB":
          img = img.convert("RGB")

      # Step 5: constrain original to max 2048px
      img.thumbnail((2048, 2048), Image.LANCZOS)

      filename = f"{uuid.uuid4().hex}.jpg"

      # Step 6: save original — omit exif= kwarg to strip ALL metadata
      orig_buf = io.BytesIO()
      img.save(orig_buf, "JPEG", quality=85, optimize=True)

      # Step 7: generate thumbnail
      thumb = img.copy()
      thumb.thumbnail((400, 400), Image.LANCZOS)
      thumb_buf = io.BytesIO()
      thumb.save(thumb_buf, "JPEG", quality=80, optimize=True)

      return filename, orig_buf.getvalue(), thumb_buf.getvalue()
  ```

- [ ] Add async wrapper in `photos.py`:

  ```python
  import asyncio

  async def save_photo(raw_bytes: bytes) -> str:
      """Process and save photo. Returns filename. Runs Pillow in thread pool."""
      filename, orig_bytes, thumb_bytes = await asyncio.to_thread(
          process_photo_sync, raw_bytes
      )
      # File I/O also in thread to avoid blocking event loop
      orig_path = settings.photo_dir / "originals" / filename
      thumb_path = settings.photo_dir / "thumbnails" / filename
      await asyncio.to_thread(orig_path.write_bytes, orig_bytes)
      await asyncio.to_thread(thumb_path.write_bytes, thumb_bytes)
      return filename

  def delete_photo(filename: str) -> None:
      """Best-effort delete of original + thumbnail files."""
      (settings.photo_dir / "originals" / filename).unlink(missing_ok=True)
      (settings.photo_dir / "thumbnails" / filename).unlink(missing_ok=True)
  ```

- [ ] Update form handlers in `main.py`:

  ```python
  from starlette.datastructures import UploadFile

  @app.post("/add")
  async def add_recipe_submit(request: Request):
      db = get_db(request)
      form = await request.form()
      recipe_data = _form_to_recipe_create(form)
      result = await create_recipe(db, recipe_data)

      # Handle photo upload separately (outside _write_lock)
      photo = form.get("photo")
      if isinstance(photo, UploadFile) and photo.filename:
          raw = await photo.read()
          if len(raw) > settings.max_photo_size:
              # Redirect with error — or flash message
              return RedirectResponse(f"/recipe/{result['id']}", status_code=303)
          try:
              filename = await save_photo(raw)
              await update_recipe(db, result['id'], RecipeUpdate(photo_path=filename))
          except ValueError:
              pass  # Invalid image — recipe created without photo

      return RedirectResponse(f"/recipe/{result['id']}", status_code=303)
  ```

- [ ] On edit with existing photo: fetch old `photo_path` before update, call `delete_photo(old)` after successful DB update
- [ ] On recipe delete in `delete_recipe_submit()`: fetch recipe first, delete DB row, then `delete_photo()` for cleanup
- [ ] Fix `/photos` static mount race condition: ensure photo dirs exist before `app.mount()` by calling `settings.photo_dir.mkdir(parents=True, exist_ok=True)` at module level (before app creation)

**Key files:**
- `src/recipe_app/photos.py` (new — ~80 lines)
- `src/recipe_app/main.py:360-382` (form handlers + delete handler)
- `src/recipe_app/models.py:7-66` (add fields to `_RecipeFields` and `RecipeResponse`)

**Security considerations:**
- `Image.verify()` + `img.load()` two-step validation (verify checks header, load forces full decode)
- RGBA→RGB conversion with white background (prevents JPEG save crash on PNG/WebP with alpha)
- Omit `exif=` kwarg on `img.save()` to strip ALL EXIF metadata including GPS
- UUID filenames derived server-side — never use user-supplied filename
- `MAX_IMAGE_PIXELS = 50_000_000` decompression bomb guard
- File size checked against `settings.max_photo_size` before Pillow processing
- Re-encoding destroys polyglot payloads

**Performance considerations:**
- All Pillow processing via `asyncio.to_thread()` — prevents 200-500ms event loop stall
- File I/O also in thread pool — prevents minor stalls on disk writes
- Photo processing happens BEFORE `_write_lock` — DB lock held only for the brief `UPDATE SET photo_path` statement

---

### Feature 2: Fix Base Servings PUT/PATCH Mismatch

**Problem:** Four bugs stack: (1) `hx-put` but only PATCH exists → 405, (2) `hx-vals='{"base_servings": ""}'` hardcodes empty string, (3) input has no `name` attribute so `hx-include` can't find it, (4) `RecipeUpdate` model has no `base_servings` field.

**Implementation:**

- [ ] `base_servings` added to `_RecipeFields` in Feature 1's model changes (inherited by `RecipeUpdate`)
- [ ] Add `POST /recipe/{recipe_id}/base-servings` web route in `main.py` (under a new `# --- Recipe inline actions ---` section comment):
  - Accept form data with `base_servings` integer (with try/except for `ValueError`)
  - Call `update_recipe(db, recipe_id, RecipeUpdate(base_servings=value))`
  - If `hx_request`: re-fetch recipe, return `recipe_detail.html` with `block_name="scaling_section"`
  - Else: redirect to `/recipe/{recipe_id}`
  - Must use `hx_request: Annotated[str | None, Header()] = None` matching existing pattern
- [ ] Fix `recipe_detail.html` lines 109-119:
  - Remove the broken `hx-put`, `hx-include`, `hx-vals`, and `hx-disabled-elt` attributes from the button
  - Replace with a proper `<form>` that POSTs to the new web route:
    ```html
    <form method="post" action="/recipe/{{ recipe.id }}/base-servings"
          hx-post="/recipe/{{ recipe.id }}/base-servings"
          hx-target="closest .scaling-section" hx-swap="outerHTML"
          class="inline-form servings-prompt">
      <em>Set base servings to enable scaling:</em>
      <input type="number" name="base_servings" min="1" max="100"
             placeholder="e.g. 4" class="input input-sm" style="width: 80px; display: inline-block;">
      <button type="submit" class="btn btn-sm btn-secondary"
              hx-disabled-elt="this">Set</button>
    </form>
    ```
- [ ] Wrap the scaling section in `{% block scaling_section %}...{% endblock %}`

**JS re-initialization after swap:**

- [ ] Add global `htmx:afterSettle` handler in `app.js` that checks what was swapped and re-inits:
  ```javascript
  document.body.addEventListener("htmx:afterSettle", function(evt) {
      var target = evt.detail.target;
      if (target.querySelector("#scaleButtons") || target.id === "scaleButtons") {
          initScaling();
      }
      if (target.querySelector("#rating-widget") || target.id === "rating-widget") {
          initQuickRate();
      }
  });
  ```
- [ ] Make `initScaling()` idempotent with a guard: `if (scaleButtons._scalingInitialized) return;`
- [ ] **Fix cooking mode zombie references**: move ingredient click handling to event delegation on a stable ancestor outside the swap target (e.g., `document` or `.recipe-detail`) so listeners survive scaling section swaps
- [ ] Also call `initAll()` on `htmx:afterSettle` for `hx-boost` navigation (DOMContentLoaded only fires once)

**Key files:**
- `src/recipe_app/templates/recipe_detail.html:90-121`
- `src/recipe_app/models.py:7-25` (already handled in Feature 1)
- `src/recipe_app/main.py` (new route)
- `static/app.js` (afterSettle handler, idempotent inits, event delegation)

---

### Feature 3: Favorite Toggle from UI

**Problem:** Heart icon at `recipe_detail.html:10-12` is a plain `<span>` with `cursor: default`. No toggle endpoint exists.

**Implementation:**

- [ ] Add `toggle_favorite()` function to `db.py` (atomic SQL, avoids FTS5 churn):
  ```python
  async def toggle_favorite(db: aiosqlite.Connection, recipe_id: int) -> dict | None:
      """Atomically flip is_favorite. Returns updated recipe dict or None."""
      async with _write_lock:
          cursor = await db.execute(
              "UPDATE recipes SET is_favorite = 1 - is_favorite WHERE id = ?",
              (recipe_id,),
          )
          await db.commit()
      if cursor.rowcount == 0:
          return None
      return await get_recipe(db, recipe_id)
  ```
- [ ] Add `POST /recipe/{recipe_id}/favorite` route in `main.py`:
  - Call `toggle_favorite(db, recipe_id)` (single atomic SQL, no read-then-flip race)
  - If `hx_request`: return `recipe_detail.html` with `block_name="favorite_toggle"`
  - Else: redirect to `/recipe/{recipe_id}`
- [ ] Wrap the heart in `recipe_detail.html` with `{% block favorite_toggle %}` (renamed from `favorite_btn` per pattern review — block names describe content regions):
  ```html
  {% block favorite_toggle %}
  <form method="post" action="/recipe/{{ recipe.id }}/favorite"
        hx-post="/recipe/{{ recipe.id }}/favorite"
        hx-target="this" hx-swap="outerHTML"
        hx-disabled-elt="find button"
        class="inline-form">
    <button type="submit" class="favorite-toggle"
            title="{% if recipe.is_favorite %}Remove from favorites{% else %}Add to favorites{% endif %}">
      {% if recipe.is_favorite %}&#9829;{% else %}&#9825;{% endif %}
    </button>
  </form>
  {% endblock %}
  ```
- [ ] Update CSS: `.favorite-toggle` with `cursor: pointer`, no border/background, `font-size: 1.5rem`, `color: var(--color-danger)`

**Why atomic toggle instead of send-desired-state:** The architecture review and data integrity review both recommended `UPDATE SET is_favorite = 1 - is_favorite` — it's a single SQL statement, holds `_write_lock` for <1ms, avoids FTS5 churn from `update_recipe()`, and is race-free. The `outerHTML` swap on the form means HTMX's request queuing naturally handles rapid clicks (second click's form is destroyed by the first response's swap).

**Scope decision:** Skip home page card grid. Cards are wrapped in `<a>` tags — restructuring deferred.

**Key files:**
- `src/recipe_app/db.py` (new `toggle_favorite()`)
- `src/recipe_app/main.py` (new route)
- `src/recipe_app/templates/recipe_detail.html:9-13`
- `static/style.css:194`

---

### Feature 4: Quick-Rate from Detail Page

**Problem:** Stars at `recipe_detail.html:79-86` are plain text in a `<span>`. No inline rating update exists. When `rating` is NULL, the entire section is hidden.

**Implementation:**

- [ ] Add `set_rating()` function to `db.py` (avoids FTS5 churn, like `toggle_favorite`):
  ```python
  async def set_rating(db: aiosqlite.Connection, recipe_id: int, rating: int) -> dict | None:
      """Set recipe rating (1-5). Returns updated recipe dict or None."""
      async with _write_lock:
          cursor = await db.execute(
              "UPDATE recipes SET rating = ? WHERE id = ?",
              (rating, recipe_id),
          )
          await db.commit()
      if cursor.rowcount == 0:
          return None
      return await get_recipe(db, recipe_id)
  ```
- [ ] Add `POST /recipe/{recipe_id}/rate` route in `main.py`:
  - Parse and validate `rating` (1-5 integer, try/except ValueError → 400)
  - Call `set_rating(db, recipe_id, rating)`
  - If `hx_request`: return `recipe_detail.html` with `block_name="rating_widget"`
  - Else: redirect to `/recipe/{recipe_id}`
- [ ] **Use single HTMX element pattern** (not 5 separate forms — prevents out-of-order response overwrites):
  ```html
  {% block rating_widget %}
  <div class="meta-item" id="rating-widget"
       hx-post="/recipe/{{ recipe.id }}/rate"
       hx-target="this" hx-swap="outerHTML"
       hx-trigger="click from:find .rating-star-btn"
       hx-disabled-elt="find .rating-star-btn">
    <span class="meta-label">Rating</span>
    <input type="hidden" name="rating" id="ratingValue" value="{{ recipe.rating or 0 }}">
    <div class="rating-stars-interactive">
      {% for i in range(1, 6) %}
        <button type="button" class="rating-star-btn {% if recipe.rating and i <= recipe.rating %}filled{% endif %}"
                data-rating="{{ i }}"
                title="Rate {{ i }} star{{ 's' if i > 1 else '' }}">
          {% if recipe.rating and i <= recipe.rating %}&#9733;{% else %}&#9734;{% endif %}
        </button>
      {% endfor %}
    </div>
  </div>
  {% endblock %}
  ```
- [ ] **Always show the rating widget** — remove the `{% if recipe.rating %}` guard so unrated recipes show 5 empty stars
- [ ] Add `initQuickRate()` in `app.js` — sets hidden input value on click before HTMX fires:
  ```javascript
  function initQuickRate() {
      // Event delegation on document — survives any HTMX swap
      if (initQuickRate._bound) return;  // idempotent guard
      initQuickRate._bound = true;
      document.addEventListener("click", function(e) {
          var btn = e.target.closest(".rating-star-btn");
          if (!btn) return;
          var input = btn.closest("#rating-widget").querySelector("#ratingValue");
          if (input) input.value = btn.dataset.rating;
      });
  }
  ```
- [ ] **Use CSS for hover preview** (no JS needed — survives DOM swaps, zero cleanup):
  ```css
  .rating-stars-interactive {
      display: flex;
      flex-direction: row-reverse;
      justify-content: flex-end;
      gap: 0.1em;
  }
  .rating-star-btn {
      background: none; border: none; cursor: pointer;
      font-size: 1.25rem; color: var(--color-border);
      padding: 0.25rem; min-width: 44px; min-height: 44px;
      line-height: 1; text-align: center;
  }
  .rating-star-btn.filled { color: var(--color-star); }
  /* Hover preview: highlight hovered star and all before it (visually after in reversed flex) */
  .rating-star-btn:hover,
  .rating-star-btn:hover ~ .rating-star-btn { color: var(--color-star); }
  ```
  Note: Stars are rendered 5→1 in HTML but displayed 1→5 via `flex-direction: row-reverse`. The `~` sibling combinator selects all stars "after" the hovered one in source order (which appear "before" it visually), achieving the left-fill hover effect.

**Key files:**
- `src/recipe_app/db.py` (new `set_rating()`)
- `src/recipe_app/main.py` (new route)
- `src/recipe_app/templates/recipe_detail.html:79-86`
- `static/style.css` (`.rating-star-btn`, `.rating-stars-interactive`)
- `static/app.js` (`initQuickRate()` — event delegation, idempotent)

---

### Feature 5: Pantry Expiration Date Display

**Problem:** Template uses `now` variable that is never passed. Three render paths all omit it. `.pantry-expiry.expired` CSS rule is missing despite template already emitting the class.

**Implementation:**

- [ ] Pass date context in all three pantry template render paths:
  ```python
  from datetime import date, timedelta

  def _pantry_context() -> dict:
      today = date.today().isoformat()
      return {"now": today, "now_plus_7": (date.today() + timedelta(days=7)).isoformat()}
  ```
  Call in `pantry_page()`, `add_pantry_submit()`, and `delete_pantry_submit()`:
  ```python
  context = {"items": items, **_pantry_context()}
  ```
- [ ] Add `.pantry-expiry.expired` and `.pantry-expiry.expiring-soon` CSS rules:
  ```css
  .pantry-expiry.expired { font-weight: 700; background: #fde8e8; padding: 0.1rem 0.4rem; border-radius: 4px; }
  .pantry-expiry.expiring-soon { color: #d4a017; font-weight: 600; }
  ```
- [ ] Update template conditional in `pantry.html:42-45`:
  ```html
  {% if item.expiration_date %}
    {% set exp_class = 'expired' if item.expiration_date < now else ('expiring-soon' if item.expiration_date <= now_plus_7 else '') %}
    <span class="pantry-expiry {{ exp_class }}">
      Exp: {{ item.expiration_date }}
    </span>
  {% endif %}
  ```
- [ ] Add optional expiration date input to pantry quick-add form:
  ```html
  <input type="date" name="expiration_date" class="input" style="width: auto;"
         placeholder="Expiration (optional)">
  ```
- [ ] Update `add_pantry_submit()` to pass `expiration_date` from form to `add_pantry_item()`

**Key files:**
- `src/recipe_app/main.py:300-339` (three route handlers + helper)
- `src/recipe_app/templates/pantry.html:15-23` (form), `42-45` (display)
- `static/style.css:283` (expiry styles)

---

## System-Wide Impact

- **Pydantic model changes:** Adding `base_servings` and `photo_path` to `_RecipeFields` and `RecipeResponse`. Backwards compatible — new nullable fields only.
- **New DB functions:** `toggle_favorite()` and `set_rating()` — atomic single-statement updates that skip FTS5 churn. Reduces DB round trips from 6+ to 2 per operation.
- **New routes:** 3 POST routes (`/recipe/{id}/favorite`, `/recipe/{id}/rate`, `/recipe/{id}/base-servings`) under a `# --- Recipe inline actions ---` section in `main.py`. All follow dual-mode pattern.
- **New module:** `photos.py` — stateless utility module. Accepts bytes, returns filename + processed bytes. No DB or request knowledge.
- **Template blocks:** 3 named blocks (`scaling_section`, `favorite_toggle`, `rating_widget`). jinja2-fragments confirmed to support nested blocks.
- **JS overhaul:** All `init*()` functions must be idempotent. Global `htmx:afterSettle` handler for re-init after swaps and `hx-boost` navigation. Cooking mode refactored to use event delegation on stable ancestor.
- **MCP parity gap:** `base_servings` must be added to `create_recipe` and `update_recipe` tools in `mcp_server.py` (manually enumerated params). `upload_recipe_photo` MCP tool is out of scope for this sprint but noted for Sprint 4.

### Interaction Graph

Photo upload → `asyncio.to_thread(process_photo_sync)` → file writes → `update_recipe(photo_path=)` → `_write_lock` → DB UPDATE → FTS update
Favorite toggle → `toggle_favorite()` → `_write_lock` → `UPDATE SET is_favorite = 1 - is_favorite` → no FTS
Quick rate → `set_rating()` → `_write_lock` → `UPDATE SET rating = ?` → no FTS
Base servings → `update_recipe(base_servings=)` → `_write_lock` → DB UPDATE → FTS update (acceptable — infrequent)

### Error Propagation

- Photo: `ValueError` from `process_photo_sync` → caught in route → recipe created without photo (graceful degradation)
- Photo size: checked before Pillow processing → 413 or redirect with error
- Rating/base_servings: `ValueError` from `int()` → caught → 400 or redirect
- Toggle/rate on nonexistent recipe: DB function returns `None` → route returns 404

## Acceptance Criteria

- [ ] Uploading a JPEG/PNG/WebP photo on the add/edit form saves the original and generates a 400px thumbnail
- [ ] PNG/WebP with alpha channels are composited onto white background before JPEG conversion
- [ ] Uploaded photos display on the detail page and as thumbnails in the recipe grid
- [ ] Invalid files (wrong type, too large, corrupt) return a user-friendly error, recipe is still created without photo
- [ ] EXIF metadata (including GPS) is stripped from saved photos
- [ ] Old photo files are cleaned up when replacing or deleting a recipe
- [ ] The "Set base servings" button updates the value and the scaling section re-renders with active scaling buttons
- [ ] Scaling and cooking mode both work after the scaling section is HTMX-swapped
- [ ] Clicking the heart icon on recipe detail toggles `is_favorite` and swaps the icon without page reload
- [ ] Clicking a star on recipe detail sets the rating and updates the star display inline
- [ ] Unrated recipes show 5 empty clickable stars
- [ ] Hover over stars shows a preview of the rating (via CSS, no JS)
- [ ] Stars have minimum 44x44px touch targets for mobile
- [ ] Pantry items with past expiration dates are highlighted as "expired"
- [ ] Pantry items expiring within 7 days are highlighted as "expiring soon"
- [ ] The pantry quick-add form includes an optional expiration date field
- [ ] All new routes work with and without JavaScript (HTMX partial or redirect fallback)
- [ ] All new routes pass existing test suite (`uv run pytest`)
- [ ] `hx-boost` navigation doesn't break interactive features (all inits re-run on `htmx:afterSettle`)

## Dependencies & Risks

- **Pillow is already installed** (`Pillow==12.1.1`) — no new dependencies needed
- **Photo mount race condition:** Ensure photo dirs exist before `app.mount()` at module level
- **MCP param drift:** `mcp_server.py` manually enumerates tool params. Must update when adding `base_servings` to models. Photo upload MCP tool deferred to Sprint 4.
- **Cooking mode fragility:** Refactoring ingredient click handling to event delegation is a prerequisite for the scaling section swap to work correctly. Test cooking mode after every scaling-related change.

## Sources & References

- **Existing plan doc:** `docs/plans/2026-03-25-001-feat-v02-v03-htmx-scaling-mealplan-photos-ocr-pantry-plan.md` — photo upload security, HTMX patterns
- **Test coverage solution:** `docs/solutions/test-failures/comprehensive-test-coverage-fastapi-recipe-app.md` — known bugs (form int() crash, missing sanitization)
- **Pillow docs:** `Image.verify()` (closes file handle — must re-open), `ImageOps.exif_transpose()`, `Image.thumbnail()` (modifies in-place), JPEG RAWMODE excludes RGBA
- **HTMX docs:** `hx-disabled-elt`, `hx-trigger="click from:find ..."`, `hx-sync`, `htmx:afterSettle` event timing
- **jinja2-fragments:** Nested blocks confirmed — Jinja2 flattens all blocks into `template.blocks` dict
- **W3C APG:** Star rating radio group pattern, `.visually-hidden` utility class
- **FastAPI docs:** `UploadFile | None = None` for optional file upload, `request.form()` returns UploadFile for file fields
