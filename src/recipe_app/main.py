import asyncio
import logging
import time
from datetime import date, timedelta
from uuid import uuid4
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2_fragments.fastapi import Jinja2Blocks
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders, UploadFile

from recipe_app.config import settings
from recipe_app.db import (
    lifespan, get_db, list_recipes, get_recipe, create_recipe,
    update_recipe, delete_recipe, search_recipes, list_categories,
    toggle_favorite, set_rating,
    list_meal_plans, get_meal_plan, create_meal_plan, add_meal_plan_entry,
    remove_meal_plan_entry, delete_meal_plan,
    get_meal_plan_week, list_recipe_titles,
    list_grocery_lists, get_grocery_list, generate_grocery_list,
    check_grocery_item, add_grocery_item, delete_grocery_list,
    delete_grocery_item, clear_checked_grocery_items, move_checked_to_pantry,
    add_recipe_to_grocery_list,
    list_pantry_items, add_pantry_item, delete_pantry_item,
)
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams
from recipe_app.paprika_import import (
    MAX_IMPORT_SIZE, ImportResult, ErroredRecipe,
    parse_paprika_archive, import_paprika_recipes,
)
from recipe_app.photos import save_photo, delete_photo
from recipe_app.routers import recipes, categories, search, meal_plans, pantry

logger = logging.getLogger(__name__)

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

# Custom Jinja2 date filters for calendar view
templates.env.filters["weekday_short"] = lambda d: d.strftime("%a")
templates.env.filters["day_num"] = lambda d: d.strftime("%-d")
templates.env.filters["month_day"] = lambda d: d.strftime("%b %-d")
templates.env.filters["isodate"] = lambda d: d.isoformat() if hasattr(d, "isoformat") else str(d)


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


MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snack"]


@app.get("/meal-plans/{plan_id}", response_class=HTMLResponse)
async def meal_plan_detail_page(
    request: Request,
    plan_id: int,
    week: str | None = None,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)

    # Parse and snap to Monday
    if week:
        try:
            week_date = date.fromisoformat(week)
        except ValueError:
            return HTMLResponse("Invalid week parameter. Use YYYY-MM-DD format.", status_code=400)
    else:
        week_date = date.today()

    block_name = "calendar_grid" if hx_request else None
    return await _render_calendar_grid(request, db, plan_id, week_date, block_name=block_name)


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
    entry_date = form.get("date", "")
    meal_slot = form.get("meal_slot", "")

    # Validate meal_slot
    if meal_slot not in MEAL_SLOTS:
        return HTMLResponse("Invalid meal slot", status_code=400)

    await add_meal_plan_entry(
        db, plan_id,
        recipe_id=int(form.get("recipe_id")),
        date=entry_date,
        meal_slot=meal_slot,
    )
    if hx_request:
        # Re-render the calendar grid for the week containing the added entry
        try:
            entry_d = date.fromisoformat(entry_date)
        except ValueError:
            entry_d = date.today()
        return await _render_calendar_grid(request, db, plan_id, entry_d)
    return RedirectResponse(f"/meal-plans/{plan_id}", status_code=303)


@app.post("/meal-plans/{plan_id}/entries/{entry_id}/remove")
async def remove_entry_submit(
    request: Request, plan_id: int, entry_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    await remove_meal_plan_entry(db, entry_id)
    if hx_request:
        week_str = form.get("week_start", "")
        try:
            week_date = date.fromisoformat(week_str)
        except ValueError:
            week_date = date.today()
        return await _render_calendar_grid(request, db, plan_id, week_date)
    # Validate referer to prevent open redirect
    from urllib.parse import urlparse
    referer = request.headers.get("referer", "/meal-plans")
    parsed = urlparse(referer)
    if parsed.netloc:  # external URL — redirect to safe default
        referer = "/meal-plans"
    return RedirectResponse(referer, status_code=303)


@app.post("/meal-plans/{plan_id}/delete")
async def delete_meal_plan_submit(request: Request, plan_id: int):
    db = get_db(request)
    await delete_meal_plan(db, plan_id)
    return RedirectResponse("/meal-plans", status_code=303)


# --- Paprika Import web UI ---

# Background import task storage: task_id -> (created_at, result_or_None)
_import_tasks: dict[str, tuple[float, ImportResult | None]] = {}
_import_task_refs: set[asyncio.Task] = set()
_IMPORT_TASK_TTL = 3600  # 1 hour


def _cleanup_stale_imports():
    """Evict import tasks older than TTL."""
    cutoff = time.time() - _IMPORT_TASK_TTL
    stale = [k for k, (ts, _) in _import_tasks.items() if ts < cutoff]
    for k in stale:
        del _import_tasks[k]


@app.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {"error": None})


