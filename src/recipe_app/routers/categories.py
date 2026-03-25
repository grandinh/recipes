from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from recipe_app.db import get_db, list_categories, create_category, delete_category
from recipe_app.models import CategoryResponse

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str


@router.get("", response_model=list[CategoryResponse])
async def list_categories_endpoint(db=Depends(get_db)):
    return await list_categories(db)


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category_endpoint(data: CategoryCreate, db=Depends(get_db)):
    return await create_category(db, data.name)


@router.delete("/{category_id}", status_code=204)
async def delete_category_endpoint(category_id: int, db=Depends(get_db)):
    result = await delete_category(db, category_id)
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")
