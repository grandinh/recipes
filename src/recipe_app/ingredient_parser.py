"""Ingredient parsing using ingredient-parser-nlp.

Wraps the library for recipe scaling and grocery list aggregation.
Handles edge cases: no-quantity items, string quantities, parse failures.
The library handles no-space format ("2tablespoons") natively via PreProcessor.
"""

from __future__ import annotations

import logging
from fractions import Fraction

from ingredient_parser import parse_ingredient as _lib_parse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single ingredient parsing
# ---------------------------------------------------------------------------

def parse_ingredient(text: str, *, preserve_fractions: bool = False) -> dict:
    """Parse a single ingredient string into a structured dict.

    Returns a dict with keys: ``name``, ``quantity``, ``quantity_max``,
    ``unit``, ``preparation``, ``original_text``, ``scalable``.

    When ``preserve_fractions=True``, quantities are kept as
    ``fractions.Fraction`` instead of being converted to float.
    This is used by the grocery aggregation pipeline for exact arithmetic.

    Edge cases handled:

    - ``amount=[]`` (e.g. "salt to taste") -> ``scalable=False``
    - ``isinstance(amount.quantity, str)`` (e.g. "1 dozen") -> ``scalable=False``
    - Malformed input that raises an exception -> ``scalable=False`` fallback
    - ``Fraction`` objects are converted to ``float`` for JSON serialization
      (unless ``preserve_fractions=True``)
    """
    text = text.strip()
    if not text:
        return _fallback(text)

    try:
        parsed = _lib_parse(text, string_units=not preserve_fractions)
    except Exception:
        logger.warning("Failed to parse ingredient: %r", text, exc_info=True)
        return _fallback(text)

    # No amount found (e.g. "salt to taste")
    if not parsed.amount:
        return {
            "name": _extract_name(parsed),
            "quantity": None,
            "quantity_max": None,
            "unit": None,
            "preparation": _extract_preparation(parsed),
            "original_text": text,
            "scalable": False,
        }

    amount = parsed.amount[0]

    # String quantity that can't be scaled (e.g. "1 dozen")
    if isinstance(amount.quantity, str):
        return {
            "name": _extract_name(parsed),
            "quantity": amount.quantity,
            "quantity_max": (
                amount.quantity_max
                if isinstance(amount.quantity_max, str)
                else _fraction_to_float(amount.quantity_max)
            ),
            "unit": amount.unit if isinstance(amount.unit, str) else str(amount.unit),
            "preparation": _extract_preparation(parsed),
            "original_text": text,
            "scalable": False,
        }

    # Normal numeric quantity — scalable
    convert = (lambda v: v) if preserve_fractions else _fraction_to_float
    return {
        "name": _extract_name(parsed),
        "quantity": convert(amount.quantity),
        "quantity_max": convert(amount.quantity_max),
        "unit": amount.unit if isinstance(amount.unit, str) else str(amount.unit),
        "preparation": _extract_preparation(parsed),
        "original_text": text,
        "scalable": True,
    }


# ---------------------------------------------------------------------------
# Batch parsing
# ---------------------------------------------------------------------------

def parse_recipe_ingredients(ingredients: list[str]) -> list[dict]:
    """Parse a list of ingredient strings.

    Returns a list of dicts, one per ingredient, using the same schema as
    :func:`parse_ingredient`.
    """
    return [parse_ingredient(line) for line in ingredients]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fraction_to_float(value: Fraction | str | None) -> float | None:
    """Convert a ``fractions.Fraction`` to ``float`` for JSON serialization.

    Returns ``None`` if the value is ``None``, and passes through strings
    unchanged (shouldn't happen for numeric quantities, but defensive).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return None
    return float(value)


def _extract_name(parsed) -> str | None:
    """Pull the ingredient name from the parsed result.

    The library returns ``name`` as a list of ``IngredientText`` objects;
    we join their ``.text`` attributes into a single string.
    """
    if not parsed.name:
        return None
    return " ".join(part.text for part in parsed.name)


def _extract_preparation(parsed) -> str | None:
    """Pull the preparation note from the parsed result.

    Returns ``None`` when no preparation was detected.
    """
    if parsed.preparation is None:
        return None
    return parsed.preparation.text


def _fallback(text: str) -> dict:
    """Return a safe fallback dict for unparseable input."""
    return {
        "name": None,
        "quantity": None,
        "quantity_max": None,
        "unit": None,
        "preparation": None,
        "original_text": text,
        "scalable": False,
    }
