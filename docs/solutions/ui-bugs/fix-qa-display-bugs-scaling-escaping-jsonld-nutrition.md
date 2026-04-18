---
title: "Fix QA bugs: scaling, double-escaping, scraper data leaks, nutrition formatting"
category: ui-bugs
date: 2026-03-27
tags:
  - jinja2
  - bleach
  - html-escaping
  - recipe-scrapers
  - ingredient-scaling
  - nutrition
  - data-quality
  - input-validation
areas:
  - templates
  - sanitization
  - scraping
  - grocery-list
severity: moderate
related:
  - docs/solutions/implementation-patterns/grocery-management-mcp-web-parity-code-review.md
  - docs/solutions/implementation-patterns/grocery-aggregation-pipeline-and-code-review-fixes.md
  - docs/solutions/implementation-patterns/calendar-view-paprika-import-fastapi-htmx.md
  - docs/solutions/test-failures/comprehensive-test-coverage-fastapi-recipe-app.md
---

# Fix QA Display Bugs: Scaling, Double-Escaping, JSON-LD Leak, Nutrition Labels

## Problem Summary

QA testing of the recipe app's web UI uncovered four display bugs spanning template rendering, input sanitization, upstream scraper data handling, and display formatting. A fifth validation gap was caught during code review of the fixes. All issues affected the web UI; the shared ingestion/DB layers meant some also affected MCP tool responses.

## Bug 1: Ingredient Scaling Broken — HTML Attribute Quoting

**Symptom:** Clicking scale buttons (x2, x3, etc.) on recipe detail page did nothing. `dataset.ingredients` contained only `"["` instead of the full JSON array.

**Root Cause:** `data-ingredients="{{ recipe.ingredients | tojson }}"` — Jinja2's `tojson` filter produces JSON with double-quoted strings. Inside a double-quoted HTML attribute, the first `"` in the JSON terminates the attribute. The browser parsed `data-ingredients="["` and treated the remaining JSON as bogus HTML attributes.

**Fix** (`recipe_detail.html:123`):

```html
<!-- BEFORE (broken) -->
data-ingredients="{{ recipe.ingredients | tojson }}">

<!-- AFTER (fixed) -->
data-ingredients='{{ recipe.ingredients | tojson }}'>
```

**Key Pattern:** Always use single-quoted HTML attributes when the value contains JSON from `tojson`. Alternatively, use `{{ value | tojson | e }}` with double quotes for full robustness.

## Bug 2: Double HTML-Escaping on Grocery Aisle Headers

**Symptom:** Aisle headers rendered as "DAIRY &AMP; EGGS" instead of "Dairy & Eggs".

**Root Cause:** Two-stage encoding:
1. `sanitize_field()` calls `bleach.clean()`, encoding `&` to `&amp;` at write time
2. Jinja2 autoescaping re-encodes: `&amp;` becomes `&amp;amp;` at render time

Aisle names like "Dairy & Eggs" come from a controlled allowlist in `aisle_map.py`, not user HTML input. Sanitizing them with bleach was unnecessary.

**Fix** (`db.py`, `aisle_map.py`):

- Removed `sanitize_field()` from 3 call sites handling aisle names (aggregation pipeline, manual add, move-to-pantry)
- Added `VALID_AISLES` frozenset for allowlist validation of user-supplied values
- Fixed corrupted DB data: `UPDATE grocery_list_items SET aisle = REPLACE(aisle, '&amp;', '&') WHERE aisle LIKE '%&amp;%'`

```python
# aisle_map.py — new allowlist
VALID_AISLES: frozenset[str] = frozenset(
    aisle for aisle, _ in _AISLE_DATA
) | {"Other"}

# db.py — allowlist validation for user-supplied aisle
if aisle is None:
    from recipe_app.aisle_map import assign_aisle
    aisle = assign_aisle(text)[0]
else:
    from recipe_app.aisle_map import VALID_AISLES
    if aisle not in VALID_AISLES:
        aisle = "Other"
```

