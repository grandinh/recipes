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


def main():
    mcp.run(transport="stdio")
