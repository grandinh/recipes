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
    Sort options: "name", "rating", "recent" (default), "last_cooked" (most
    recently cooked first; never-cooked recipes ranked last).
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
async def record_recipe_cooked(
    recipe_id: int,
    cooked_at: str | None = None,
    source: str = "manual",
    calendar_entry_id: int | None = None,
    notes: str | None = None,
) -> dict:
    """Record that a recipe was cooked.

    Args:
        recipe_id: Target recipe.
        cooked_at: Optional ISO 8601 timestamp. If omitted, uses current UTC.
            Naive timestamps are stored verbatim and treated as UTC downstream.
        source: One of 'manual' (default), 'calendar', 'import', 'migration'.
        calendar_entry_id: Optional FK to calendar_entries. If the entry does
            not exist, the link is dropped and source is downgraded to 'manual'.
        notes: Optional free-text. HTML is stripped before storage.

    Returns {"event": <event-row>, "recipe": <updated-recipe-dict>} on success
    or {"error": "..."} on a validation/lookup failure."""
    db = await get_db()
    try:
        return await db_module.record_recipe_cooked(
            db,
            recipe_id,
            cooked_at=cooked_at,
            source=source,
            calendar_entry_id=calendar_entry_id,
            notes=notes,
        )
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool
async def get_recipe_cook_history(recipe_id: int, limit: int = 10) -> list[dict] | dict:
    """List cook events for a recipe, newest first. Returns up to `limit` events
    (default 10) with shape {id, recipe_id, cooked_at, source, calendar_entry_id,
    notes, created_at}. Returns {"error": "..."} if the recipe does not exist."""
    db = await get_db()
    recipe = await db_module.get_recipe(db, recipe_id)
    if recipe is None:
        return {"error": f"Recipe {recipe_id} not found"}
    return await db_module.list_recipe_cook_events(db, recipe_id, limit=limit)


@mcp.tool
async def delete_recipe_cook_event(event_id: int) -> dict:
    """Delete a cook event by ID. Returns {"deleted": True, "event_id": id}
    on success or {"error": "..."} if the event does not exist."""
    db = await get_db()
    deleted = await db_module.delete_recipe_cook_event(db, event_id)
    if deleted:
        return {"deleted": True, "event_id": event_id}
    return {"error": f"Cook event {event_id} not found"}


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
    source_url: str | None = None,
    image_url: str | None = None,
    nutritional_info: str | None = None,
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
        source_url=source_url,
        image_url=image_url,
        nutritional_info=nutritional_info,
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
    source_url: str | None = None,
    image_url: str | None = None,
    nutritional_info: str | None = None,
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
        ("base_servings", base_servings), ("source_url", source_url),
        ("image_url", image_url), ("nutritional_info", nutritional_info),
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
async def toggle_favorite(recipe_id: int) -> dict:
    """Toggle a recipe's favorite status. Returns the updated recipe.
    Uses an atomic SQL flip — no need to read the current state first."""
    db = await get_db()
    result = await db_module.toggle_favorite(db, recipe_id)
    if result is None:
        return {"error": f"Recipe {recipe_id} not found"}
    return result


@mcp.tool
async def set_recipe_rating(recipe_id: int, rating: int) -> dict:
    """Set a recipe's rating (1-5 stars). Returns the updated recipe."""
    db = await get_db()
    try:
        result = await db_module.set_rating(db, recipe_id, rating)
    except ValueError as e:
        return {"error": str(e)}
    if result is None:
        return {"error": f"Recipe {recipe_id} not found"}
    return result


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
# Calendar Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def add_to_calendar(
    recipe_id: int,
    date: str,
    meal_slot: str,
) -> dict:
    """Add a recipe to the calendar. meal_slot must be one of: breakfast, lunch, dinner, snack.
    date format: YYYY-MM-DD. Returns the created entry with recipe title."""
    db = await get_db()
    return await db_module.add_calendar_entry(db, recipe_id, date, meal_slot)


@mcp.tool
async def add_to_calendar_batch(
    entries: list[dict],
) -> list[dict]:
    """Batch-add recipes to the calendar for weekly planning.
    Each entry must have: recipe_id (int), date (YYYY-MM-DD), meal_slot (breakfast/lunch/dinner/snack).
    Returns all created entries with recipe titles."""
    db = await get_db()
    return await db_module.add_calendar_entries_batch(db, entries)


@mcp.tool
async def get_calendar_week(date: str) -> dict:
    """Get calendar entries for the Mon-Sun week containing the given date (YYYY-MM-DD).
    Any date within the week works — it snaps to Monday automatically.
    Returns {"entries": [...]} with recipe titles and image URLs."""
    from datetime import date as date_type, timedelta

    db = await get_db()
    ref = date_type.fromisoformat(date)
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return await db_module.get_calendar_week(db, monday.isoformat(), sunday.isoformat())


