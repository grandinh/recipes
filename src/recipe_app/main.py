from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2_fragments.fastapi import Jinja2Blocks
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders

from recipe_app.config import settings
from recipe_app.db import (
    lifespan, get_db, list_recipes, get_recipe, create_recipe,
    update_recipe, delete_recipe, search_recipes, list_categories,
    list_meal_plans, get_meal_plan, create_meal_plan, add_meal_plan_entry,
    remove_meal_plan_entry, delete_meal_plan,
    list_grocery_lists, get_grocery_list, generate_grocery_list,
    check_grocery_item, add_grocery_item, delete_grocery_list,
    list_pantry_items, add_pantry_item, delete_pantry_item,
)
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams
from recipe_app.photos import save_photo, delete_photo
from recipe_app.routers import recipes, categories, search, meal_plans, pantry


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
app.include_router(meal_plans.router)
app.include_router(pantry.router)

# Static files and templates
_static_dir = Path(__file__).parent.parent.parent / "static"
_template_dir = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Mount photo storage — ensure dirs exist before mount to avoid first-run race
_photo_dir = settings.photo_dir
_photo_dir.mkdir(parents=True, exist_ok=True)
(_photo_dir / "originals").mkdir(exist_ok=True)
(_photo_dir / "thumbnails").mkdir(exist_ok=True)
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


# --- Meal Plans web UI ---

@app.get("/meal-plans", response_class=HTMLResponse)
async def meal_plans_page(request: Request):
    db = get_db(request)
    plans = await list_meal_plans(db)
    return templates.TemplateResponse(request, "meal_plans.html", {"plans": plans})


@app.get("/meal-plans/{plan_id}", response_class=HTMLResponse)
async def meal_plan_detail_page(request: Request, plan_id: int):
    db = get_db(request)
    plan = await get_meal_plan(db, plan_id)
    if plan is None:
        return HTMLResponse("Meal plan not found", status_code=404)
    all_recipes = await list_recipes(db, limit=1000)
    return templates.TemplateResponse(request, "meal_plan_detail.html", {
        "plan": plan, "all_recipes": all_recipes,
    })


@app.post("/meal-plans")
async def create_meal_plan_submit(request: Request):
    form = await request.form()
    db = get_db(request)
    name = form.get("name", "New Meal Plan")
    plan = await create_meal_plan(db, name)
    return RedirectResponse(f"/meal-plans/{plan['id']}", status_code=303)


