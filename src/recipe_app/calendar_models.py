"""Pydantic models for calendar entries and grocery lists."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, model_validator


class CalendarEntryCreate(BaseModel):
    """POST payload for adding a recipe to the calendar."""

    recipe_id: int
    date: str
    meal_slot: Literal["breakfast", "lunch", "dinner", "snack"]


class CalendarEntryBatchCreate(BaseModel):
    """POST payload for batch-adding recipes to the calendar."""

    entries: list[CalendarEntryCreate]


class GroceryListGenerate(BaseModel):
    """POST payload for generating grocery items from calendar or recipes."""

    recipe_ids: list[int] | None = None
    date_start: date | None = None
    date_end: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (self.date_start is None) != (self.date_end is None):
            raise ValueError("date_start and date_end must both be provided or both omitted")
        if self.date_start and self.date_end and self.date_start > self.date_end:
            raise ValueError("date_start must be <= date_end")
        return self


class GroceryItemCreate(BaseModel):
    """POST payload for adding an ad-hoc grocery item."""

    text: str
    aisle: str | None = None


class GroceryItemUpdate(BaseModel):
    """PATCH payload for toggling a grocery item's checked state."""

    is_checked: bool
