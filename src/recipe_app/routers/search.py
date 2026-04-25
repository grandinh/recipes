from fastapi import APIRouter, Depends, Query
from typing import Literal

from recipe_app.db import get_db, search_recipes
from recipe_app.models import RecipeResponse, SearchParams

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[RecipeResponse])
async def search_recipes_endpoint(
    q: str | None = None,
    category: str | None = None,
    rating_min: int | None = Query(None, ge=1, le=5),
    rating_max: int | None = Query(None, ge=1, le=5),
    cuisine: str | None = None,
    is_favorite: bool | None = None,
    # NOTE: sort keys mirrored in db.py (list_recipes + search_recipes order maps), models.SearchParams, routers/search.py, routers/recipes.py — keep in sync.
    sort: Literal["name", "rating", "recent", "last_cooked"] = "recent",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    params = SearchParams(
        q=q,
        category=category,
        rating_min=rating_min,
        rating_max=rating_max,
        cuisine=cuisine,
        is_favorite=is_favorite,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return await search_recipes(db, params)
