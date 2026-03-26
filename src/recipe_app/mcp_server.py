import aiosqlite
from fastmcp import FastMCP

from recipe_app import db as db_module
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams

mcp = FastMCP("Recipe Manager")

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await db_module.connect()
    return _db


@mcp.tool
async def search_recipes(
    query: str | None = None,
    category: str | None = None,
    rating_min: int | None = None,
    rating_max: int | None = None,
    cuisine: str | None = None,
    is_favorite: bool | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "recent",
) -> list[dict]:
    """Search recipes by keyword, category, or rating.

    Query supports multi-ingredient search (e.g., "chicken garlic lemon").
    Sort options: "name", "rating", "recent" (default).
    Filters can be combined: category + rating_min + cuisine etc.
    """
    db = await get_db()
    params = SearchParams(
        q=query,
        category=category,
        rating_min=rating_min,
        rating_max=rating_max,
        cuisine=cuisine,
        is_favorite=is_favorite,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return await db_module.search_recipes(db, params)


@mcp.tool
async def get_recipe(recipe_id: int) -> dict | None:
    """Get full recipe details by ID, including ingredients, directions,
    categories, image URL, and all metadata."""
    db = await get_db()
    return await db_module.get_recipe(db, recipe_id)


@mcp.tool
async def create_recipe(
    title: str,
    ingredients: list[str] | None = None,
    directions: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    categories: list[str] | None = None,
    servings: str | None = None,
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    cuisine: str | None = None,
    difficulty: str | None = None,
    rating: int | None = None,
    is_favorite: bool = False,
    base_servings: int | None = None,
) -> dict:
    """Add a new recipe. Only title is required. Returns the full created recipe."""
    db = await get_db()
    data = RecipeCreate(
        title=title,
        ingredients=ingredients,
        directions=directions,
        description=description,
        notes=notes,
        categories=categories,
        servings=servings,
        prep_time_minutes=prep_time_minutes,
        cook_time_minutes=cook_time_minutes,
        cuisine=cuisine,
        difficulty=difficulty,
        rating=rating,
        is_favorite=is_favorite,
        base_servings=base_servings,
    )
    return await db_module.create_recipe(db, data)


@mcp.tool
async def import_recipe_from_url(url: str) -> dict:
    """Import a recipe from a website URL. Supports 624+ recipe sites.
    Returns the imported recipe and any warnings about fields that couldn't be extracted.
    Returns error if the URL was already imported."""
    from recipe_app.scraper import import_from_url

    db = await get_db()

    # Check duplicate
    existing = await db_module.get_recipe_by_url(db, url)
    if existing is not None:
        return {"error": "Recipe already imported from this URL", "existing_recipe": existing}

    try:
        recipe_dict, warnings = await import_from_url(url)
    except ValueError as e:
        return {"error": "import_failed", "message": str(e)}
    except Exception as e:
        return {"error": "import_failed", "message": f"Failed to fetch recipe: {type(e).__name__}"}

    try:
        data = RecipeCreate(**recipe_dict)
        recipe = await db_module.create_recipe(db, data)
    except Exception as e:
        return {"error": "save_failed", "message": str(e)}

    return {"recipe": recipe, "warnings": warnings}


@mcp.tool
async def update_recipe(
    recipe_id: int,
    title: str | None = None,
    ingredients: list[str] | None = None,
    directions: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    categories: list[str] | None = None,
    servings: str | None = None,
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    cuisine: str | None = None,
    difficulty: str | None = None,
    rating: int | None = None,
    is_favorite: bool | None = None,
    base_servings: int | None = None,
) -> dict | None:
    """Update any field of an existing recipe. Only provided fields are changed.
    Returns the full updated recipe."""
    db = await get_db()

    # Build kwargs with only non-None values
    kwargs = {}
    for field, value in [
        ("title", title), ("ingredients", ingredients), ("directions", directions),
        ("description", description), ("notes", notes), ("categories", categories),
        ("servings", servings), ("prep_time_minutes", prep_time_minutes),
        ("cook_time_minutes", cook_time_minutes), ("cuisine", cuisine),
        ("difficulty", difficulty), ("rating", rating), ("is_favorite", is_favorite),
        ("base_servings", base_servings),
    ]:
        if value is not None:
            kwargs[field] = value

    if not kwargs:
        return await db_module.get_recipe(db, recipe_id)

    data = RecipeUpdate(**kwargs)
    return await db_module.update_recipe(db, recipe_id, data)


@mcp.tool
async def delete_recipe(recipe_id: int) -> str:
    """Permanently delete a recipe by ID. Returns confirmation."""
    db = await get_db()
    existing = await db_module.get_recipe(db, recipe_id)
    if existing is None:
        return f"Recipe {recipe_id} not found"
    await db_module.delete_recipe(db, recipe_id)
    return f"Recipe {recipe_id} ({existing['title']}) deleted"


@mcp.tool
async def list_categories() -> list[dict]:
    """List all recipe categories with the number of recipes in each."""
    db = await get_db()
    return await db_module.list_categories(db)


@mcp.tool
async def get_recipe_by_url(url: str) -> dict | None:
    """Check if a recipe from this URL already exists. Returns the recipe or null."""
    db = await get_db()
    return await db_module.get_recipe_by_url(db, url)


# ---------------------------------------------------------------------------
# Category Tools (previously missing)
# ---------------------------------------------------------------------------

@mcp.tool
async def create_category(name: str) -> dict:
    """Create a new recipe category. Returns the category with its ID."""
    db = await get_db()
    return await db_module.create_category(db, name)


@mcp.tool
async def delete_category(category_id: int) -> str:
    """Delete a category by ID. Does not delete recipes, only removes the tag."""
    db = await get_db()
    deleted = await db_module.delete_category(db, category_id)
    return f"Category {category_id} deleted" if deleted else f"Category {category_id} not found"


# ---------------------------------------------------------------------------
# Scaling Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def scale_recipe(recipe_id: int, multiplier: float) -> dict:
    """Scale a recipe's ingredients by a multiplier. Returns structured data
    with both scaled ingredient objects and formatted text.

    Example: scale_recipe(42, 2.0) doubles all ingredient quantities.
    """
    import asyncio
    from recipe_app.scaling import scale_recipe_ingredients

    db = await get_db()
    recipe = await db_module.get_recipe(db, recipe_id)
    if recipe is None:
        return {"error": f"Recipe {recipe_id} not found"}

    ingredients = recipe.get("ingredients", [])
    if not ingredients:
        return {"error": "Recipe has no ingredients"}

    scaled = await asyncio.to_thread(scale_recipe_ingredients, ingredients, multiplier)
    formatted_lines = [s["scaled_text"] for s in scaled]

    return {
        "recipe_id": recipe_id,
        "title": recipe["title"],
        "multiplier": multiplier,
        "scaled_ingredients": scaled,
        "formatted_text": "\n".join(formatted_lines),
    }


# ---------------------------------------------------------------------------
# Meal Plan Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def create_meal_plan(name: str) -> dict:
    """Create a new meal plan. Returns the full plan object with its ID."""
    db = await get_db()
    return await db_module.create_meal_plan(db, name)


@mcp.tool
async def get_meal_plan(plan_id: int) -> dict | None:
    """Get a meal plan with all its entries (recipes assigned to days/slots)."""
    db = await get_db()
    return await db_module.get_meal_plan(db, plan_id)


@mcp.tool
async def list_meal_plans() -> list[dict]:
    """List all meal plans with entry counts."""
    db = await get_db()
    return await db_module.list_meal_plans(db)


@mcp.tool
async def update_meal_plan(plan_id: int, name: str) -> dict | None:
    """Rename a meal plan. Returns the updated plan."""
    db = await get_db()
    return await db_module.update_meal_plan(db, plan_id, name)


@mcp.tool
async def delete_meal_plan(plan_id: int) -> str:
    """Delete a meal plan and all its entries."""
    db = await get_db()
    deleted = await db_module.delete_meal_plan(db, plan_id)
    return f"Meal plan {plan_id} deleted" if deleted else f"Meal plan {plan_id} not found"


@mcp.tool
async def add_recipe_to_meal_plan(
    plan_id: int,
    recipe_id: int,
    date: str,
    meal_slot: str,
    servings_override: int | None = None,
) -> dict:
    """Add a recipe to a meal plan. meal_slot must be one of: breakfast, lunch, dinner, snack.
    date format: YYYY-MM-DD. Returns the created entry."""
    db = await get_db()
    return await db_module.add_meal_plan_entry(db, plan_id, recipe_id, date, meal_slot, servings_override)


@mcp.tool
async def remove_recipe_from_meal_plan(entry_id: int) -> str:
    """Remove a recipe entry from a meal plan."""
    db = await get_db()
    deleted = await db_module.remove_meal_plan_entry(db, entry_id)
    return f"Entry {entry_id} removed" if deleted else f"Entry {entry_id} not found"


# ---------------------------------------------------------------------------
# Grocery List Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def generate_grocery_list(
    meal_plan_id: int | None = None,
    recipe_ids: list[int] | None = None,
    name: str | None = None,
) -> dict:
    """Generate a grocery list from a meal plan or list of recipe IDs.
    Aggregates ingredients across recipes. Returns the full list with items."""
    db = await get_db()
    return await db_module.generate_grocery_list(db, name=name, meal_plan_id=meal_plan_id, recipe_ids=recipe_ids)