@mcp.tool
async def remove_from_calendar(entry_id: int) -> str:
    """Remove a calendar entry by ID."""
    db = await get_db()
    deleted = await db_module.remove_calendar_entry(db, entry_id)
    return f"Entry {entry_id} removed" if deleted else f"Entry {entry_id} not found"


# ---------------------------------------------------------------------------
# Grocery List Tools (single global list)
# ---------------------------------------------------------------------------

@mcp.tool
async def get_grocery_list() -> dict:
    """Get the single global grocery list with all items, including
    is_checked and in_pantry flags on each item."""
    db = await get_db()
    return await db_module.get_grocery_list(db)


@mcp.tool
async def add_grocery_item(name: str, aisle: str | None = None) -> dict:
    """Add a manual item to the global grocery list. Auto-assigns aisle
    when not provided. Returns the created item."""
    db = await get_db()
    return await db_module.add_grocery_item(db, name, aisle=aisle)


@mcp.tool
async def add_recipe_to_grocery_list(recipe_id: int) -> dict:
    """Add all of a recipe's ingredients to the global grocery list.
    Ingredients are normalized, assigned aisles, and matched against pantry.
    Returns {items_added, pantry_match_count, recipe_title}."""
    db = await get_db()
    try:
        return await db_module.add_recipe_to_grocery_list(db, recipe_id)
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool
async def preview_grocery_additions(recipe_id: int) -> dict:
    """Read-only preview of what would be added from a recipe.
    Returns items with pantry flags — does not modify the grocery list."""
    db = await get_db()
    try:
        return await db_module.preview_grocery_additions(db, recipe_id)
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool
async def generate_grocery_list_from_calendar(
    start: str | None = None,
    end: str | None = None,
    recipe_ids: list[int] | None = None,
) -> dict:
    """Generate grocery items from calendar entries or specific recipes and append to the global list.
    Provide either start+end (YYYY-MM-DD date range) or recipe_ids (list of recipe IDs), not both.
    Returns {items_added, pantry_match_count, items}."""
    if not start and not recipe_ids:
        return {"error": "Provide start+end date range or recipe_ids"}
    db = await get_db()
    return await db_module.generate_grocery_list(
        db, date_start=start, date_end=end, recipe_ids=recipe_ids,
    )


@mcp.tool
async def check_grocery_item(item_id: int, is_checked: bool) -> dict | None:
    """Check or uncheck a grocery list item. Returns the updated item."""
    db = await get_db()
    return await db_module.check_grocery_item(db, item_id, is_checked)


@mcp.tool
async def delete_grocery_item(item_id: int) -> str:
    """Delete a single item from the grocery list."""
    db = await get_db()
    deleted = await db_module.delete_grocery_item(db, item_id)
    return f"Item {item_id} deleted" if deleted else f"Item {item_id} not found"


@mcp.tool
async def clear_bought_items() -> dict:
    """Remove all checked (purchased) items from the grocery list.
    Returns the number of items cleared."""
    db = await get_db()
    return await db_module.clear_checked_grocery_items(db)


@mcp.tool
async def move_checked_to_pantry() -> dict:
    """Move checked grocery items to the pantry and remove them from the list.
    Items already in the pantry are skipped (no duplicates).
    Returns lists of moved items, already-in-pantry items, and any warnings."""
    db = await get_db()
    return await db_module.move_checked_to_pantry(db)


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


@mcp.tool
async def upload_recipe_photo(
    recipe_id: int,
    image_base64: str,
) -> dict:
    """Upload a photo for an existing recipe. All common image formats
    (JPEG, PNG, WebP) are auto-detected and re-encoded to JPEG.

    recipe_id: ID of the recipe to attach the photo to.
    image_base64: Base64-encoded image data (max ~10 MB decoded).
    """
    import binascii
    import base64 as b64

    from recipe_app.models import RecipeUpdate
    from recipe_app.photos import delete_photo, save_photo

    MAX_BASE64_SIZE = 14 * 1024 * 1024  # ~10 MB decoded

    if len(image_base64) > MAX_BASE64_SIZE:
        return {"error": "Image too large (max 10 MB)"}

    db = await get_db()
    recipe = await db_module.get_recipe(db, recipe_id)
    if not recipe:
        return {"error": f"Recipe {recipe_id} not found"}

    try:
        image_data = b64.b64decode(image_base64)
    except (binascii.Error, ValueError):
        return {"error": "Invalid base64 image data"}

    try:
        filename = await save_photo(image_data)
    except ValueError as e:
        return {"error": f"Invalid image: {e}"}

    old_photo = recipe.get("photo_path")
    await db_module.update_recipe(db, recipe_id, RecipeUpdate(photo_path=filename))
    if old_photo:
        await delete_photo(old_photo)

    return {"recipe_id": recipe_id, "photo_path": filename}


def main():
    mcp.run(transport="stdio")