@app.post("/import")
async def import_upload(request: Request):

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return templates.TemplateResponse(request, "import.html", {
            "error": "Please select a .paprikarecipes file.",
        })

    # Stream-read with size check
    chunks = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_IMPORT_SIZE:
            return templates.TemplateResponse(request, "import.html", {
                "error": f"File exceeds maximum size of {MAX_IMPORT_SIZE // (1024*1024)} MB.",
            })
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    if not file_bytes:
        return templates.TemplateResponse(request, "import.html", {
            "error": "Empty file uploaded.",
        })

    # Validate ZIP format
    try:
        paprika_recipes = await asyncio.to_thread(parse_paprika_archive, file_bytes)
    except ValueError as exc:
        return templates.TemplateResponse(request, "import.html", {
            "error": str(exc),
        })

    if not paprika_recipes:
        return templates.TemplateResponse(request, "import.html", {
            "error": "No recipes found in archive.",
        })

    # Start background import task
    _cleanup_stale_imports()
    task_id = uuid4().hex
    _import_tasks[task_id] = (time.time(), None)
    db = get_db(request)

    async def _run_import():
        try:
            result = await import_paprika_recipes(db, paprika_recipes)
            _import_tasks[task_id] = (time.time(), result)
        except Exception as exc:
            logger.exception("Import task %s failed", task_id)
            _import_tasks[task_id] = (time.time(), ImportResult(errors=[ErroredRecipe(
                title="Import", error=str(exc),
            )]))

    task = asyncio.create_task(_run_import())
    _import_task_refs.add(task)
    task.add_done_callback(_import_task_refs.discard)
    return RedirectResponse(f"/import/status/{task_id}", status_code=303)


@app.get("/import/status/{task_id}", response_class=HTMLResponse)
async def import_status(request: Request, task_id: str):
    _cleanup_stale_imports()
    if task_id not in _import_tasks:
        return HTMLResponse("Import task not found", status_code=404)

    ts, result = _import_tasks[task_id]
    if result is None:
        # Still processing
        return templates.TemplateResponse(request, "import_progress.html", {
            "task_id": task_id,
        })

    # Done — render results and clean up
    del _import_tasks[task_id]
    return templates.TemplateResponse(request, "import_results.html", {
        "result": result,
    })


async def _render_calendar_grid(
    request: Request,
    db: "aiosqlite.Connection",
    plan_id: int,
    ref_date: date,
    block_name: str | None = "calendar_grid",
) -> HTMLResponse:
    """Render the meal plan calendar (full page or just the grid block)."""
    week_start = ref_date - timedelta(days=ref_date.weekday())
    week_end = week_start + timedelta(days=6)

    plan = await get_meal_plan_week(db, plan_id, week_start.isoformat(), week_end.isoformat())
    if plan is None:
        return HTMLResponse("Meal plan not found", status_code=404)

    # Only load recipe titles for full-page render (dropdown is outside the grid block)
    all_recipes = await list_recipe_titles(db) if block_name is None else []
    days = [week_start + timedelta(days=i) for i in range(7)]

    entries_by_cell: dict[tuple[str, str], list[dict]] = {}
    for entry in plan.get("entries", []):
        key = (entry["date"], entry["meal_slot"])
        entries_by_cell.setdefault(key, []).append(entry)

    context = {
        "plan": plan,
        "all_recipes": all_recipes,
        "days": days,
        "week_start": week_start,
        "week_end": week_end,
        "prev_week": (week_start - timedelta(days=7)).isoformat(),
        "next_week": (week_start + timedelta(days=7)).isoformat(),
        "entries_by_cell": entries_by_cell,
        "today": date.today(),
        "meal_slots": MEAL_SLOTS,
    }
    return templates.TemplateResponse(
        request, "meal_plan_detail.html", context,
        block_name=block_name,
    )


