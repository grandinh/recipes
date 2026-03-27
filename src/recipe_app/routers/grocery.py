"""REST API router for the single global grocery list."""

from fastapi import APIRouter, Depends, HTTPException

from recipe_app import db as db_module
from recipe_app.db import get_db
from recipe_app.calendar_models import (
    GroceryItemCreate,
    GroceryItemUpdate,
    GroceryListGenerate,
)

router = APIRouter(prefix="/api/grocery", tags=["grocery"])


@router.get("")
async def get_grocery_list_endpoint(db=Depends(get_db)):
    """Get the single global grocery list with all items."""
    return await db_module.get_grocery_list(db)


@router.post("/items", status_code=201)
async def add_grocery_item_endpoint(data: GroceryItemCreate, db=Depends(get_db)):
    """Add a manual item to the global grocery list."""
    return await db_module.add_grocery_item(db, data.text, aisle=data.aisle)


@router.post("/add-from-recipe/{recipe_id}", status_code=201)
async def add_from_recipe_endpoint(recipe_id: int, db=Depends(get_db)):
    """Add all of a recipe's ingredients to the global grocery list."""
    try:
        return await db_module.add_recipe_to_grocery_list(db, recipe_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Recipe not found")


@router.post("/generate-from-calendar", status_code=201)
async def generate_from_calendar_endpoint(
    data: GroceryListGenerate, db=Depends(get_db)
):
    """Generate grocery items from calendar entries or recipe IDs."""
    if not data.recipe_ids and not (data.date_start and data.date_end):
        raise HTTPException(
            status_code=400,
            detail="Provide either recipe_ids or date_start+date_end",
        )
    return await db_module.generate_grocery_list(
        db,
        recipe_ids=data.recipe_ids,
        date_start=data.date_start.isoformat() if data.date_start else None,
        date_end=data.date_end.isoformat() if data.date_end else None,
    )


@router.patch("/items/{item_id}")
async def update_grocery_item_endpoint(
    item_id: int, data: GroceryItemUpdate, db=Depends(get_db)
):
    """Check or uncheck a grocery item."""
    result = await db_module.check_grocery_item(db, item_id, data.is_checked)
    if result is None:
        raise HTTPException(status_code=404, detail="Grocery item not found")
    return result


@router.delete("/items/{item_id}", status_code=204)
async def delete_grocery_item_endpoint(item_id: int, db=Depends(get_db)):
    """Delete a single grocery item."""
    deleted = await db_module.delete_grocery_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Grocery item not found")


@router.post("/clear-checked")
async def clear_checked_endpoint(db=Depends(get_db)):
    """Remove all checked (purchased) items from the grocery list."""
    return await db_module.clear_checked_grocery_items(db)


@router.post("/move-to-pantry")
async def move_to_pantry_endpoint(db=Depends(get_db)):
    """Move checked items to the pantry and remove from the grocery list."""
    return await db_module.move_checked_to_pantry(db)


@router.get("/preview/{recipe_id}")
async def preview_grocery_additions_endpoint(recipe_id: int, db=Depends(get_db)):
    """Preview what would be added from a recipe (read-only)."""
    try:
        return await db_module.preview_grocery_additions(db, recipe_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Recipe not found")
