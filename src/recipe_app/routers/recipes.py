import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal

from recipe_app.db import (
    get_db, create_recipe, get_recipe, get_recipe_by_url,
    update_recipe, delete_recipe, list_recipes,
    record_recipe_cooked, list_recipe_cook_events, delete_recipe_cook_event,
)
from recipe_app.models import (
    RecipeCreate, RecipeUpdate, RecipeResponse,
    ImportRequest, ImportResponse,
    RecipeCookEventCreate, RecipeCookEventResponse, RecipeCookRecordedResponse,
)
from recipe_app.scraper import import_from_url

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("", response_model=list[RecipeResponse])
async def list_recipes_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["name", "rating", "recent"] = "recent",
    db=Depends(get_db),
):
    return await list_recipes(db, limit=limit, offset=offset, sort=sort)


@router.post("", response_model=RecipeResponse, status_code=201)
async def create_recipe_endpoint(data: RecipeCreate, db=Depends(get_db)):
    try:
        return await create_recipe(db, data)
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="Recipe with this source_url already exists")
        raise


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe_endpoint(recipe_id: int, db=Depends(get_db)):
    recipe = await get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.patch("/{recipe_id}", response_model=RecipeResponse)
async def update_recipe_endpoint(recipe_id: int, data: RecipeUpdate, db=Depends(get_db)):
    result = await update_recipe(db, recipe_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return result


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe_endpoint(recipe_id: int, db=Depends(get_db)):
    deleted = await delete_recipe(db, recipe_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recipe not found")


@router.delete("/cook-events/{event_id}", status_code=204)
async def delete_cook_event_endpoint(event_id: int, db=Depends(get_db)):
    deleted = await delete_recipe_cook_event(db, event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cook event not found")


@router.post(
    "/{recipe_id}/cooked",
    response_model=RecipeCookRecordedResponse,
    status_code=201,
)
async def record_cooked_endpoint(
    recipe_id: int,
    data: RecipeCookEventCreate | None = None,
    db=Depends(get_db),
):
    payload = data or RecipeCookEventCreate()
    cooked_at = payload.cooked_at.isoformat() if payload.cooked_at else None
    try:
        return await record_recipe_cooked(
            db,
            recipe_id,
            cooked_at=cooked_at,
            source=payload.source,
            calendar_entry_id=payload.calendar_entry_id,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{recipe_id}/cook-events",
    response_model=list[RecipeCookEventResponse],
)
async def list_cook_events_endpoint(
    recipe_id: int,
    limit: int = Query(20, ge=1, le=200),
    db=Depends(get_db),
):
    recipe = await get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return await list_recipe_cook_events(db, recipe_id, limit=limit)


@router.post("/import", response_model=ImportResponse, status_code=201)
async def import_recipe_endpoint(data: ImportRequest, db=Depends(get_db)):
    # Check for duplicate URL
    existing = await get_recipe_by_url(db, data.url)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": "Recipe already imported from this URL", "recipe_id": existing["id"]},
        )

    try:
        recipe_dict, warnings = await import_from_url(data.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch recipe: {e}")

    recipe_data = RecipeCreate(**recipe_dict)
    recipe = await create_recipe(db, recipe_data)
    return ImportResponse(recipe=RecipeResponse(**recipe), warnings=warnings)
