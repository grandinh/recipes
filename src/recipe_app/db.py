"""Database module — SQLite via aiosqlite with FTS5 full-text search."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import Request

from recipe_app.config import settings
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams
from recipe_app.sanitize import sanitize_field, sanitize_url
from recipe_app.scraper import sanitize_fts5_query  # noqa: F401 — used in search_recipes

logger = logging.getLogger(__name__)

# Write serialization — prevents transaction state pollution when multiple
# concurrent async handlers share one aiosqlite connection.
_write_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Schema path
# ---------------------------------------------------------------------------

_SCHEMA_SQL = Path(__file__).parent / "sql" / "schema.sql"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    """row_factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _recipe_dict(row: dict, categories: list[str] | None = None) -> dict:
    """Convert a raw DB row into a recipe response dict."""
    out = dict(row)

    # Deserialise JSON fields
    raw_ingredients = out.get("ingredients")
    if raw_ingredients:
        out["ingredients"] = json.loads(raw_ingredients)
    else:
        out["ingredients"] = []

    raw_nutrition = out.get("nutritional_info")
    if raw_nutrition:
        out["nutritional_info"] = json.loads(raw_nutrition)
    else:
        out["nutritional_info"] = None

    # Boolean conversion
    out["is_favorite"] = bool(out.get("is_favorite"))

    # Categories
    if categories is not None:
        out["categories"] = categories

    return out


async def _fetch_categories(db: aiosqlite.Connection, recipe_id: int) -> list[str]:
    """Return category names for a single recipe."""
    cursor = await db.execute(
        """
        SELECT c.name
          FROM categories c
          JOIN recipe_categories rc ON rc.category_id = c.id
         WHERE rc.recipe_id = ?
         ORDER BY c.name
        """,
        (recipe_id,),
    )
    rows = await cursor.fetchall()
    return [r["name"] for r in rows]


async def _fetch_categories_batch(
    db: aiosqlite.Connection, recipe_ids: list[int]
) -> dict[int, list[str]]:
    """Return {recipe_id: [category_names]} for all given IDs in one query."""
    if not recipe_ids:
        return {}
    placeholders = ",".join("?" for _ in recipe_ids)
    cursor = await db.execute(
        f"""
        SELECT rc.recipe_id, c.name
          FROM categories c
          JOIN recipe_categories rc ON rc.category_id = c.id
         WHERE rc.recipe_id IN ({placeholders})
         ORDER BY c.name
        """,
        recipe_ids,
    )
    rows = await cursor.fetchall()
    result: dict[int, list[str]] = {rid: [] for rid in recipe_ids}
    for row in rows:
        result[row["recipe_id"]].append(row["name"])
    return result


async def _ensure_categories(
    db: aiosqlite.Connection,
    recipe_id: int,
    category_names: list[str],
) -> None:
    """Replace the set of categories linked to *recipe_id*.

    Must be called inside an existing transaction.
    """
    await db.execute(
        "DELETE FROM recipe_categories WHERE recipe_id = ?", (recipe_id,)
    )
    for name in category_names:
        await db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        cursor = await db.execute("SELECT id FROM categories WHERE name = ?", (name,))
        cat = await cursor.fetchone()
        await db.execute(
            "INSERT OR IGNORE INTO recipe_categories (recipe_id, category_id) VALUES (?, ?)",
            (recipe_id, cat["id"]),
        )


