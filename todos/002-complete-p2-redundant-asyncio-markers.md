---
status: pending
priority: p2
issue_id: "002"
tags: [code-review, quality, tests, cleanup]
dependencies: []
---

# Redundant @pytest.mark.asyncio decorators on all async tests

## Problem Statement
`pyproject.toml` sets `asyncio_mode = "auto"` which makes `@pytest.mark.asyncio` unnecessary on every `async def test_*` function. Yet all 130+ async tests carry the decorator — pure noise that could drift to inconsistency if new contributors omit it.

## Findings
- **kieran-python-reviewer**: "130+ redundant markers... should not propagate the anti-pattern"
- **pattern-recognition-specialist**: "Consistently applied (no async test is missing it), so it is not an inconsistency... it is a codebase-wide redundancy"
- **architecture-strategist**: "Either remove all the decorators or switch to strict mode"

## Proposed Solutions

### Option A: Remove all @pytest.mark.asyncio decorators (Recommended)
Strip from all files, rely on `asyncio_mode = "auto"`.
- **Pros**: Cleaner code, less noise, matches the intent of the config
- **Cons**: Large diff touching many files
- **Effort**: Small (search-and-replace)
- **Risk**: None — auto mode handles it

### Option B: Keep decorators, add comment in conftest
Document the convention choice.
- **Pros**: No code changes
- **Cons**: Perpetuates unnecessary noise
- **Effort**: Trivial

## Acceptance Criteria
- [ ] All async tests work without @pytest.mark.asyncio
- [ ] Convention is documented or decorators are removed consistently
