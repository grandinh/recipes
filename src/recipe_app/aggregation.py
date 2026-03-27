"""Grocery ingredient aggregation pipeline.

Pure CPU-bound function — no DB, no async.  Testable in isolation.
Parses ingredients, normalizes names, assigns aisles, and aggregates
quantities using Fraction arithmetic.
"""

from __future__ import annotations

from fractions import Fraction

from recipe_app.aisle_map import assign_aisle
from recipe_app.ingredient_parser import parse_ingredient
from recipe_app.normalizer import normalize_ingredient_name
from recipe_app.scaling import format_quantity


def aggregate_ingredients(
    raw_ingredients: list[tuple[str, int, int | None, int | None]],
) -> list[dict]:
    """Parse, normalize, classify, and aggregate ingredients.

    Each input tuple: (ingredient_text, recipe_id, servings_override, base_servings).

    Returns list of dicts with keys: text, aisle, sort_order, recipe_id, normalized_name.
    """
    # aggregation_key -> {qty: Fraction|None, unit: str|None, name: str, texts: [str], recipe_ids: set}
    buckets: dict[tuple[str, str | None], dict] = {}
    result_order: list[tuple[str, str | None]] = []  # preserve insertion order

    for ing_text, recipe_id, servings_override, base_servings in raw_ingredients:
        try:
            parsed = parse_ingredient(ing_text, preserve_fractions=True)
        except Exception:
            parsed = {
                "name": None, "quantity": None, "unit": None,
                "original_text": ing_text, "scalable": False,
            }

        raw_name = parsed.get("name") or parsed.get("original_text") or ing_text
        norm = normalize_ingredient_name(raw_name)
        aisle_name, aisle_order = assign_aisle(norm.name)

        qty = parsed.get("quantity")
        unit = parsed.get("unit")

        # Apply servings scaling if override differs from base
        if (
            qty is not None
            and isinstance(qty, Fraction)
            and servings_override is not None
            and base_servings is not None
            and base_servings > 0
        ):
            qty = qty * Fraction(servings_override, base_servings)

        # Aggregation key: (normalized_name, unit_if_quantified)
        # Items with no quantity never merge with quantified items
        if qty is None or not parsed.get("scalable"):
            agg_key = (norm.name, None)
        else:
            agg_key = (norm.name, unit)

        if agg_key in buckets:
            bucket = buckets[agg_key]
            # Sum quantities if both have numeric qty
            if qty is not None and isinstance(qty, Fraction) and bucket["qty"] is not None:
                bucket["qty"] += qty
            bucket["texts"].append(ing_text)
            bucket["recipe_ids"].add(recipe_id)
        else:
            buckets[agg_key] = {
                "qty": qty if isinstance(qty, Fraction) else None,
                "unit": unit,
                "normalized_name": norm.name,
                "original_name": raw_name,
                "aisle": aisle_name,
                "aisle_order": aisle_order,
                "texts": [ing_text],
                "recipe_ids": {recipe_id},
            }
            result_order.append(agg_key)

    # Build output sorted by aisle order, then name
    items = []
    sorted_keys = sorted(result_order, key=lambda k: (buckets[k]["aisle_order"], buckets[k]["normalized_name"]))
    for i, key in enumerate(sorted_keys):
        b = buckets[key]
        # Format the display text
        if b["qty"] is not None:
            formatted_qty = format_quantity(b["qty"])
            parts = [formatted_qty]
            if b["unit"]:
                parts.append(b["unit"])
            parts.append(b["original_name"])
            display_text = " ".join(parts)
        else:
            display_text = b["texts"][0]  # use original text for unquantified

        items.append({
            "text": display_text,
            "aisle": b["aisle"],
            "sort_order": i,
            "recipe_id": next(iter(b["recipe_ids"])),  # first recipe
            "normalized_name": b["normalized_name"],
        })

    return items