async def _fts_insert(db: aiosqlite.Connection, recipe_id: int, row: dict) -> None:
    """Insert a row into the FTS5 table.  *row* must already be the DB row."""
    await db.execute(
        """
        INSERT INTO recipes_fts (rowid, title, description, ingredients, directions)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            recipe_id,
            row.get("title"),
            row.get("description"),
            row.get("ingredients"),  # stored as raw JSON string in FTS
            row.get("directions"),
        ),
    )


async def _fts_delete(db: aiosqlite.Connection, recipe_id: int) -> None:
    """Delete an FTS5 row by rowid."""
    await db.execute(
        "DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,)
    )


# ---------------------------------------------------------------------------
# Lifecycle & dependency injection
# ---------------------------------------------------------------------------

async def init_schema(db: aiosqlite.Connection) -> None:
    """Read and execute ``schema.sql``."""
    sql = _SCHEMA_SQL.read_text()
    await db.executescript(sql)


_KNOWN_TABLES = {"recipes", "categories", "recipe_categories", "meal_plans",
                 "meal_plan_entries", "grocery_lists", "grocery_list_items", "pantry_items"}


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    if table not in _KNOWN_TABLES:
        raise ValueError(f"Unknown table: {table}")
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in await cursor.fetchall())


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Apply schema migrations using PRAGMA user_version."""
    row = await (await db.execute("PRAGMA user_version")).fetchone()
    version = row["user_version"] if isinstance(row, dict) else row[0]

    if version < 1:
        db_path = str(settings.database_path)
        backup = f"{db_path}.backup-v{version}-{datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(db_path, backup)
        logger.info("Database backed up to %s before migration", backup)

        # Add new columns (idempotent)
        if not await _column_exists(db, "recipes", "base_servings"):
            await db.execute("ALTER TABLE recipes ADD COLUMN base_servings INTEGER DEFAULT NULL")
        if not await _column_exists(db, "recipes", "photo_path"):
            await db.execute("ALTER TABLE recipes ADD COLUMN photo_path TEXT DEFAULT NULL")

        # Attempt to extract integer from servings TEXT
        await db.execute("""
            UPDATE recipes SET base_servings = CAST(servings AS INTEGER)
            WHERE servings IS NOT NULL AND servings GLOB '[0-9]*'
              AND CAST(servings AS INTEGER) BETWEEN 1 AND 100
              AND base_servings IS NULL
        """)

        # v0.2 tables (idempotent with IF NOT EXISTS)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS meal_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS meal_plan_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_plan_id INTEGER NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                meal_slot TEXT NOT NULL CHECK (meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack')),
                servings_override INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS grocery_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                meal_plan_id INTEGER REFERENCES meal_plans(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS grocery_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grocery_list_id INTEGER NOT NULL REFERENCES grocery_lists(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                is_checked INTEGER NOT NULL DEFAULT 0 CHECK (is_checked IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_plan ON meal_plan_entries(meal_plan_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_recipe ON meal_plan_entries(recipe_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_date ON meal_plan_entries(meal_plan_id, date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_grocery_list_items_list ON grocery_list_items(grocery_list_id)")

        # Triggers
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_meal_plans_updated
            AFTER UPDATE ON meal_plans FOR EACH ROW BEGIN
                UPDATE meal_plans SET updated_at = datetime('now') WHERE id = NEW.id;
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_grocery_lists_updated
            AFTER UPDATE ON grocery_lists FOR EACH ROW BEGIN
                UPDATE grocery_lists SET updated_at = datetime('now') WHERE id = NEW.id;
            END
        """)

        await db.execute("PRAGMA user_version = 1")
        await db.commit()
        logger.info("Migration v0 -> v1 complete")

    if version < 2:
        # v0.3: Pantry table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pantry_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category TEXT,
                quantity REAL,
                unit TEXT,
                expiration_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pantry_items_name ON pantry_items(name COLLATE NOCASE)")
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_pantry_items_updated
            AFTER UPDATE ON pantry_items FOR EACH ROW BEGIN
                UPDATE pantry_items SET updated_at = datetime('now') WHERE id = NEW.id;
            END
        """)
        await db.execute("PRAGMA user_version = 2")
        await db.commit()
        logger.info("Migration v1 -> v2 complete")

    if version < 3:
        db_path = str(settings.database_path)
        backup = f"{db_path}.backup-v{version}-{datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(db_path, backup)
        logger.info("Database backed up to %s before v3 migration", backup)

        if not await _column_exists(db, "grocery_list_items", "aisle"):
            await db.execute(
                "ALTER TABLE grocery_list_items ADD COLUMN aisle TEXT DEFAULT 'Other'"
            )
        if not await _column_exists(db, "grocery_list_items", "recipe_id"):
            await db.execute(
                "ALTER TABLE grocery_list_items ADD COLUMN recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL"
            )
        if not await _column_exists(db, "grocery_list_items", "normalized_name"):
            await db.execute(
                "ALTER TABLE grocery_list_items ADD COLUMN normalized_name TEXT"
            )

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_grocery_list_items_recipe
                ON grocery_list_items(grocery_list_id, recipe_id)
        """)

        await db.execute("PRAGMA user_version = 3")
        await db.commit()
        logger.info("Migration v2 -> v3 complete")


@asynccontextmanager
async def lifespan(app: Any):
    """FastAPI lifespan — open/close the database connection."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = _row_to_dict
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 5000")
    await init_schema(db)
    await run_migrations(db)

    # Ensure photo directories exist
    settings.photo_dir.mkdir(parents=True, exist_ok=True)
    (settings.photo_dir / "originals").mkdir(exist_ok=True)
    (settings.photo_dir / "thumbnails").mkdir(exist_ok=True)

    app.state.db = db
    yield
    await db.close()


def get_db(request: Request) -> aiosqlite.Connection:
    """FastAPI dependency — retrieve the DB connection from app state."""
    return request.app.state.db


async def connect() -> aiosqlite.Connection:
    """Standalone connection for the MCP server (mirrors lifespan settings)."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = _row_to_dict
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 5000")
    await init_schema(db)
    await run_migrations(db)
    return db


# ---------------------------------------------------------------------------
# CRUD — Recipes
# ---------------------------------------------------------------------------

async def create_recipe(db: aiosqlite.Connection, data: RecipeCreate) -> dict:
    """Insert a new recipe with FTS5 and category rows.  Returns full dict."""
    # Sanitize text fields at the db layer so all entry points (web, API, MCP) are covered
    if data.title:
        data.title = sanitize_field(data.title)
    if data.description:
        data.description = sanitize_field(data.description)
    if data.directions:
        data.directions = sanitize_field(data.directions)
    if data.notes:
        data.notes = sanitize_field(data.notes)
    if data.cuisine:
        data.cuisine = sanitize_field(data.cuisine)
    if data.source_url:
        data.source_url = sanitize_url(data.source_url)
    if data.source_url is not None and not data.source_url.strip():
        data.source_url = None
    if data.image_url:
        data.image_url = sanitize_url(data.image_url)
    if data.ingredients:
        data.ingredients = [sanitize_field(i) for i in data.ingredients]

    fields = data.model_dump(exclude={"categories"}, exclude_none=True)

    # Serialise complex fields
    if "ingredients" in fields:
        fields["ingredients"] = json.dumps(fields["ingredients"])
    if "nutritional_info" in fields:
        fields["nutritional_info"] = json.dumps(fields["nutritional_info"])
    if "is_favorite" in fields:
        fields["is_favorite"] = int(fields["is_favorite"])

    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    values = list(fields.values())

    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")

            cursor = await db.execute(
                f"INSERT INTO recipes ({columns}) VALUES ({placeholders})",
                values,
            )
            recipe_id = cursor.lastrowid

            # Re-fetch the full row (includes generated total_time_minutes, defaults)
            cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
            row = await cursor.fetchone()

            # FTS5
            await _fts_insert(db, recipe_id, row)

            # Categories
            categories = data.categories or []
            if categories:
                await _ensure_categories(db, recipe_id, categories)

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    cat_list = await _fetch_categories(db, recipe_id)
    return _recipe_dict(row, categories=cat_list)


async def get_recipe(db: aiosqlite.Connection, recipe_id: int) -> dict | None:
    """Fetch a single recipe by id, with categories."""
    cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    categories = await _fetch_categories(db, recipe_id)
    return _recipe_dict(row, categories=categories)


async def update_recipe(
    db: aiosqlite.Connection,
    recipe_id: int,
    data: RecipeUpdate,
) -> dict | None:
    """Update non-None fields.  Returns updated dict or None if not found."""
    # Sanitize text fields at the db layer
    if data.title:
        data.title = sanitize_field(data.title)
    if data.description:
        data.description = sanitize_field(data.description)
    if data.directions:
        data.directions = sanitize_field(data.directions)
    if data.notes:
        data.notes = sanitize_field(data.notes)
    if data.cuisine:
        data.cuisine = sanitize_field(data.cuisine)
    if data.source_url:
        data.source_url = sanitize_url(data.source_url)
    if data.source_url is not None and not data.source_url.strip():
        data.source_url = None
    if data.image_url:
        data.image_url = sanitize_url(data.image_url)
    if data.ingredients:
        data.ingredients = [sanitize_field(i) for i in data.ingredients]

    # Check existence first
    cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    existing = await cursor.fetchone()
    if existing is None:
        return None

    fields = data.model_dump(exclude={"categories"}, exclude_none=True)

    # Serialise complex fields
    if "ingredients" in fields:
        fields["ingredients"] = json.dumps(fields["ingredients"])
    if "nutritional_info" in fields:
        fields["nutritional_info"] = json.dumps(fields["nutritional_info"])
    if "is_favorite" in fields:
        fields["is_favorite"] = int(fields["is_favorite"])

    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")

            if fields:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                values = list(fields.values()) + [recipe_id]
                await db.execute(
                    f"UPDATE recipes SET {set_clause} WHERE id = ?",
                    values,
                )

            # Re-fetch row
            cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
            row = await cursor.fetchone()

            # FTS5 delete + reinsert
            await _fts_delete(db, recipe_id)
            await _fts_insert(db, recipe_id, row)

            # Categories
            if data.categories is not None:
                await _ensure_categories(db, recipe_id, data.categories)

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    categories = await _fetch_categories(db, recipe_id)
    return _recipe_dict(row, categories=categories)


async def delete_recipe(db: aiosqlite.Connection, recipe_id: int) -> bool:
    """Delete a recipe, its FTS5 entry, and cascade categories.

    Also sets grocery_list_items.recipe_id to NULL (application-layer FK
    enforcement since ALTER TABLE silently ignores FK constraints).
    Returns True if a row was deleted.
    """
    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _fts_delete(db, recipe_id)
            # Application-layer FK cleanup for grocery list items
            await db.execute(
                "UPDATE grocery_list_items SET recipe_id = NULL WHERE recipe_id = ?",
                (recipe_id,),
            )
            cursor = await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return cursor.rowcount > 0


async def toggle_favorite(db: aiosqlite.Connection, recipe_id: int) -> dict | None:
    """Atomically flip is_favorite for a recipe.

    Uses ``1 - is_favorite`` to avoid read-then-write races and skips
    FTS updates (is_favorite is not indexed).  Returns updated recipe
    dict or None if not found.
    """
    async with _write_lock:
        cursor = await db.execute(
            "UPDATE recipes SET is_favorite = 1 - is_favorite WHERE id = ?",
            (recipe_id,),
        )
        await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_recipe(db, recipe_id)


async def set_rating(db: aiosqlite.Connection, recipe_id: int, rating: int) -> dict | None:
    """Set recipe rating (1-5).  Skips FTS update (rating not indexed).

    Returns updated recipe dict or None if not found.
    """
    if not 1 <= rating <= 5:
        raise ValueError(f"Rating must be 1-5, got {rating}")
    async with _write_lock:
        cursor = await db.execute(
            "UPDATE recipes SET rating = ? WHERE id = ?",
            (rating, recipe_id),
        )
        await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_recipe(db, recipe_id)


async def list_recipes(
    db: aiosqlite.Connection,
    limit: int = 50,
    offset: int = 0,
    sort: str = "recent",
) -> list[dict]:
    """List recipes with pagination and sorting.  Includes categories."""
    order = {
        "name": "r.title ASC",
        "rating": "r.rating DESC NULLS LAST, r.created_at DESC",
        "recent": "r.created_at DESC",
    }.get(sort, "r.created_at DESC")

    cursor = await db.execute(
        f"""
        SELECT r.*
          FROM recipes r
         ORDER BY {order}
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = await cursor.fetchall()

    ids = [row["id"] for row in rows]
    cats_map = await _fetch_categories_batch(db, ids)
    return [_recipe_dict(row, categories=cats_map.get(row["id"], [])) for row in rows]


async def search_recipes(
    db: aiosqlite.Connection,
    params: SearchParams,
) -> list[dict]:
    """Full-text + filter search with BM25 ranking when *q* is provided."""
    conditions: list[str] = []
    bindings: list[Any] = []

    use_fts = params.q is not None and params.q.strip() != ""

    if use_fts:
        safe_q = sanitize_fts5_query(params.q)
        conditions.append("recipes_fts.rowid = r.id")
        conditions.append("recipes_fts MATCH ?")
        bindings.append(safe_q)

    if params.category:
        conditions.append(
            """
            r.id IN (
                SELECT rc.recipe_id
                  FROM recipe_categories rc
                  JOIN categories c ON c.id = rc.category_id
                 WHERE c.name = ?
            )
            """
        )
        bindings.append(params.category)

    if params.rating_min is not None:
        conditions.append("r.rating >= ?")
        bindings.append(params.rating_min)

    if params.rating_max is not None:
        conditions.append("r.rating <= ?")
        bindings.append(params.rating_max)

    if params.cuisine is not None:
        conditions.append("r.cuisine = ?")
        bindings.append(params.cuisine)

    if params.is_favorite is not None:
        conditions.append("r.is_favorite = ?")
        bindings.append(int(params.is_favorite))

    where = " AND ".join(conditions) if conditions else "1"

    if use_fts:
        from_clause = "recipes r, recipes_fts"
        order_default = "bm25(recipes_fts)"
    else:
        from_clause = "recipes r"
        order_default = "r.created_at DESC"

    order = {
        "name": "r.title ASC",
        "rating": "r.rating DESC NULLS LAST, r.created_at DESC",
        "recent": "r.created_at DESC",
    }.get(params.sort, order_default)

    # If sort wasn't explicitly specified and we have FTS, use BM25
    if use_fts and params.sort == "recent":
        order = "bm25(recipes_fts)"

    sql = f"""
        SELECT r.*
          FROM {from_clause}
         WHERE {where}
         ORDER BY {order}
         LIMIT ? OFFSET ?
    """
    bindings.extend([params.limit, params.offset])

    cursor = await db.execute(sql, bindings)
    rows = await cursor.fetchall()

    ids = [row["id"] for row in rows]
    cats_map = await _fetch_categories_batch(db, ids)
    return [_recipe_dict(row, categories=cats_map.get(row["id"], [])) for row in rows]


async def get_recipe_by_url(db: aiosqlite.Connection, url: str) -> dict | None:
    """Find a recipe by its source_url.  Returns dict or None."""
    cursor = await db.execute(
        "SELECT * FROM recipes WHERE source_url = ?", (url,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    categories = await _fetch_categories(db, row["id"])
    return _recipe_dict(row, categories=categories)


# ---------------------------------------------------------------------------
# CRUD — Categories
# ---------------------------------------------------------------------------

async def list_categories(db: aiosqlite.Connection) -> list[dict]:
    """All categories with recipe counts."""
    cursor = await db.execute(
        """
        SELECT c.id, c.name, COUNT(rc.recipe_id) AS recipe_count
          FROM categories c
          LEFT JOIN recipe_categories rc ON rc.category_id = c.id
         GROUP BY c.id, c.name
         ORDER BY c.name
        """
    )
    return await cursor.fetchall()


async def create_category(db: aiosqlite.Connection, name: str) -> dict:
    """Create a category (INSERT OR IGNORE).  Returns the category dict."""
    await db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
    await db.commit()
    cursor = await db.execute("SELECT id, name FROM categories WHERE name = ?", (name,))
    row = await cursor.fetchone()
    return {**row, "recipe_count": 0}


async def delete_category(db: aiosqlite.Connection, category_id: int) -> bool:
    """Delete a category and unlink recipes (junction rows cascade).

    Does NOT delete the recipes themselves.  Returns True if a row was deleted.
    """
    cursor = await db.execute(
        "DELETE FROM categories WHERE id = ?", (category_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# CRUD — Meal Plans
# ---------------------------------------------------------------------------

async def create_meal_plan(db: aiosqlite.Connection, name: str) -> dict:
    async with _write_lock:
        cursor = await db.execute(
            "INSERT INTO meal_plans (name) VALUES (?)", (name,)
        )
        await db.commit()
    plan_id = cursor.lastrowid
    return await get_meal_plan(db, plan_id)


async def get_meal_plan(db: aiosqlite.Connection, plan_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM meal_plans WHERE id = ?", (plan_id,))
    plan = await cursor.fetchone()
    if plan is None:
        return None

    cursor = await db.execute(
        """
        SELECT e.*, r.title as recipe_title, r.image_url as recipe_image_url
          FROM meal_plan_entries e
          JOIN recipes r ON r.id = e.recipe_id
         WHERE e.meal_plan_id = ?
         ORDER BY e.date, e.meal_slot
        """,
        (plan_id,),
    )
    entries = await cursor.fetchall()
    return {**plan, "entries": entries}


async def list_meal_plans(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT mp.*, COUNT(e.id) as entry_count
          FROM meal_plans mp
          LEFT JOIN meal_plan_entries e ON e.meal_plan_id = mp.id
         GROUP BY mp.id
         ORDER BY mp.created_at DESC
        """
    )
    return await cursor.fetchall()


async def update_meal_plan(db: aiosqlite.Connection, plan_id: int, name: str) -> dict | None:
    async with _write_lock:
        cursor = await db.execute(
            "UPDATE meal_plans SET name = ? WHERE id = ?", (name, plan_id)
        )
        await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_meal_plan(db, plan_id)


async def delete_meal_plan(db: aiosqlite.Connection, plan_id: int) -> bool:
    async with _write_lock:
        cursor = await db.execute("DELETE FROM meal_plans WHERE id = ?", (plan_id,))
        await db.commit()
    return cursor.rowcount > 0


async def add_meal_plan_entry(
    db: aiosqlite.Connection,
    plan_id: int,
    recipe_id: int,
    date: str,
    meal_slot: str,
    servings_override: int | None = None,
) -> dict:
    async with _write_lock:
        cursor = await db.execute(
            """
            INSERT INTO meal_plan_entries (meal_plan_id, recipe_id, date, meal_slot, servings_override)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plan_id, recipe_id, date, meal_slot, servings_override),
        )
        await db.commit()
    entry_id = cursor.lastrowid
    cursor = await db.execute(
        """
        SELECT e.*, r.title as recipe_title, r.image_url as recipe_image_url
          FROM meal_plan_entries e
          JOIN recipes r ON r.id = e.recipe_id
         WHERE e.id = ?
        """,
        (entry_id,),
    )
    return await cursor.fetchone()


async def get_meal_plan_week(
    db: aiosqlite.Connection,
    plan_id: int,
    week_start: str,
    week_end: str,
) -> dict | None:
    """Get a meal plan with entries filtered to a date range (inclusive)."""
    cursor = await db.execute("SELECT * FROM meal_plans WHERE id = ?", (plan_id,))
    plan = await cursor.fetchone()
    if plan is None:
        return None

    cursor = await db.execute(
        """
        SELECT e.*, r.title as recipe_title, r.image_url as recipe_image_url
          FROM meal_plan_entries e
          JOIN recipes r ON r.id = e.recipe_id
         WHERE e.meal_plan_id = ?
           AND e.date BETWEEN ? AND ?
         ORDER BY e.date, e.meal_slot
        """,
        (plan_id, week_start, week_end),
    )
    entries = await cursor.fetchall()
    return {**plan, "entries": entries}


async def list_recipe_titles(db: aiosqlite.Connection) -> list[dict]:
    """Lightweight recipe list returning only id and title for pickers."""
    cursor = await db.execute("SELECT id, title FROM recipes ORDER BY title")
    return await cursor.fetchall()


async def remove_meal_plan_entry(db: aiosqlite.Connection, entry_id: int) -> bool:
    async with _write_lock:
        cursor = await db.execute("DELETE FROM meal_plan_entries WHERE id = ?", (entry_id,))
        await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# CRUD — Grocery Lists
# ---------------------------------------------------------------------------

def _aggregate_ingredients(
    raw_ingredients: list[tuple[str, int, int | None, int | None]],
) -> list[dict]:
    """Parse, normalize, classify, and aggregate ingredients.

    Each input tuple: (ingredient_text, recipe_id, servings_override, base_servings).
    Pure CPU-bound function — no DB, no async.  Testable in isolation.

    Returns list of dicts with keys: text, aisle, sort_order, recipe_id, normalized_name.
    """
    from fractions import Fraction as _Fraction
    from recipe_app.ingredient_parser import parse_ingredient
    from recipe_app.normalizer import normalize_ingredient_name
    from recipe_app.aisle_map import assign_aisle
    from recipe_app.scaling import format_quantity

    # aggregation_key -> {qty: Fraction|None, unit: str|None, name: str, texts: [str], recipe_ids: set}
    buckets: dict[tuple[str, str | None], dict] = {}
    result_order: list[tuple[str, str | None]] = []  # preserve insertion order

    for ing_text, recipe_id, servings_override, base_servings in raw_ingredients:
        try:
            parsed = parse_ingredient(ing_text, preserve_fractions=True)
        except Exception:
            parsed = {
                "name": None, "quantity": None, "unit": None,
                "original_text": ing_text, "scalable": False,
            }

        raw_name = parsed.get("name") or parsed.get("original_text") or ing_text
        norm = normalize_ingredient_name(raw_name)
        aisle_name, aisle_order = assign_aisle(norm.name)

        qty = parsed.get("quantity")
        unit = parsed.get("unit")

        # Apply servings scaling if override differs from base
        if (
            qty is not None
            and isinstance(qty, _Fraction)
            and servings_override is not None
            and base_servings is not None
            and base_servings > 0
        ):
            qty = qty * _Fraction(servings_override, base_servings)

        # Aggregation key: (normalized_name, unit_if_quantified)
        # Items with no quantity never merge with quantified items
        if qty is None or not parsed.get("scalable"):
            agg_key = (norm.name, None)
        else:
            agg_key = (norm.name, unit)

        if agg_key in buckets:
            bucket = buckets[agg_key]
            # Sum quantities if both have numeric qty
            if qty is not None and isinstance(qty, _Fraction) and bucket["qty"] is not None:
                bucket["qty"] += qty
            bucket["texts"].append(ing_text)
            bucket["recipe_ids"].add(recipe_id)
        else:
            buckets[agg_key] = {
                "qty": qty if isinstance(qty, _Fraction) else None,
                "unit": unit,
                "normalized_name": norm.name,
                "original_name": raw_name,
                "aisle": aisle_name,
                "aisle_order": aisle_order,
                "texts": [ing_text],
                "recipe_ids": {recipe_id},
            }
            result_order.append(agg_key)

    # Build output sorted by aisle order, then name
    items = []
    sorted_keys = sorted(result_order, key=lambda k: (buckets[k]["aisle_order"], buckets[k]["normalized_name"]))
    for i, key in enumerate(sorted_keys):
        b = buckets[key]
        # Format the display text
        if b["qty"] is not None:
            formatted_qty = format_quantity(b["qty"])
            parts = [formatted_qty]
            if b["unit"]:
                parts.append(b["unit"])
            parts.append(b["original_name"])
            display_text = " ".join(parts)
        else:
            display_text = b["texts"][0]  # use original text for unquantified

        items.append({
            "text": display_text,
            "aisle": b["aisle"],
            "sort_order": i,
            "recipe_id": next(iter(b["recipe_ids"])),  # first recipe
            "normalized_name": b["normalized_name"],
        })

    return items


async def generate_grocery_list(
    db: aiosqlite.Connection,
    name: str | None = None,
    meal_plan_id: int | None = None,
    recipe_ids: list[int] | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> dict:
    """Generate a grocery list from a meal plan or list of recipe IDs.

    Parses ingredients, normalizes, assigns aisles, and aggregates
    using Fraction arithmetic.  CPU-bound work runs via asyncio.to_thread().
    """
    # 1. Fetch ingredient data (async, on event loop)
    raw_ingredients: list[tuple[str, int, int | None, int | None]] = []

    if meal_plan_id:
        # Use JOIN to preserve duplicates (same recipe on multiple days)
        date_filter = ""
        params: list = [meal_plan_id]
        if date_start and date_end:
            date_filter = " AND e.date BETWEEN ? AND ?"
            params.extend([date_start, date_end])

        cursor = await db.execute(
            f"""
            SELECT r.id as recipe_id, r.ingredients, r.base_servings,
                   e.servings_override
              FROM meal_plan_entries e
              JOIN recipes r ON r.id = e.recipe_id
             WHERE e.meal_plan_id = ?{date_filter}
            """,
            params,
        )
        rows = await cursor.fetchall()
        for row in rows:
            if row["ingredients"]:
                ingredients_list = json.loads(row["ingredients"])
                for ing in ingredients_list:
                    raw_ingredients.append((
                        ing,
                        row["recipe_id"],
                        row["servings_override"],
                        row["base_servings"],
                    ))
    elif recipe_ids:
        for rid in recipe_ids:
            cursor = await db.execute(
                "SELECT id, ingredients, base_servings FROM recipes WHERE id = ?",
                (rid,),
            )
            row = await cursor.fetchone()
            if row and row["ingredients"]:
                ingredients_list = json.loads(row["ingredients"])
                for ing in ingredients_list:
                    raw_ingredients.append((ing, row["id"], None, row["base_servings"]))

    # 2. CPU-bound aggregation (off event loop)
    aggregated = await asyncio.to_thread(_aggregate_ingredients, raw_ingredients)

    # 3. DB writes (async, inside write lock + explicit transaction)
    list_name = sanitize_field(name) if name else "Shopping List"

    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "INSERT INTO grocery_lists (name, meal_plan_id) VALUES (?, ?)",
                (list_name, meal_plan_id),
            )
            list_id = cursor.lastrowid
            for item in aggregated:
                await db.execute(
                    """INSERT INTO grocery_list_items
                       (grocery_list_id, text, sort_order, aisle, recipe_id, normalized_name)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        list_id,
                        sanitize_field(item["text"]),
                        item["sort_order"],
                        sanitize_field(item["aisle"]),
                        item["recipe_id"],
                        sanitize_field(item["normalized_name"]) if item["normalized_name"] else None,
                    ),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return await get_grocery_list(db, list_id)


async def get_grocery_list(db: aiosqlite.Connection, list_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM grocery_lists WHERE id = ?", (list_id,))
    glist = await cursor.fetchone()
    if glist is None:
        return None
    cursor = await db.execute(
        """SELECT gli.*, r.title as recipe_title
             FROM grocery_list_items gli
             LEFT JOIN recipes r ON r.id = gli.recipe_id
            WHERE gli.grocery_list_id = ?
            ORDER BY gli.is_checked, gli.sort_order""",
        (list_id,),
    )
    items = await cursor.fetchall()
    return {**glist, "items": items}


async def list_grocery_lists(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT gl.*, COUNT(gli.id) as item_count,
               SUM(CASE WHEN gli.is_checked = 1 THEN 1 ELSE 0 END) as checked_count
          FROM grocery_lists gl
          LEFT JOIN grocery_list_items gli ON gli.grocery_list_id = gl.id
         GROUP BY gl.id
         ORDER BY gl.created_at DESC
        """
    )
    return await cursor.fetchall()


async def delete_grocery_list(db: aiosqlite.Connection, list_id: int) -> bool:
    async with _write_lock:
        cursor = await db.execute("DELETE FROM grocery_lists WHERE id = ?", (list_id,))
        await db.commit()
    return cursor.rowcount > 0


async def check_grocery_item(db: aiosqlite.Connection, item_id: int, is_checked: bool) -> dict | None:
    async with _write_lock:
        await db.execute(
            "UPDATE grocery_list_items SET is_checked = ? WHERE id = ?",
            (int(is_checked), item_id),
        )
        await db.commit()
    cursor = await db.execute("SELECT * FROM grocery_list_items WHERE id = ?", (item_id,))
    return await cursor.fetchone()


async def add_grocery_item(db: aiosqlite.Connection, list_id: int, text: str) -> dict:
    text = sanitize_field(text)
    async with _write_lock:
        # Get max sort_order inside lock to prevent race condition
        cursor = await db.execute(
            "SELECT MAX(sort_order) as max_order FROM grocery_list_items WHERE grocery_list_id = ?",
            (list_id,),
        )
        row = await cursor.fetchone()
        next_order = (row["max_order"] or 0) + 1

        cursor = await db.execute(
            "INSERT INTO grocery_list_items (grocery_list_id, text, sort_order) VALUES (?, ?, ?)",
            (list_id, text, next_order),
        )
        await db.commit()
    item_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM grocery_list_items WHERE id = ?", (item_id,))
    return await cursor.fetchone()


async def add_recipe_to_grocery_list(
    db: aiosqlite.Connection,
    recipe_id: int,
    list_name: str | None = None,
) -> dict:
    """Create a new grocery list from a single recipe's ingredients.

    Normalizes and assigns aisles. Returns the new grocery list.
    """
    recipe = await get_recipe(db, recipe_id)
    if recipe is None:
        raise ValueError(f"Recipe {recipe_id} not found")

    ingredients = recipe.get("ingredients", [])
    name = list_name or recipe["title"]

    raw_ingredients = [
        (ing, recipe_id, None, recipe.get("base_servings"))
        for ing in ingredients
    ]

    aggregated = await asyncio.to_thread(_aggregate_ingredients, raw_ingredients)

    async with _write_lock:
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "INSERT INTO grocery_lists (name) VALUES (?)",
                (sanitize_field(name),),
            )
            list_id = cursor.lastrowid
            for item in aggregated:
                await db.execute(
                    """INSERT INTO grocery_list_items
                       (grocery_list_id, text, sort_order, aisle, recipe_id, normalized_name)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        list_id,
                        sanitize_field(item["text"]),
                        item["sort_order"],
                        sanitize_field(item["aisle"]),
                        item["recipe_id"],
                        sanitize_field(item["normalized_name"]) if item["normalized_name"] else None,
                    ),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return await get_grocery_list(db, list_id)


# ---------------------------------------------------------------------------
# CRUD — Pantry
# ---------------------------------------------------------------------------

async def add_pantry_item(
    db: aiosqlite.Connection,
    name: str,
    category: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    expiration_date: str | None = None,
) -> dict:
    async with _write_lock:
        cursor = await db.execute(
            """
            INSERT INTO pantry_items (name, category, quantity, unit, expiration_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, category, quantity, unit, expiration_date),
        )
        await db.commit()
    item_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM pantry_items WHERE id = ?", (item_id,))
    return await cursor.fetchone()


_PANTRY_COLUMNS = {"name", "category", "quantity", "unit", "expiration_date"}


async def update_pantry_item(db: aiosqlite.Connection, item_id: int, **kwargs) -> dict | None:
    fields = {k: v for k, v in kwargs.items() if v is not None and k in _PANTRY_COLUMNS}
    if not fields:
        cursor = await db.execute("SELECT * FROM pantry_items WHERE id = ?", (item_id,))
        return await cursor.fetchone()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]

    async with _write_lock:
        cursor = await db.execute(
            f"UPDATE pantry_items SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
    if cursor.rowcount == 0:
        return None
    cursor = await db.execute("SELECT * FROM pantry_items WHERE id = ?", (item_id,))
    return await cursor.fetchone()


async def delete_pantry_item(db: aiosqlite.Connection, item_id: int) -> bool:
    async with _write_lock:
        cursor = await db.execute("DELETE FROM pantry_items WHERE id = ?", (item_id,))
        await db.commit()
    return cursor.rowcount > 0


async def list_pantry_items(
    db: aiosqlite.Connection, expiring_within_days: int | None = None
) -> list[dict]:
    if expiring_within_days is not None:
        cursor = await db.execute(
            """
            SELECT * FROM pantry_items
             WHERE expiration_date IS NOT NULL
               AND date(expiration_date) <= date('now', '+' || ? || ' days')
             ORDER BY expiration_date ASC
            """,
            (expiring_within_days,),
        )
    else:
        cursor = await db.execute("SELECT * FROM pantry_items ORDER BY name")
    return await cursor.fetchall()
