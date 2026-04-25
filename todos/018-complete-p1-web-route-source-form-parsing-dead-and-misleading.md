---
status: complete
priority: p1
issue_id: "018"
tags: [code-review, bug, web, simplicity, last-cooked-history]
dependencies: []
---

# `record_cooked_submit` form parsing is dead today AND mistranslates ValueError

## Problem Statement
Two issues bundled:

1. **Dead code.** `record_cooked_submit` (`main.py:803-818`) reads `form.get("source")` and `form.get("calendar_entry_id")` from the request body, but the only template that posts to this endpoint (`recipe_detail.html:59-68`) sends an empty body. No UI surface emits these fields.

2. **Misleading error.** Pass-through `source` to `record_recipe_cooked` raises `ValueError("Invalid source: ...")` for out-of-allowlist values. The handler's catch-all `except ValueError` (`main.py:818`) maps that to "Recipe not found" 404 — same response as a missing recipe. A handcrafted form with `source=evil` silently 404s.

## Findings
- **kieran-python-reviewer P1 #1**: catch-all ValueError swallows source validation as 404
- **security-sentinel P2**: form path has no Pydantic boundary while JSON path does — brittle
- **architecture-strategist P1-1**: invariant violation — every surface should treat `source` consistently
- **pattern-recognition-specialist #3**: 404 unconditionally for both ValueError causes
- **code-simplicity-reviewer P2**: "the form parse code is dead in the web UI path"

## Recommended Fix
Drop the form parsing entirely (per simplicity reviewer). Web button always means `source='manual'`, no `calendar_entry_id`. When/if a calendar-card "Cooked" shortcut ships (deferred per plan), reintroduce the form parsing then through a Pydantic-bound shape.

```python
async def record_cooked_submit(request, recipe_id, hx_request=...):
    db = get_db(request)
    try:
        result = await record_recipe_cooked(db, recipe_id)  # source defaults to 'manual'
    except ValueError:
        # Only "Recipe not found" can fire now
        ...
```

## Acceptance Criteria
- [ ] Form parsing removed from `record_cooked_submit`
- [ ] ValueError from missing recipe still 404s; no other ValueError path exists
- [ ] Existing tests still pass
