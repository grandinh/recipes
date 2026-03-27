"""REST API router for the global calendar."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from recipe_app import db as db_module
from recipe_app.db import get_db
from recipe_app.calendar_models import CalendarEntryCreate, CalendarEntryBatchCreate

router = APIRouter(tags=["calendar"])


@router.get("/api/calendar")
async def get_calendar_week_endpoint(
    week: str | None = None,
    db=Depends(get_db),
):
    """Return calendar entries for a Mon-Sun week.

    Pass any date via ?week=YYYY-MM-DD; it snaps to Monday.
    Defaults to the current week.
    """
    if week:
        try:
            ref = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid week param. Use YYYY-MM-DD.")
    else:
        ref = date.today()

    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return await db_module.get_calendar_week(db, monday.isoformat(), sunday.isoformat())


@router.post("/api/calendar/entries", status_code=201)
async def create_calendar_entry_endpoint(
    data: CalendarEntryCreate,
    db=Depends(get_db),
):
    return await db_module.add_calendar_entry(
        db, data.recipe_id, data.date, data.meal_slot,
    )


@router.post("/api/calendar/entries/batch", status_code=201)
async def create_calendar_entries_batch_endpoint(
    data: CalendarEntryBatchCreate,
    db=Depends(get_db),
):
    entries = [e.model_dump() for e in data.entries]
    return await db_module.add_calendar_entries_batch(db, entries)


@router.delete("/api/calendar/entries/{entry_id}", status_code=204)
async def delete_calendar_entry_endpoint(entry_id: int, db=Depends(get_db)):
    deleted = await db_module.remove_calendar_entry(db, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
