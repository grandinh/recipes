from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class _RecipeFields(BaseModel):
    """Base fields shared by create and update models."""

    title: str | None = None
    description: str | None = None
    ingredients: list[str] | None = None
    directions: str | None = None
    notes: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    servings: str | None = None
    rating: int | None = Field(None, ge=1, le=5)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    cuisine: str | None = None
    nutritional_info: dict[str, str | int | float] | None = None
    is_favorite: bool = False
    categories: list[str] | None = None
    base_servings: int | None = Field(None, ge=1, le=100)
    photo_path: str | None = None


class RecipeCreate(_RecipeFields):
    """POST payload — title is required."""

    title: str


class RecipeUpdate(_RecipeFields):
    """PATCH payload — every field optional."""

    is_favorite: bool | None = None

    @model_validator(mode="after")
    def check_not_empty(self) -> "RecipeUpdate":
        if not any(v is not None for v in self.model_dump().values()):
            raise ValueError("At least one field must be provided")
        return self


class RecipeResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    ingredients: list[str] = Field(default_factory=list)
    directions: str | None = None
    notes: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    total_time_minutes: int | None = None
    servings: str | None = None
    rating: int | None = None
    difficulty: str | None = None
    cuisine: str | None = None
    nutritional_info: dict[str, str | int | float] | None = None
    is_favorite: bool = False
    categories: list[str] = Field(default_factory=list)
    base_servings: int | None = None
    photo_path: str | None = None
    last_cooked_at: datetime | None = None
    times_cooked: int = 0
    created_at: datetime
    updated_at: datetime


class RecipeCookEventCreate(BaseModel):
    cooked_at: datetime | None = None
    source: Literal["manual", "calendar", "import", "migration"] = "manual"
    calendar_entry_id: int | None = None
    notes: str | None = None


class RecipeCookEventResponse(BaseModel):
    id: int
    recipe_id: int
    cooked_at: datetime
    source: str
    calendar_entry_id: int | None = None
    notes: str | None = None
    created_at: datetime


class RecipeCookRecordedResponse(BaseModel):
    event: RecipeCookEventResponse
    recipe: RecipeResponse


class SearchParams(BaseModel):
    q: str | None = None
    category: str | None = None
    rating_min: int | None = Field(None, ge=1, le=5)
    rating_max: int | None = Field(None, ge=1, le=5)
    cuisine: str | None = None
    is_favorite: bool | None = None
    sort: Literal["name", "rating", "recent", "last_cooked"] = "recent"
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def check_rating_range(self) -> "SearchParams":
        if self.rating_min is not None and self.rating_max is not None:
            if self.rating_min > self.rating_max:
                raise ValueError("rating_min must not exceed rating_max")
        return self


class ImportRequest(BaseModel):
    url: str


class ImportResponse(BaseModel):
    recipe: RecipeResponse
    warnings: list[str] = Field(default_factory=list)


class CategoryResponse(BaseModel):
    id: int
    name: str
    recipe_count: int = 0


class HealthResponse(BaseModel):
    status: str = "ok"
    recipe_count: int = 0
