"""Pydantic models for meal plans and grocery lists."""

from typing import Literal

from pydantic import BaseModel


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


class GroceryItemCreate(BaseModel):
    """POST payload for adding an ad-hoc grocery item."""

    text: str


class GroceryItemUpdate(BaseModel):
    """PATCH payload for toggling a grocery item's checked state."""

    is_checked: bool
