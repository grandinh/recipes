---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, quality, mcp, tests]
dependencies: []
---

# MCP test assertions use fragile string matching

## Problem Statement
19 MCP tests in `test_mcp_server.py` use `assert "keyword" in str(result)` patterns that would pass on false positives. The fastmcp `Client.call_tool` returns structured content objects, but the tests convert to string and do substring matching. Additionally, several tests hardcode `recipe_id: 1` / `plan_id: 1` assuming autoincrement starts at 1.

## Findings
- **kieran-python-reviewer**: "MCP assertions too loose — substring matching on str(result)"
- **architecture-strategist**: "Loose assertions in MCP tests... fragile... a tool could return a garbled error message containing the string and the test would pass"
- **pattern-recognition-specialist**: "Mixing str-check and value-check in one assertion"
- **agent-native-reviewer**: "8 of 27 MCP tools have zero test coverage"

Examples:
- Line 53: `assert "MCP Tacos" in str(result)`
- Line 66: `assert "null" in str(result).lower() or "None" in str(result)`
- Line 176: `assert str(result)` — only checks result is non-empty

## Proposed Solutions

### Option A: Parse MCP result content objects (Recommended)
Extract `.text` from result content, parse JSON, assert on specific fields.
- **Pros**: Precise assertions, catches real regressions
- **Cons**: Need to understand fastmcp result type structure
- **Effort**: Medium
- **Risk**: Low

### Option B: Add a helper function to extract results
Create `extract_mcp_result(result) -> dict` utility and use it everywhere.
- **Pros**: DRY, consistent pattern
- **Cons**: Still need to understand the type
- **Effort**: Medium
- **Risk**: Low

## Technical Details
- **Affected files**: `tests/test_mcp_server.py`
- **All 19 tests affected**
- Also add comment about hardcoded ID=1 assumption or extract IDs from create results

## Acceptance Criteria
- [ ] MCP test assertions check structured data, not substring of str()
- [ ] Hardcoded IDs replaced with extracted IDs or documented with comment
- [ ] 8 untested MCP tools get at least one test each