@app.post("/meal-plans/{plan_id}/add-recipe")
async def add_recipe_to_plan_submit(
    request: Request, plan_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    await add_meal_plan_entry(
        db, plan_id,
        recipe_id=int(form.get("recipe_id")),
        date=form.get("date"),
        meal_slot=form.get("meal_slot"),
    )
    if hx_request:
        plan = await get_meal_plan(db, plan_id)
        return templates.TemplateResponse(
            request, "meal_plan_detail.html", {"plan": plan, "all_recipes": []},
            block_name="entries_list",
        )
    return RedirectResponse(f"/meal-plans/{plan_id}", status_code=303)


@app.post("/meal-plans/entries/{entry_id}/remove")
async def remove_entry_submit(request: Request, entry_id: int):
    db = get_db(request)
    await remove_meal_plan_entry(db, entry_id)
    referer = request.headers.get("referer", "/meal-plans")
    return RedirectResponse(referer, status_code=303)


@app.post("/meal-plans/{plan_id}/delete")
async def delete_meal_plan_submit(request: Request, plan_id: int):
    db = get_db(request)
    await delete_meal_plan(db, plan_id)
    return RedirectResponse("/meal-plans", status_code=303)


# --- Grocery Lists web UI ---

@app.get("/grocery-lists", response_class=HTMLResponse)
async def grocery_lists_page(request: Request):
    db = get_db(request)
    lists = await list_grocery_lists(db)
    return templates.TemplateResponse(request, "grocery_lists.html", {"lists": lists})


@app.get("/grocery-lists/{list_id}", response_class=HTMLResponse)
async def grocery_list_detail_page(request: Request, list_id: int):
    db = get_db(request)
    glist = await get_grocery_list(db, list_id)
    if glist is None:
        return HTMLResponse("Grocery list not found", status_code=404)
    return templates.TemplateResponse(request, "grocery_list_detail.html", {"glist": glist})


@app.post("/grocery-lists/generate")
async def generate_grocery_list_submit(request: Request):
    form = await request.form()
    db = get_db(request)
    plan_id = int(form.get("meal_plan_id")) if form.get("meal_plan_id") else None
    name = form.get("name") or None
    glist = await generate_grocery_list(db, name=name, meal_plan_id=plan_id)
    return RedirectResponse(f"/grocery-lists/{glist['id']}", status_code=303)


@app.post("/grocery-lists/{list_id}/check/{item_id}")
async def check_item_submit(
    request: Request, list_id: int, item_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    is_checked = form.get("is_checked") == "1"
    item = await check_grocery_item(db, item_id, is_checked)
    if hx_request and item:
        return templates.TemplateResponse(
            request, "grocery_list_detail.html",
            {"item": item, "glist": {"id": list_id}},
            block_name="grocery_item",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/grocery-lists/{list_id}/add-item")
async def add_item_submit(
    request: Request, list_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    text = form.get("text", "").strip()
    if text:
        await add_grocery_item(db, list_id, text)
    if hx_request:
        glist = await get_grocery_list(db, list_id)
        return templates.TemplateResponse(
            request, "grocery_list_detail.html", {"glist": glist},
            block_name="items_list",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/grocery-lists/{list_id}/delete")
async def delete_grocery_list_submit(request: Request, list_id: int):
    db = get_db(request)
    await delete_grocery_list(db, list_id)
    return RedirectResponse("/grocery-lists", status_code=303)


# --- Pantry web UI ---

@app.get("/pantry", response_class=HTMLResponse)
async def pantry_page(request: Request):
    db = get_db(request)
    items = await list_pantry_items(db)
    return templates.TemplateResponse(request, "pantry.html", {"items": items})


@app.post("/pantry/add")
async def add_pantry_submit(
    request: Request,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    name = form.get("name", "").strip()
    if name:
        await add_pantry_item(db, name)
    if hx_request:
        items = await list_pantry_items(db)
        return templates.TemplateResponse(
            request, "pantry.html", {"items": items},
            block_name="pantry_list",
        )
    return RedirectResponse("/pantry", status_code=303)


@app.post("/pantry/delete/{item_id}")
async def delete_pantry_submit(
    request: Request, item_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    await delete_pantry_item(db, item_id)
    if hx_request:
        items = await list_pantry_items(db)
        return templates.TemplateResponse(
            request, "pantry.html", {"items": items},
            block_name="pantry_list",
        )
    return RedirectResponse("/pantry", status_code=303)


@app.get("/pantry/what-can-i-make", response_class=HTMLResponse)
async def pantry_matches_page(request: Request, max_missing: int = 2):
    from recipe_app.pantry_matcher import find_matching_recipes

    db = get_db(request)
    items = await list_pantry_items(db)
    if not items:
        return templates.TemplateResponse(request, "pantry_matches.html", {
            "matches": [], "pantry_empty": True, "max_missing": max_missing,
        })
    matches = await find_matching_recipes(db, items, max_missing)
    return templates.TemplateResponse(request, "pantry_matches.html", {
        "matches": matches, "pantry_empty": False, "max_missing": max_missing,
    })


# --- Web UI form POST handlers ---

@app.post("/add")
async def add_recipe_submit(request: Request):
    db = get_db(request)
    form = await request.form()
    recipe_data = _form_to_recipe_create(form)
    result = await create_recipe(db, recipe_data)

    # Handle photo upload (outside _write_lock — Pillow processing is CPU-bound)
    await _handle_photo_upload(form, db, result["id"])

    return RedirectResponse(f"/recipe/{result['id']}", status_code=303)


@app.post("/edit/{recipe_id}")
async def edit_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    form = await request.form()

    # Fetch old photo path for cleanup if replaced
    old_recipe = await get_recipe(db, recipe_id)
    old_photo = old_recipe["photo_path"] if old_recipe else None

    recipe_data = _form_to_recipe_update(form)
    await update_recipe(db, recipe_id, recipe_data)

    # Handle photo upload and clean up old file
    new_photo = await _handle_photo_upload(form, db, recipe_id)
    if new_photo and old_photo:
        delete_photo(old_photo)

    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/delete/{recipe_id}")
async def delete_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    # Fetch photo path before deletion for cleanup
    recipe = await get_recipe(db, recipe_id)
    photo_path = recipe["photo_path"] if recipe else None

    await delete_recipe(db, recipe_id)

    if photo_path:
        delete_photo(photo_path)

    return RedirectResponse("/", status_code=303)


def _form_to_recipe_create(form) -> RecipeCreate:
    """Parse HTML form data into a RecipeCreate model with sanitization."""
    ingredients_raw = form.get("ingredients", "")
    ingredients = [line.strip() for line in ingredients_raw.split("\n") if line.strip()] or None

    categories_raw = form.get("categories", "")
    categories_list = [c.strip() for c in categories_raw.split(",") if c.strip()] or None

    nutritional_info = _parse_nutrition_form(form)

    return RecipeCreate(
        title=form.get("title", "Untitled"),
        description=form.get("description") or None,
        ingredients=ingredients,
        directions=form.get("directions") or None,
        notes=form.get("notes") or None,
        source_url=form.get("source_url") or None,
        image_url=form.get("image_url") or None,
        prep_time_minutes=int(form.get("prep_time_minutes")) if form.get("prep_time_minutes") else None,
        cook_time_minutes=int(form.get("cook_time_minutes")) if form.get("cook_time_minutes") else None,
        servings=form.get("servings") or None,
        rating=int(form.get("rating")) if form.get("rating") else None,
        difficulty=form.get("difficulty") or None,
        cuisine=form.get("cuisine") or None,
        nutritional_info=nutritional_info,
        categories=categories_list,
    )


def _form_to_recipe_update(form) -> RecipeUpdate:
    """Parse HTML form data into a RecipeUpdate model."""
    ingredients_raw = form.get("ingredients", "")
    ingredients = [line.strip() for line in ingredients_raw.split("\n") if line.strip()] or None

    categories_raw = form.get("categories", "")
    categories_list = [c.strip() for c in categories_raw.split(",") if c.strip()] or None

    nutritional_info = _parse_nutrition_form(form)

    return RecipeUpdate(
        title=form.get("title") or None,
        description=form.get("description") or None,
        ingredients=ingredients,
        directions=form.get("directions") or None,
        notes=form.get("notes") or None,
        source_url=form.get("source_url") or None,
        image_url=form.get("image_url") or None,
        prep_time_minutes=int(form.get("prep_time_minutes")) if form.get("prep_time_minutes") else None,
        cook_time_minutes=int(form.get("cook_time_minutes")) if form.get("cook_time_minutes") else None,
        servings=form.get("servings") or None,
        rating=int(form.get("rating")) if form.get("rating") else None,
        difficulty=form.get("difficulty") or None,
        cuisine=form.get("cuisine") or None,
        nutritional_info=nutritional_info,
        categories=categories_list,
    )


def _parse_nutrition_form(form) -> dict | None:
    """Extract nutritional info key-value pairs from form data."""
    keys = form.getlist("nutrition_key")
    values = form.getlist("nutrition_value")
    pairs = {k.strip(): v.strip() for k, v in zip(keys, values) if k.strip() and v.strip()}
    return pairs or None


async def _handle_photo_upload(form, db, recipe_id: int) -> str | None:
    """Extract and process a photo from form data. Returns filename or None."""
    from starlette.datastructures import UploadFile

    photo = form.get("photo")
    if not isinstance(photo, UploadFile) or not photo.filename:
        return None

    raw = await photo.read()
    if not raw or len(raw) > settings.max_photo_size:
        return None  # Too large or empty — silently skip

    try:
        filename = await save_photo(raw)
    except ValueError:
        return None  # Invalid image — recipe saved without photo

    await update_recipe(db, recipe_id, RecipeUpdate(photo_path=filename))
    return filename


def run():
    import uvicorn
    uvicorn.run(
        "recipe_app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
