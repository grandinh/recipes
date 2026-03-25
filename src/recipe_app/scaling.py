"""Recipe scaling -- multiply ingredient quantities by a factor.

Uses fractions.Fraction for exact arithmetic and cooking-friendly display.
"""

from __future__ import annotations

from fractions import Fraction

from .ingredient_parser import parse_ingredient

# ---------------------------------------------------------------------------
# Supported multipliers (for UI validation; the math works with any float)
# ---------------------------------------------------------------------------
SUPPORTED_MULTIPLIERS: list[float] = [
    0.125, 0.25, 1 / 3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0,
]


# ---------------------------------------------------------------------------
# Quantity formatting
# ---------------------------------------------------------------------------

def format_quantity(value: float) -> str:
    """Display a numeric quantity as a cooking-friendly fraction string.

    Uses ``fractions.Fraction.limit_denominator(8)`` so the result is
    always a denominator cooks recognise (2, 3, 4, 5, 6, 7, 8).

    Examples::

        0.5   -> "1/2"
        0.333 -> "1/3"
        0.25  -> "1/4"
        3.0   -> "3"
        1.5   -> "1 1/2"
        0.125 -> "1/8"
    """
    frac = Fraction(value).limit_denominator(8)

    if frac.denominator == 1:
        # Whole number
        return str(frac.numerator)

    whole = frac.numerator // frac.denominator
    remainder = frac - whole

    if whole > 0:
        return f"{whole} {remainder}"
    return str(frac)


# ---------------------------------------------------------------------------
# Single ingredient scaling
# ---------------------------------------------------------------------------

def scale_ingredient(parsed: dict, factor: float) -> dict:
    """Multiply a parsed ingredient's quantity by *factor*.

    Returns a **new** dict that adds ``scaled_quantity`` and
    ``formatted_quantity`` to the original parsed fields.  The original
    ``quantity`` and ``quantity_max`` are preserved unchanged.

    Items with ``scalable=False`` pass through with no quantity change;
    ``scaled_quantity`` and ``formatted_quantity`` are set to ``None``.
    """
    result = dict(parsed)

    if not parsed.get("scalable") or parsed.get("quantity") is None:
        result["scaled_quantity"] = None
        result["scaled_quantity_max"] = None
        result["formatted_quantity"] = None
        result["formatted_quantity_max"] = None
        return result

    scaled = parsed["quantity"] * factor
    result["scaled_quantity"] = scaled
    result["formatted_quantity"] = format_quantity(scaled)

    # Handle ranges (quantity_max differs from quantity)
    if (
        parsed.get("quantity_max") is not None
        and parsed["quantity_max"] != parsed["quantity"]
    ):
        scaled_max = parsed["quantity_max"] * factor
        result["scaled_quantity_max"] = scaled_max
        result["formatted_quantity_max"] = format_quantity(scaled_max)
    else:
        result["scaled_quantity_max"] = result["scaled_quantity"]
        result["formatted_quantity_max"] = result["formatted_quantity"]

    return result


# ---------------------------------------------------------------------------
# Full recipe scaling
# ---------------------------------------------------------------------------

def _build_scaled_text(scaled: dict) -> str:
    """Reconstruct a human-readable ingredient line from scaled data.

    For non-scalable items, returns the original text unchanged.
    """
    if not scaled.get("scalable") or scaled.get("formatted_quantity") is None:
        return scaled.get("original_text", "")

    parts: list[str] = []

    # Quantity (with range if applicable)
    if (
        scaled.get("formatted_quantity_max")
        and scaled["formatted_quantity_max"] != scaled["formatted_quantity"]
    ):
        parts.append(f"{scaled['formatted_quantity']}-{scaled['formatted_quantity_max']}")
    else:
        parts.append(scaled["formatted_quantity"])

    # Unit
    if scaled.get("unit"):
        parts.append(scaled["unit"])

    # Name
    if scaled.get("name"):
        parts.append(scaled["name"])

    # Preparation
    if scaled.get("preparation"):
        parts.append(f", {scaled['preparation']}")

    return " ".join(parts)


def scale_recipe_ingredients(
    ingredients: list[str],
    factor: float,
) -> list[dict]:
    """Parse all ingredients and scale them by *factor*.

    Returns a list of dicts, each with: ``original_text``, ``scaled_text``,
    ``quantity``, ``scaled_quantity``, ``unit``, ``name``, ``scalable``.
    """
    results: list[dict] = []

    for line in ingredients:
        parsed = parse_ingredient(line)
        scaled = scale_ingredient(parsed, factor)

        results.append({
            "original_text": parsed["original_text"],
            "scaled_text": _build_scaled_text(scaled),
            "quantity": parsed["quantity"],
            "scaled_quantity": scaled.get("scaled_quantity"),
            "unit": parsed.get("unit"),
            "name": parsed.get("name"),
            "scalable": parsed["scalable"],
        })

    return results