**Key Pattern:** Never HTML-encode plain-text data at storage time when the template engine will autoescap on render. For enumerated values, use allowlist validation instead of sanitization.

## Bug 3: JSON-LD Schema Keys Leaking into Directions

**Symptom:** Some scraped recipes showed `@type`, `text`, `url` as visible direction steps.

**Root Cause:** Upstream `recipe_scrapers` library bug — when `HowToStep.itemListElement` is a dict instead of a list, iterating it yields dict keys as strings instead of instruction text.

**Fix** (`scraper.py`):

```python
_jsonld_junk = {"@type", "text", "url", "@context", "@id", "name", "image"}
lines = [
    ln for ln in raw_instructions.split("\n")
    if ln.strip() not in _jsonld_junk
]
directions = sanitize_field("\n".join(lines)) or None
```

**Key Pattern:** Always post-process upstream scraper output. Third-party parsers can emit structured data metadata as text when encountering unexpected schema formats.

## Bug 4: Raw Schema.org Nutrition Field Names

**Symptom:** Nutrition section showed `carbohydrateContent: 25.6 grams` instead of `Carbohydrate: 25.6 grams`.

**Root Cause:** `scraper.nutrients()` returns raw schema.org property names. No formatting was applied before storage.

**Fix** (`scraper.py`):

```python
def _format_nutrition(raw: dict) -> dict:
    """Convert schema.org nutrient keys to human-readable labels."""
    _skip = {"@type", "@context", "servingSize"}
    out = {}
    for key, val in raw.items():
        if key in _skip or not val:
            continue
        label = re.sub(r"Content$", "", key)              # Strip "Content" suffix
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", label)  # camelCase to spaces
        label = label.replace("_", " ").strip().title()
        out[label] = val
    return out
```

**Key Pattern:** Schema.org field names follow a predictable `fooContent` convention. A single regex pipeline handles all nutrition keys without a manual mapping table.

## Bug 5: Aisle Validation Gap (Found in Code Review)

**Symptom:** After removing `sanitize_field()` from aisles (Bug 2 fix), user-supplied values via API/MCP had no validation. Three independent review agents flagged this.

**Fix:** Added `VALID_AISLES` frozenset and allowlist validation — unknown values map to "Other" (see Bug 2 fix above).

**Key Pattern:** When removing a security control, always add the replacement control in the same change. Allowlist validation is stronger than sanitization for enumerated values.

## Prevention Strategies

### JSON in HTML Attributes
- Use single-quoted attributes for `tojson` output: `data-foo='{{ val | tojson }}'`
- For maximum robustness: `data-foo="{{ val | tojson | e }}"`
- CI check: grep for `tojson }}"` in templates (tojson into double-quoted attribute)

### Double-Escaping
- Plain-text fields: validate with Pydantic, rely on Jinja2 autoescaping for output
- Rich HTML fields (directions, notes): sanitize with bleach, render with `|safe`
- Test: verify `&` round-trips as `&` through write-then-read, never as `&amp;`

### Upstream Scraper Data Quality
- Post-filter all `recipe_scrapers` output for known JSON-LD key patterns
- Pin scraper library version; add regression tests with captured HTML fixtures
- Log warnings when junk lines are filtered (visibility for new leak patterns)

### Input Validation vs. Sanitization
- Enumerated values (aisle, difficulty, meal_slot): allowlist validation
- Free-text fields: bleach with `tags=[]` (strip all HTML) for plain text; `tags=ALLOWED_TAGS` for rich text
- Never remove a security control without adding the replacement in the same commit

## Files Changed

| File | Change |
|------|--------|
| `src/recipe_app/templates/recipe_detail.html` | Single-quoted data-ingredients attribute |
| `src/recipe_app/db.py` | Removed aisle sanitization, added allowlist validation |
| `src/recipe_app/aisle_map.py` | Added `VALID_AISLES` frozenset |
| `src/recipe_app/scraper.py` | Added `_format_nutrition()`, JSON-LD direction filtering |
| `tests/test_grocery_lists.py` | Updated assertion for un-sanitized aisle value |
