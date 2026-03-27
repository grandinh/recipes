"""Ingredient name normalization for grocery list aggregation.

Three MVP strategies that fail to "too many items" (status quo), never
"wrong quantities."  Pure functions, no state between calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedResult:
    name: str
    original_name: str


# Words that already end in 's' (or similar) but are singular
_SINGULAR_EXCEPTIONS = frozenset({
    "asparagus", "citrus", "couscous", "hibiscus", "hummus", "octopus",
    "bass", "grass", "harissa", "swiss", "anise", "hollandaise",
    "bearnaise", "mayonnaise", "molasses", "grits", "oats", "brussels",
})


def singularize(word: str) -> str:
    """Singularize a single word.  Rule-based with exception set."""
    lower = word.lower()
    if lower in _SINGULAR_EXCEPTIONS:
        return word
    if lower.endswith("ies") and len(lower) > 3:
        return word[:-3] + "y"
    if lower.endswith("ves"):
        return word[:-3] + "f"
    if lower.endswith("oes") and len(lower) > 3:
        return word[:-2]
    if lower.endswith("shes") or lower.endswith("ches"):
        return word[:-2]
    if lower.endswith("ses") and not lower.endswith("sses"):
        return word[:-2]
    if lower.endswith("s") and not lower.endswith("ss"):
        return word[:-1]
    return word


_PARENS_RE = re.compile(r"\([^)]*\)")


def normalize_ingredient_name(name: str) -> NormalizedResult:
    """Apply normalization strategies to an ingredient name.

    Strategies applied in order:
    1. Strip parentheticals  ("flour (all-purpose)" -> "flour")
    2. Normalize hyphens     ("extra-virgin olive oil" -> "extra virgin olive oil")
    3. Singularize last word ("tomatoes" -> "tomato")
    """
    original = name
    # 1. Strip parentheticals
    result = _PARENS_RE.sub("", name).strip()
    if not result:
        result = name  # safety: don't blank out entirely

    # 2. Normalize hyphens
    result = result.replace("-", " ")

    # 3. Singularize last word
    words = result.split()
    if words:
        words[-1] = singularize(words[-1])
        result = " ".join(words)

    # Normalize whitespace
    result = " ".join(result.split()).lower().strip()

    return NormalizedResult(name=result, original_name=original)
