"""Pantry-based recipe matching — two-tier: exact + substring.

No external dependencies (no rapidfuzz). Matches pantry item names against
recipe ingredient lists using case-insensitive exact match and substring containment.
"""

from __future__ import annotations

import json
import logging

from ingredient_parser import parse_ingredient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ingredient name extraction
# ---------------------------------------------------------------------------


def _extract_ingredient_name(ingredient_text: str) -> str | None:
    """Parse a single ingredient string and return the ingredient name.

    Returns None if parsing fails or no name is found.
    """
    try:
        parsed = parse_ingredient(ingredient_text)
        if parsed.name:
            return parsed.name[0].text.strip()
    except Exception:
        logger.debug("Failed to parse ingredient: %s", ingredient_text)
    return None


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _matches_pantry(ingredient_name: str, pantry_names_lower: list[str]) -> bool:
    """Check if an ingredient name matches any pantry item.

    Two-tier matching:
    1. Exact match (case-insensitive, trimmed)
    2. Substring containment — pantry "chicken" matches ingredient
       "boneless skinless chicken breast"
    """
    name_lower = ingredient_name.lower().strip()
    for pantry_name in pantry_names_lower:
        # Tier 1: exact match
        if name_lower == pantry_name:
            return True
        # Tier 2: pantry item name is contained in the ingredient name
        if pantry_name in name_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Main matching engine (sync — call via asyncio.to_thread from routes)
# ---------------------------------------------------------------------------


def find_matching_recipes_sync(
    recipes: list[dict],
    pantry_items: list[dict],
    max_missing: int = 2,
) -> list[dict]:
    """Match pantry items against recipe ingredients.

    Parameters
    ----------
    recipes:
        List of recipe dicts, each with at least ``id``, ``title``,
        ``image_url``, and ``ingredients`` (JSON string or list of strings).
    pantry_items:
        List of pantry item dicts, each with at least a ``name`` key.
    max_missing:
        Maximum number of missing ingredients to include a recipe in results.

    Returns
    -------
    List of match-result dicts sorted by (match_percentage DESC, missing count ASC).
    Each dict: {recipe_id, title, image_url, total_ingredients, matched_count,
                match_percentage, matched_ingredients, missing_ingredients}
    """
    if not pantry_items:
        return []

    # Pre-compute lowercase pantry names for fast comparison
    pantry_names_lower = [item["name"].lower().strip() for item in pantry_items]

    results: list[dict] = []

    for recipe in recipes:
        # Parse the ingredients list (may be JSON string or already a list)
        raw_ingredients = recipe.get("ingredients", [])
        if isinstance(raw_ingredients, str):
            try:
                raw_ingredients = json.loads(raw_ingredients)
            except (json.JSONDecodeError, TypeError):
                raw_ingredients = []

        if not raw_ingredients:
            continue

        # Parse each ingredient and match against pantry
        matched: list[str] = []
        missing: list[str] = []

        for ingredient_text in raw_ingredients:
            parsed_name = _extract_ingredient_name(ingredient_text)
            if parsed_name is None:
                # Could not parse — treat as missing
                missing.append(ingredient_text)
                continue

            if _matches_pantry(parsed_name, pantry_names_lower):
                matched.append(ingredient_text)
            else:
                missing.append(ingredient_text)

        total = len(raw_ingredients)
        matched_count = len(matched)
        missing_count = len(missing)

        # Filter by max_missing
        if missing_count > max_missing:
            continue

        match_percentage = round((matched_count / total) * 100, 1) if total > 0 else 0.0

        results.append({
            "recipe_id": recipe["id"],
            "title": recipe["title"],
            "image_url": recipe.get("image_url"),
            "total_ingredients": total,
            "matched_count": matched_count,
            "match_percentage": match_percentage,
            "matched_ingredients": matched,
            "missing_ingredients": missing,
        })

    # Sort: highest match percentage first, then fewest missing
    results.sort(key=lambda r: (-r["match_percentage"], len(r["missing_ingredients"])))

    return results


async def find_matching_recipes(
    db,
    pantry_items: list[dict],
    max_missing: int = 2,
) -> list[dict]:
    """Async wrapper — fetches recipes from DB, then runs matching in a thread.

    Parameters
    ----------
    db:
        aiosqlite connection.
    pantry_items:
        List of pantry item dicts with at least a ``name`` key.
    max_missing:
        Maximum number of missing ingredients for a recipe to be included.

    Returns
    -------
    Sorted list of match-result dicts.
    """
    import asyncio

    # Fetch all recipes (id, title, image_url, ingredients)
    cursor = await db.execute(
        "SELECT id, title, image_url, ingredients FROM recipes"
    )
    recipes = await cursor.fetchall()

    # Convert Row objects to plain dicts if needed
    recipe_list = [dict(r) for r in recipes]

    # Run CPU-bound matching in a thread to avoid blocking the event loop
    return await asyncio.to_thread(
        find_matching_recipes_sync,
        recipe_list,
        pantry_items,
        max_missing,
    )