# --- Grocery Lists web UI ---

def _build_aisle_groups(glist: dict) -> list[tuple[str, list[dict]]]:
    """Group grocery list items by aisle for template rendering."""
    aisle_groups: list[tuple[str, list[dict]]] = []
    aisle_map: dict[str, list[dict]] = {}
    for item in glist.get("items", []):
        aisle = item.get("aisle") or "Other"
        if aisle not in aisle_map:
            aisle_map[aisle] = []
            aisle_groups.append((aisle, aisle_map[aisle]))
        aisle_map[aisle].append(item)
    return aisle_groups


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
    aisle_groups = _build_aisle_groups(glist)
    return templates.TemplateResponse(request, "grocery_list_detail.html", {
        "glist": glist,
        "aisle_groups": aisle_groups,
    })


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
        aisle_groups = _build_aisle_groups(glist)
        return templates.TemplateResponse(
            request, "grocery_list_detail.html",
            {"glist": glist, "aisle_groups": aisle_groups},
            block_name="items_list",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/grocery-lists/{list_id}/delete")
async def delete_grocery_list_submit(request: Request, list_id: int):
    db = get_db(request)
    await delete_grocery_list(db, list_id)
    return RedirectResponse("/grocery-lists", status_code=303)


@app.post("/grocery-lists/{list_id}/delete-item/{item_id}")
async def delete_grocery_item_submit(
    request: Request, list_id: int, item_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    await delete_grocery_item(db, item_id)
    if hx_request:
        glist = await get_grocery_list(db, list_id)
        aisle_groups = _build_aisle_groups(glist)
        return templates.TemplateResponse(
            request, "grocery_list_detail.html",
            {"glist": glist, "aisle_groups": aisle_groups},
            block_name="items_list",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/grocery-lists/{list_id}/clear-checked")
async def clear_checked_submit(
    request: Request, list_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    await clear_checked_grocery_items(db, list_id)
    if hx_request:
        glist = await get_grocery_list(db, list_id)
        aisle_groups = _build_aisle_groups(glist)
        return templates.TemplateResponse(
            request, "grocery_list_detail.html",
            {"glist": glist, "aisle_groups": aisle_groups},
            block_name="items_list",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/grocery-lists/{list_id}/move-to-pantry")
async def move_to_pantry_submit(
    request: Request, list_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    result = await move_checked_to_pantry(db, list_id)
    if hx_request:
        glist = await get_grocery_list(db, list_id)
        aisle_groups = _build_aisle_groups(glist)
        return templates.TemplateResponse(
            request, "grocery_list_detail.html",
            {"glist": glist, "aisle_groups": aisle_groups,
             "move_result": result},
            block_name="items_list",
        )
    return RedirectResponse(f"/grocery-lists/{list_id}", status_code=303)


@app.post("/recipes/{recipe_id}/add-to-grocery-list")
async def add_recipe_to_grocery_list_submit(request: Request, recipe_id: int):
    db = get_db(request)
    try:
        glist = await add_recipe_to_grocery_list(db, recipe_id)
    except ValueError:
        return HTMLResponse("Recipe not found", status_code=404)
    return RedirectResponse(f"/grocery-lists/{glist['id']}", status_code=303)


# --- Pantry web UI ---

def _pantry_context(items: list[dict]) -> dict:
    """Build template context with date strings for expiration highlighting."""
    today = date.today()
    return {
        "items": items,
        "now": today.isoformat(),
        "now_plus_7": (today + timedelta(days=7)).isoformat(),
    }


@app.get("/pantry", response_class=HTMLResponse)
async def pantry_page(request: Request):
    db = get_db(request)
    items = await list_pantry_items(db)
    return templates.TemplateResponse(request, "pantry.html", _pantry_context(items))


@app.post("/pantry/add")
async def add_pantry_submit(
    request: Request,
    hx_request: Annotated[str | None, Header()] = None,
):
    form = await request.form()
    db = get_db(request)
    name = form.get("name", "").strip()
    expiration_date = form.get("expiration_date", "").strip() or None
    if name:
        await add_pantry_item(db, name, expiration_date=expiration_date)
    if hx_request:
        items = await list_pantry_items(db)
        return templates.TemplateResponse(
            request, "pantry.html", _pantry_context(items),
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
            request, "pantry.html", _pantry_context(items),
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

    # Process photo first (outside _write_lock, Pillow is CPU-bound)
    photo_filename = await _handle_photo_upload(form)

    recipe_data = _form_to_recipe_create(form)
    if photo_filename:
        recipe_data.photo_path = photo_filename
    result = await create_recipe(db, recipe_data)
    return RedirectResponse(f"/recipe/{result['id']}", status_code=303)


@app.post("/edit/{recipe_id}")
async def edit_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    form = await request.form()
    old_recipe = await get_recipe(db, recipe_id)
    old_photo = old_recipe["photo_path"] if old_recipe else None

    photo_filename = await _handle_photo_upload(form)

    recipe_data = _form_to_recipe_update(form)
    if photo_filename:
        recipe_data.photo_path = photo_filename
    await update_recipe(db, recipe_id, recipe_data)

    # Clean up old photo after successful DB update
    if photo_filename and old_photo:
        await delete_photo(old_photo)

    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/delete/{recipe_id}")
async def delete_recipe_submit(request: Request, recipe_id: int):
    db = get_db(request)
    # Fetch photo path before deletion for cleanup
    recipe = await get_recipe(db, recipe_id)
    photo_path = recipe["photo_path"] if recipe else None

    await delete_recipe(db, recipe_id)

    if photo_path:
        await delete_photo(photo_path)

    return RedirectResponse("/", status_code=303)


# --- Recipe inline actions ---

@app.post("/recipe/{recipe_id}/base-servings")
async def set_base_servings_submit(
    request: Request,
    recipe_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    form = await request.form()
    try:
        value = int(form.get("base_servings", ""))
    except (ValueError, TypeError):
        if hx_request:
            return HTMLResponse("Invalid number", status_code=400)
        return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)

    await update_recipe(db, recipe_id, RecipeUpdate(base_servings=value))

    if hx_request:
        recipe = await get_recipe(db, recipe_id)
        if recipe is None:
            return HTMLResponse("Recipe not found", status_code=404)
        return templates.TemplateResponse(
            request, "recipe_detail.html", {"recipe": recipe},
            block_name="scaling_section",
        )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/recipe/{recipe_id}/favorite")
async def toggle_favorite_submit(
    request: Request,
    recipe_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    recipe = await toggle_favorite(db, recipe_id)
    if recipe is None:
        if hx_request:
            return HTMLResponse("Recipe not found", status_code=404)
        return RedirectResponse("/", status_code=303)

    if hx_request:
        return templates.TemplateResponse(
            request, "recipe_detail.html", {"recipe": recipe},
            block_name="favorite_toggle",
        )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/recipe/{recipe_id}/rate")
async def set_rating_submit(
    request: Request,
    recipe_id: int,
    hx_request: Annotated[str | None, Header()] = None,
):
    db = get_db(request)
    form = await request.form()
    try:
        rating = int(form.get("rating", ""))
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be 1-5")
    except (ValueError, TypeError):
        if hx_request:
            return HTMLResponse("Invalid rating", status_code=400)
        return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)

    recipe = await set_rating(db, recipe_id, rating)
    if recipe is None:
        if hx_request:
            return HTMLResponse("Recipe not found", status_code=404)
        return RedirectResponse("/", status_code=303)

    if hx_request:
        return templates.TemplateResponse(
            request, "recipe_detail.html", {"recipe": recipe},
            block_name="rating_widget",
        )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


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


async def _handle_photo_upload(form) -> str | None:
    """Extract and process a photo from form data. Returns filename or None."""
    photo = form.get("photo")
    if not isinstance(photo, UploadFile) or not photo.filename:
        return None

    raw = await photo.read()
    if not raw or len(raw) > settings.max_photo_size:
        logger.warning("Photo upload skipped: empty or exceeds %d bytes", settings.max_photo_size)
        return None

    try:
        return await save_photo(raw)
    except ValueError as exc:
        logger.warning("Photo upload rejected: %s", exc)
        return None


def run():
    import uvicorn
    uvicorn.run(
        "recipe_app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
