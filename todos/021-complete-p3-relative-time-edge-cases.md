---
status: complete
priority: p3
issue_id: "021"
tags: [code-review, ui, last-cooked-history]
dependencies: []
---

# `relative_time` filter has edge-case rendering oddities

## Problem Statement
Three small flaws in `_relative_time` (`main.py:99-138`):

1. **Future timestamps render as "just now"** — codex caught this. A `cooked_at` set to tomorrow yields a negative delta and falls through to the 60-second branch.
2. **"today" covers any 1–23h delta** — a cook at 23:00 yesterday (UTC) rendered at 01:00 today reads as "today" despite being on the prior calendar date.
3. **Buckets may be over-engineered** — 6 levels (just-now / minutes / today / yesterday / days / months / years) for a personal recipe app. The "minutes ago" branch is unreachable in practice (no flow re-renders the same recipe within minutes of marking cooked). Months/years use day//30 and day//365 which drift.

## Findings
- **codex (D3)** Low: future timestamps return "just now"
- **kieran-python-reviewer P3 #10, #13**: month/year approximation drifts; "today" is calendar-imprecise
- **code-simplicity-reviewer P1**: filter is over-spec'd — collapse to today/yesterday/N days ago/MMM YYYY

## Recommended Fix
Either (a) collapse buckets per simplicity reviewer, or (b) keep buckets and add a future-timestamp branch ("scheduled" or rendered as absolute date). Pick one based on whether backdating + future scheduling are real workflows.

## Acceptance Criteria
- [ ] Future timestamps render deliberately (not "just now")
- [ ] Decision on bucket granularity documented in code (or buckets simplified)
