---
status: pending
priority: p2
issue_id: "004"
tags: [code-review, performance, tests, mcp]
dependencies: []
---

# MCP fixture _db reset can leak connections on test failure

## Problem Statement
The `mcp_client` fixture sets `mcp_mod._db = None` at the start without closing a potentially open prior connection. If a prior test's cleanup failed, the old connection leaks.

## Findings
- **performance-oracle**: "If a prior test set _db to a live connection and the cleanup block failed for any reason, the next test would overwrite _db = None without closing the old connection. This is a leaked file descriptor."

## Proposed Solution
Add defensive close before nulling:
```python
if mcp_mod._db is not None:
    await mcp_mod._db.close()
mcp_mod._db = None
```

## Acceptance Criteria
- [ ] `mcp_client` fixture defensively closes _db before resetting to None
