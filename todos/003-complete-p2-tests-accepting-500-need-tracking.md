---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, quality, tests, bugs]
dependencies: []
---

# Tests accepting 500 status code should use xfail or track the bugs

## Problem Statement
5 tests accept HTTP 500 as a valid response to document known bugs (unhandled IntegrityError, template rendering failures). These pass silently when the bugs are fixed, providing no signal that the fix landed. They also don't verify the 500 response doesn't leak internal details.

## Findings
- **kieran-python-reviewer**: "Should be marked with pytest.mark.xfail or a custom marker"
- **security-sentinel**: "None of these tests verify that the 500 response body does not leak internal implementation details"
- **pattern-recognition-specialist**: "No tracking mechanism (no TODO, no issue number)"

Affected tests:
- `test_meal_plans.py:146` — `assert resp.status_code in (400, 404, 500)`
- `test_pantry.py:45` — `assert resp.status_code in (409, 500)`
- `test_pantry.py:108` — `assert resp.status_code in (409, 500)`
- `test_web_ui.py:113` — `assert resp.status_code in (200, 500)`
- `test_htmx_partials.py:80` — `assert resp.status_code in (200, 500)`

## Proposed Solutions

### Option A: Use xfail with strict=False (Recommended)
Mark tests with `@pytest.mark.xfail(reason="...", strict=False)` and assert the correct status code. When bugs are fixed, xfail warns you to update.
- **Effort**: Small
- **Risk**: None

### Option B: Fix the underlying bugs
Catch IntegrityError in routers, return 409. Fix template rendering.
- **Effort**: Medium
- **Risk**: Low — but this is app code change, not just test change

## Acceptance Criteria
- [ ] Tests are either xfail'd or bugs are fixed
- [ ] If 500 is expected, assert response body doesn't contain "Traceback", "IntegrityError", or file paths
