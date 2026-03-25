"""REST API router for pantry items and recipe matching."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from recipe_app import db as db_module
from recipe_app.db import get_db
from recipe_app.pantry_matcher import find_matching_recipes


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PantryItemCreate(BaseModel):
    """POST payload for adding a pantry item."""

    name: str
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None
    expiration_date: str | None = None


class PantryItemUpdate(BaseModel):
    """PATCH payload for updating a pantry item — all fields optional."""

    name: str | None = None
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None
    expiration_date: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/pantry", tags=["pantry"])


@router.get("")
async def list_pantry_items_endpoint(
    expiring_within_days: int | None = Query(None, ge=1),
    db=Depends(get_db),
):
    """List all pantry items, optionally filtered to those expiring soon."""
    return await db_module.list_pantry_items(db, expiring_within_days=expiring_within_days)


@router.get("/matches")
async def pantry_matches_endpoint(
    max_missing: int = Query(2, ge=0),
    db=Depends(get_db),
):
    """'What can I make?' — find recipes matching current pantry items."""
    pantry_items = await db_module.list_pantry_items(db)
    if not pantry_items:
        return []
    return await find_matching_recipes(db, pantry_items, max_missing=max_missing)


@router.post("", status_code=201)
async def create_pantry_item_endpoint(data: PantryItemCreate, db=Depends(get_db)):
    """Add a new pantry item."""
    return await db_module.add_pantry_item(
        db,
        name=data.name,
        category=data.category,
        quantity=data.quantity,
        unit=data.unit,
        expiration_date=data.expiration_date,
    )


@router.patch("/{item_id}")
async def update_pantry_item_endpoint(
    item_id: int, data: PantryItemUpdate, db=Depends(get_db)
):
    """Update a pantry item's fields."""
    # Build kwargs from non-None fields only
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one field must be provided")
    result = await db_module.update_pantry_item(db, item_id, **updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    return result


@router.delete("/{item_id}", status_code=204)
async def delete_pantry_item_endpoint(item_id: int, db=Depends(get_db)):
    """Delete a pantry item."""
    deleted = await db_module.delete_pantry_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pantry item not found")
