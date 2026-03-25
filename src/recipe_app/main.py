from pathlib import Path
from typing import Annotated

import bleach
from fastapi import FastAPI, Form, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2_fragments.fastapi import Jinja2Blocks
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders

from recipe_app.config import settings
from recipe_app.db import (
    lifespan, get_db, list_recipes, get_recipe, create_recipe,
    update_recipe, delete_recipe, search_recipes, list_categories,
)
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams
from recipe_app.routers import recipes, categories, search


# Allowed HTML tags for sanitization (same as scraper)
_ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + ["p", "br", "h1", "h2", "h3", "h4", "ul", "ol", "li", "img"]
_ALLOWED_ATTRS = {**bleach.ALLOWED_ATTRIBUTES, "img": ["src", "alt"]}


def _sanitize(value: str | None) -> str | None:
    """Sanitize a text field using bleach."""
    if value is None:
        return None
    return bleach.clean(value, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


app = FastAPI(title="Recipe Manager", version="0.2.0", lifespan=lifespan)


# Pure ASGI middleware for CSP (avoids BaseHTTPMiddleware response buffering)
class CSPMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_csp(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' https: data:; script-src 'self'",
                )
            await send(message)

        await self.app(scope, receive, send_with_csp)


app.add_middleware(CSPMiddleware)

# Mount API routers
app.include_router(recipes.router)
app.include_router(categories.router)
app.include_router(search.router)

# Static files and templates
_static_dir = Path(__file__).parent.parent.parent / "static"
_template_dir = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Mount photo storage
_photo_dir = settings.photo_dir
if _photo_dir.exists():
    app.mount("/photos", StaticFiles(directory=str(_photo_dir)), name="photos")

# Use Jinja2Blocks for htmx fragment rendering
templates = Jinja2Blocks(directory=str(_template_dir))


# --- Health endpoint ---

@app.get("/health")
async def health(request: Request):
    db = get_db(request)
    cursor = await db.execute("SELECT COUNT(*) AS cnt FROM recipes")
    row = await cursor.fetchone()
    return {"status": "ok", "recipe_count": row["cnt"]}


# --- Web UI routes ---

@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    sort: str = "recent",
    page: int = 1,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    limit = 24
    offset = (page - 1) * limit

    if q or category:
        params = SearchParams(q=q, category=category, sort=sort, limit=limit, offset=offset)
        recipe_rows = await search_recipes(db, params)
    else:
        recipe_rows = await list_recipes(db, limit=limit, offset=offset, sort=sort)

    cats = await list_categories(db)

    context = {
        "recipes": recipe_rows,
        "categories": cats,
        "q": q or "",
        "category": category or "",
        "sort": sort,
        "page": page,
        "has_next": len(recipe_rows) == limit,
    }

    # Return only the recipe grid block for htmx requests
    block_name = "recipe_grid" if hx_request else None
    return templates.TemplateResponse(
        request, "recipes.html", context, block_name=block_name
    )


@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
async def recipe_detail(request: Request, recipe_id: int):
    db = get_db(request)
    recipe = await get_recipe(db, recipe_id)
    if recipe is None:
        return HTMLResponse("Recipe not found", status_code=404)
    return templates.TemplateResponse(request, "recipe_detail.html", {
        "recipe": recipe,
    })


@app.get("/add", response_class=HTMLResponse)
async def add_recipe_form(request: Request):
    db = get_db(request)
    cats = await list_categories(db)
    return templates.TemplateResponse(request, "recipe_form.html", {
        "recipe": None,
        "categories": cats,
    })


@app.get("/edit/{recipe_id}", response_class=HTMLResponse)
async def edit_recipe_form(request: Request, recipe_id: int):
    db = get_db(request)
    recipe = await get_recipe(db, recipe_id)
    if recipe is None:
        return HTMLResponse("Recipe not found", status_code=404)
    cats = await list_categories(db)
    return templates.TemplateResponse(request, "recipe_form.html", {
        "recipe": recipe,
        "categories": cats,
    })


# --- Web UI form POST handlers ---

@app.post("/add")
async def add_recipe_submit(request: Request):
    db = get_db(request)
    form = await request.form()
    recipe_data = _form_to_recipe_create(form)
    result = await create_recipe(db, recipe_data)
    return RedirectResponse(f"/recipe/{result['id']}", status_code=303)


@app.post("/edit/{recipe_id}")
async def edit_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    form = await request.form()
    recipe_data = _form_to_recipe_update(form)
    await update_recipe(db, recipe_id, recipe_data)
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/delete/{recipe_id}")
async def delete_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    await delete_recipe(db, recipe_id)
    return RedirectResponse("/", status_code=303)


def _form_to_recipe_create(form) -> RecipeCreate:
    """Parse HTML form data into a RecipeCreate model with sanitization."""
    ingredients_raw = form.get("ingredients", "")
    ingredients = [line.strip() for line in ingredients_raw.split("\n") if line.strip()] or None

    categories_raw = form.get("categories", "")
    categories_list = [c.strip() for c in categories_raw.split(",") if c.strip()] or None

    nutritional_info = _parse_nutrition_form(form)

    return RecipeCreate(
        title=_sanitize(form.get("title", "Untitled")),
        description=_sanitize(form.get("description")) or None,
        ingredients=ingredients,
        directions=_sanitize(form.get("directions")) or None,
        notes=_sanitize(form.get("notes")) or None,
        source_url=form.get("source_url") or None,
        image_url=form.get("image_url") or None,
        prep_time_minutes=int(form.get("prep_time_minutes")) if form.get("prep_time_minutes") else None,
        cook_time_minutes=int(form.get("cook_time_minutes")) if form.get("cook_time_minutes") else None,
        servings=form.get("servings") or None,
        rating=int(form.get("rating")) if form.get("rating") else None,
        difficulty=form.get("difficulty") or None,
        cuisine=_sanitize(form.get("cuisine")) or None,
        nutritional_info=nutritional_info,
        categories=categories_list,
    )


def _form_to_recipe_update(form) -> RecipeUpdate:
    """Parse HTML form data into a RecipeUpdate model with sanitization."""
    ingredients_raw = form.get("ingredients", "")
    ingredients = [line.strip() for line in ingredients_raw.split("\n") if line.strip()] or None

    categories_raw = form.get("categories", "")
    categories_list = [c.strip() for c in categories_raw.split(",") if c.strip()] or None

    nutritional_info = _parse_nutrition_form(form)

    return RecipeUpdate(
        title=_sanitize(form.get("title")) or None,
        description=_sanitize(form.get("description")) or None,
        ingredients=ingredients,
        directions=_sanitize(form.get("directions")) or None,
        notes=_sanitize(form.get("notes")) or None,
        source_url=form.get("source_url") or None,
        image_url=form.get("image_url") or None,
        prep_time_minutes=int(form.get("prep_time_minutes")) if form.get("prep_time_minutes") else None,
        cook_time_minutes=int(form.get("cook_time_minutes")) if form.get("cook_time_minutes") else None,
        servings=form.get("servings") or None,
        rating=int(form.get("rating")) if form.get("rating") else None,
        difficulty=form.get("difficulty") or None,
        cuisine=_sanitize(form.get("cuisine")) or None,
        nutritional_info=nutritional_info,
        categories=categories_list,
    )


def _parse_nutrition_form(form) -> dict | None:
    """Extract nutritional info key-value pairs from form data."""
    keys = form.getlist("nutrition_key")
    values = form.getlist("nutrition_value")
    pairs = {k.strip(): v.strip() for k, v in zip(keys, values) if k.strip() and v.strip()}
    return pairs or None


def run():
    import uvicorn
    uvicorn.run(
        "recipe_app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
