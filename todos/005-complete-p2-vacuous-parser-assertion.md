---
status: pending
priority: p2
issue_id: "005"
tags: [code-review, quality, tests]
dependencies: []
---

# test_with_preparation assertion is vacuous (always true)

## Problem Statement
In `test_ingredient_parser.py`, `test_with_preparation` asserts `result["scalable"] is True or result["scalable"] is False` — which is always true for any boolean value.

## Findings
- **kieran-python-reviewer**: "This assertion is always true. It asserts that scalable is a boolean, which is trivially satisfied. The test name says 'with_preparation' but never checks the preparation field."

## Proposed Solution
Check the `preparation` field or at minimum assert something meaningful:
```python
def test_with_preparation(self):
    result = parse_ingredient("2 cloves garlic, minced")
    assert result["original_text"] == "2 cloves garlic, minced"
    assert "preparation" in result
```

## Acceptance Criteria
- [ ] test_with_preparation makes a meaningful assertion about the preparation field
