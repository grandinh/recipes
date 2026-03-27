"""REST API router for grocery lists (kept here pending Step 4 migration to routers/grocery.py)."""

from fastapi import APIRouter, Depends, HTTPException

from recipe_app import db as db_module
from recipe_app.db import get_db
from recipe_app.calendar_models import (
    GroceryItemCreate,
    GroceryItemUpdate,
    GroceryListGenerate,
)

router = APIRouter(tags=["grocery-lists"])


# ---------------------------------------------------------------------------
# Grocery Lists
# ---------------------------------------------------------------------------


@router.post("/api/grocery-lists/generate", status_code=201)
async def generate_grocery_list_endpoint(
    data: GroceryListGenerate, db=Depends(get_db)
):
    if not data.recipe_ids and not (data.date_start and data.date_end):
        raise HTTPException(
            status_code=400,
            detail="Provide either recipe_ids or date_start+date_end",
        )
    return await db_module.generate_grocery_list(
        db,
        recipe_ids=data.recipe_ids,
        name=data.name,
        date_start=data.date_start.isoformat() if data.date_start else None,
        date_end=data.date_end.isoformat() if data.date_end else None,
    )


@router.get("/api/grocery-lists")
async def list_grocery_lists_endpoint(db=Depends(get_db)):
    return await db_module.list_grocery_lists(db)


@router.get("/api/grocery-lists/{list_id}")
async def get_grocery_list_endpoint(list_id: int, db=Depends(get_db)):
    grocery_list = await db_module.get_grocery_list(db, list_id)
    if grocery_list is None:
        raise HTTPException(status_code=404, detail="Grocery list not found")
    return grocery_list


@router.delete("/api/grocery-lists/{list_id}", status_code=204)
async def delete_grocery_list_endpoint(list_id: int, db=Depends(get_db)):
    deleted = await db_module.delete_grocery_list(db, list_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Grocery list not found")


@router.post("/api/grocery-lists/{list_id}/items", status_code=201)
async def add_grocery_item_endpoint(
    list_id: int, data: GroceryItemCreate, db=Depends(get_db)
):
    # Verify the grocery list exists
    grocery_list = await db_module.get_grocery_list(db, list_id)
    if grocery_list is None:
        raise HTTPException(status_code=404, detail="Grocery list not found")
    return await db_module.add_grocery_item(db, list_id, data.text)


@router.post("/api/recipes/{recipe_id}/grocery-list", status_code=201)
async def add_recipe_to_grocery_list_endpoint(
    recipe_id: int, db=Depends(get_db)
):
    try:
        return await db_module.add_recipe_to_grocery_list(db, recipe_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Recipe not found")


@router.patch("/api/grocery-lists/items/{item_id}")
async def update_grocery_item_endpoint(
    item_id: int, data: GroceryItemUpdate, db=Depends(get_db)
):
    result = await db_module.check_grocery_item(db, item_id, data.is_checked)
    if result is None:
        raise HTTPException(status_code=404, detail="Grocery item not found")
    return result


@router.delete("/api/grocery-lists/items/{item_id}", status_code=204)
async def delete_grocery_item_endpoint(item_id: int, db=Depends(get_db)):
    deleted = await db_module.delete_grocery_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Grocery item not found")


@router.post("/api/grocery-lists/{list_id}/clear-checked")
async def clear_checked_grocery_items_endpoint(list_id: int, db=Depends(get_db)):
    result = await db_module.clear_checked_grocery_items(db, list_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Grocery list not found")
    return result


@router.post("/api/grocery-lists/{list_id}/move-to-pantry")
async def move_checked_to_pantry_endpoint(list_id: int, db=Depends(get_db)):
    result = await db_module.move_checked_to_pantry(db, list_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Grocery list not found")
    return result
