---
status: pending
priority: p3
issue_id: "006"
tags: [code-review, quality, tests, naming]
dependencies: []
---

# ~13 test methods use single-word names violating naming convention

## Problem Statement
Convention is `test_<verb>_<subject>_<qualifier>`. Several tests in scaling and parser files use bare names like `test_double`, `test_half`, `test_range`, `test_numeric`, `test_batch`.

## Findings
- **pattern-recognition-specialist**: "~13 single-word test names in test_scaling.py and test_ingredient_parser.py violate the test_<verb>_<subject> convention"

Examples: `test_double` → `test_scale_double_factor`, `test_numeric` → `test_parse_numeric_quantity`

Also: 9 duplicate test method names across classes that would collide if classes are ever flattened.

## Acceptance Criteria
- [ ] Test names follow test_<verb>_<subject>_<qualifier> pattern
- [ ] No duplicate names that would collide across files