@mcp.tool
async def get_grocery_list(list_id: int) -> dict | None:
    """Get a grocery list with all its items."""
    db = await get_db()
    return await db_module.get_grocery_list(db, list_id)


@mcp.tool
async def list_grocery_lists() -> list[dict]:
    """List all grocery lists with item counts."""
    db = await get_db()
    return await db_module.list_grocery_lists(db)


@mcp.tool
async def delete_grocery_list(list_id: int) -> str:
    """Delete a grocery list and all its items."""
    db = await get_db()
    deleted = await db_module.delete_grocery_list(db, list_id)
    return f"Grocery list {list_id} deleted" if deleted else f"Grocery list {list_id} not found"


# ---------------------------------------------------------------------------
# Pantry Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def add_pantry_item(
    name: str,
    category: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    expiration_date: str | None = None,
) -> dict:
    """Add an item to the pantry. Name must be unique (case-insensitive).
    Returns the created item."""
    db = await get_db()
    return await db_module.add_pantry_item(db, name, category, quantity, unit, expiration_date)


@mcp.tool
async def delete_pantry_item(item_id: int) -> str:
    """Permanently delete a pantry item."""
    db = await get_db()
    deleted = await db_module.delete_pantry_item(db, item_id)
    return f"Pantry item {item_id} deleted" if deleted else f"Pantry item {item_id} not found"


@mcp.tool
async def list_pantry_items(expiring_within_days: int | None = None) -> list[dict]:
    """List pantry items. Optionally filter to items expiring within N days."""
    db = await get_db()
    return await db_module.list_pantry_items(db, expiring_within_days)


@mcp.tool
async def update_pantry_item(
    item_id: int,
    name: str | None = None,
    category: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    expiration_date: str | None = None,
) -> dict | None:
    """Update a pantry item. Only provided fields are changed."""
    db = await get_db()
    return await db_module.update_pantry_item(
        db, item_id, name=name, category=category,
        quantity=quantity, unit=unit, expiration_date=expiration_date,
    )


@mcp.tool
async def find_recipes_from_pantry(max_missing: int = 2) -> list[dict]:
    """Find recipes you can make with your current pantry items.

    Returns recipes ranked by ingredient availability percentage.
    max_missing: maximum number of missing ingredients allowed (default 2).
    Each result includes matched and missing ingredient lists.
    """
    from recipe_app.pantry_matcher import find_matching_recipes as _find

    db = await get_db()
    pantry = await db_module.list_pantry_items(db)
    if not pantry:
        return []

    return await _find(db, pantry, max_missing)


def main():
    mcp.run(transport="stdio")
