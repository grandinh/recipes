"""REST API router for meal plans and grocery lists."""

from fastapi import APIRouter, Depends, HTTPException

from recipe_app import db as db_module
from recipe_app.db import get_db
from recipe_app.meal_plan_models import (
    GroceryItemCreate,
    GroceryItemUpdate,
    GroceryListGenerate,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanUpdate,
)

router = APIRouter(tags=["meal-plans"])


# ---------------------------------------------------------------------------
# Meal Plans
# ---------------------------------------------------------------------------


@router.get("/api/meal-plans")
async def list_meal_plans_endpoint(db=Depends(get_db)):
    return await db_module.list_meal_plans(db)


@router.post("/api/meal-plans", status_code=201)
async def create_meal_plan_endpoint(data: MealPlanCreate, db=Depends(get_db)):
    return await db_module.create_meal_plan(db, data.name)


@router.get("/api/meal-plans/{plan_id}")
async def get_meal_plan_endpoint(plan_id: int, db=Depends(get_db)):
    plan = await db_module.get_meal_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return plan


@router.patch("/api/meal-plans/{plan_id}")
async def update_meal_plan_endpoint(
    plan_id: int, data: MealPlanUpdate, db=Depends(get_db)
):
    result = await db_module.update_meal_plan(db, plan_id, data.name)
    if result is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return result


@router.delete("/api/meal-plans/{plan_id}", status_code=204)
async def delete_meal_plan_endpoint(plan_id: int, db=Depends(get_db)):
    deleted = await db_module.delete_meal_plan(db, plan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meal plan not found")


@router.post("/api/meal-plans/{plan_id}/entries", status_code=201)
async def add_meal_plan_entry_endpoint(
    plan_id: int, data: MealPlanEntryCreate, db=Depends(get_db)
):
    # Verify the meal plan exists
    plan = await db_module.get_meal_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return await db_module.add_meal_plan_entry(
        db,
        plan_id,
        data.recipe_id,
        data.date,
        data.meal_slot,
        data.servings_override,
    )


@router.delete("/api/meal-plans/entries/{entry_id}", status_code=204)
async def remove_meal_plan_entry_endpoint(entry_id: int, db=Depends(get_db)):
    deleted = await db_module.remove_meal_plan_entry(db, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meal plan entry not found")


# ---------------------------------------------------------------------------
# Grocery Lists
# ---------------------------------------------------------------------------


@router.post("/api/grocery-lists/generate", status_code=201)
async def generate_grocery_list_endpoint(
    data: GroceryListGenerate, db=Depends(get_db)
):
    if data.meal_plan_id is None and not data.recipe_ids:
        raise HTTPException(
            status_code=400,
            detail="Provide either meal_plan_id or recipe_ids",
        )
    return await db_module.generate_grocery_list(
        db,
        meal_plan_id=data.meal_plan_id,
        recipe_ids=data.recipe_ids,
        name=data.name,
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


@router.patch("/api/grocery-lists/items/{item_id}")
async def update_grocery_item_endpoint(
    item_id: int, data: GroceryItemUpdate, db=Depends(get_db)
):
    result = await db_module.check_grocery_item(db, item_id, data.is_checked)
    if result is None:
        raise HTTPException(status_code=404, detail="Grocery item not found")
    return result
