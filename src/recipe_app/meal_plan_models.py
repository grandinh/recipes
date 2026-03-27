"""Pydantic models for meal plans and grocery lists."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, model_validator


class MealPlanCreate(BaseModel):
    """POST payload for creating a meal plan."""

    name: str


class MealPlanUpdate(BaseModel):
    """PATCH payload for updating a meal plan."""

    name: str | None = None


class MealPlanEntryCreate(BaseModel):
    """POST payload for adding a recipe to a meal plan."""

    recipe_id: int
    date: str
    meal_slot: Literal["breakfast", "lunch", "dinner", "snack"]
    servings_override: int | None = None


class GroceryListGenerate(BaseModel):
    """POST payload for generating a grocery list."""

    meal_plan_id: int | None = None
    recipe_ids: list[int] | None = None
    name: str | None = None
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


class GroceryItemUpdate(BaseModel):
    """PATCH payload for toggling a grocery item's checked state."""

    is_checked: bool
