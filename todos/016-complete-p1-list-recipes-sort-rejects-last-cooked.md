---
status: complete
priority: p1
issue_id: "016"
tags: [code-review, bug, api, last-cooked-history]
dependencies: []
---

# GET /api/recipes rejects ?sort=last_cooked with 422

## Problem Statement
`SearchParams.sort` (models.py:104), `routers/search.py:18`, and `db.list_recipes` / `db.search_recipes` (db.py:746, 823) all accept `last_cooked`. The list endpoint at `routers/recipes.py:25` was missed — its `Literal["name", "rating", "recent"]` annotation rejects `?sort=last_cooked` with a 422. Asymmetric: `/api/search?sort=last_cooked` works, `/api/recipes?sort=last_cooked` doesn't.

## Findings
- **pattern-recognition-specialist**: "Literal still reads `Literal["name", "rating", "recent"]`. A client passing `?sort=last_cooked` to `/api/recipes` gets a 422 even though `db.list_recipes` accepts it." (`routers/recipes.py:25`)

Sort literal is now duplicated at 4 sites (db.py x2, models.py, routers/search.py, routers/recipes.py); see todo 022 for the dedup option.

## Acceptance Criteria
- [ ] `routers/recipes.py:25` Literal extended to include `last_cooked`
- [ ] Add a test asserting `GET /api/recipes?sort=last_cooked` returns 200
