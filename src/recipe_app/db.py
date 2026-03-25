"""Database module — SQLite via aiosqlite with FTS5 full-text search."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import Request

from recipe_app.config import settings
from recipe_app.models import RecipeCreate, RecipeUpdate, SearchParams
from recipe_app.scraper import sanitize_fts5_query  # noqa: F401 — used in search_recipes

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


@asynccontextmanager
async def lifespan(app: Any):
    """FastAPI lifespan — open/close the database connection."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = _row_to_dict
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 5000")
    await init_schema(db)
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
    return db


# ---------------------------------------------------------------------------
# CRUD — Recipes
# ---------------------------------------------------------------------------

async def create_recipe(db: aiosqlite.Connection, data: RecipeCreate) -> dict:
    """Insert a new recipe with FTS5 and category rows.  Returns full dict."""
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

    Returns True if a row was deleted.
    """
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _fts_delete(db, recipe_id)
        cursor = await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return cursor.rowcount > 0


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
