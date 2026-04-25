---
status: complete
priority: p3
issue_id: "022"
tags: [code-review, refactor, last-cooked-history]
dependencies: []
---

# Sort-key allowlist is now duplicated across 4 sites

## Problem Statement
The sort-literal map exists at:
1. `db.py:742-747` (`list_recipes` order map)
2. `db.py:819-824` (`search_recipes` order map)
3. `models.py:104` (`SearchParams.sort: Literal[...]`)
4. `routers/search.py:18` (endpoint Literal)
5. `routers/recipes.py:25` (endpoint Literal — currently incomplete; see todo 016)

Each `last_cooked` add required touching 4 of the 5 sites; one was missed (todo 016). Same pattern likely to bite the next sort key (e.g. `times_cooked`).

`_VALID_COOK_SOURCES` has the same shape (3 sites — `db.py:1014`, `models.py:80`, `schema.sql:121` CHECK).

## Findings
- **kieran-python-reviewer P2 #4**: tuple in db.py, Literal in models.py, CHECK in schema — three copies
- **pattern-recognition-specialist #8 + #10**: 4-way sort dup, 3-way source dup
- **code-simplicity-reviewer P2**: drop `_VALID_COOK_SOURCES` — Pydantic + SQL CHECK already enforce it

## Recommended Fix (when next sort key is added)
Define a single Python tuple per enum (e.g. `VALID_SORT_KEYS = ("name", "rating", "recent", "last_cooked")`) and derive the Pydantic Literal via `Literal[*VALID_SORT_KEYS]` (PEP 646 syntax — Python 3.12 supports). The SQL CHECK and the order map stay separate but reference the canonical tuple via comment so future contributors find them all.

For `_VALID_COOK_SOURCES`: since Pydantic + SQL CHECK already enforce it, the runtime check in `db.py:1059` can be deleted entirely (per simplicity reviewer).

## Acceptance Criteria
- [ ] Decision recorded — keep duplicated with cross-references, or extract to single source of truth
- [ ] If extracted: all sites import from the canonical location
