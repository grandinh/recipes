"""Paprika 3 recipe archive import (.paprikarecipes)."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field

import aiosqlite

from recipe_app.db import create_recipe
from recipe_app.models import RecipeCreate
from recipe_app.photos import save_photo, delete_photo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

MAX_IMPORT_SIZE = 50 * 1024 * 1024        # 50 MB upload limit
MAX_ENTRY_SIZE = 50 * 1024 * 1024          # 50 MB per decompressed entry
MAX_RECIPES_PER_IMPORT = 2000              # entry count cap
MAX_PHOTO_BASE64_SIZE = 20 * 1024 * 1024   # ~15 MB decoded


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ImportedRecipe:
    id: int
    title: str

@dataclass
class SkippedRecipe:
    title: str
    reason: str

@dataclass
class ErroredRecipe:
    title: str
    error: str

@dataclass
class ImportResult:
    imported: list[ImportedRecipe] = field(default_factory=list)
    skipped: list[SkippedRecipe] = field(default_factory=list)
    errors: list[ErroredRecipe] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Archive parsing
# ---------------------------------------------------------------------------

def _safe_gzip_decompress(data: bytes, max_size: int = MAX_ENTRY_SIZE) -> bytes:
    """Decompress gzip data with a size limit to prevent decompression bombs."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        while True:
            chunk = gz.read(8192)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > max_size:
                raise ValueError(f"Decompressed size exceeds limit of {max_size} bytes")
    return buf.getvalue()


def parse_paprika_archive(file_bytes: bytes) -> list[dict]:
    """Parse a .paprikarecipes ZIP archive into a list of recipe dicts.

    Each entry in the ZIP is an individually gzipped JSON file.
    Runs in a thread via asyncio.to_thread (CPU-bound).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ZIP file: {exc}") from exc

    recipes = []
    with zf:
        entries = zf.infolist()
        if len(entries) > MAX_RECIPES_PER_IMPORT:
            raise ValueError(
                f"Archive contains {len(entries)} entries, maximum is {MAX_RECIPES_PER_IMPORT}"
            )

        for info in entries:
            # Skip directories
            if info.is_dir():
                continue

            # Path traversal guard
            if ".." in info.filename or info.filename.startswith("/"):
                logger.warning("Skipping suspicious ZIP entry: %s", info.filename)
                continue

            # Size guard
            if info.file_size > MAX_ENTRY_SIZE:
                logger.warning("Skipping oversized entry: %s (%d bytes)", info.filename, info.file_size)
                continue

            try:
                raw = zf.read(info)
                decompressed = _safe_gzip_decompress(raw)
                recipe_dict = json.loads(decompressed.decode("utf-8", errors="replace"))
                recipes.append(recipe_dict)
            except (gzip.BadGzipFile, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping malformed entry %s: %s", info.filename, exc)
                continue

    return recipes


# ---------------------------------------------------------------------------
# Time string parsing
# ---------------------------------------------------------------------------

def parse_time_string(s: str | None) -> int | None:
    """Parse Paprika time strings into minutes.

    Handles: "15 min", "1 hour", "1 hr 30 min", "1:30", "90", ""
    Returns None for empty or unparseable strings.
    """
    if not s or not s.strip():
        return None

    s = s.strip().lower()

    # Try "H:MM" format
    m = re.match(r"^(\d+):(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    # Try bare integer (already minutes)
    if s.isdigit():
        return int(s)

    # Try natural language: "1 hour 30 minutes", "15 min", "1 hr 30 min", etc.
    total = 0
    found = False

    # Hours
    m = re.search(r"(\d+)\s*(?:hours?|hrs?|h)\b", s)
    if m:
        total += int(m.group(1)) * 60
        found = True

    # Minutes
    m = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", s)
    if m:
        total += int(m.group(1))
        found = True

    return total if found else None


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def map_paprika_recipe(paprika: dict) -> tuple[dict, bytes | None, list[str]]:
    """Map a Paprika recipe dict to RecipeCreate-compatible fields.

    Returns (recipe_fields, photo_bytes_or_None, warnings).
    """
    warnings = []
    title = paprika.get("name") or "Untitled Import"

    # Ingredients: newline-separated string -> list
    raw_ingredients = paprika.get("ingredients", "") or ""
    ingredients = [line.strip() for line in raw_ingredients.split("\n") if line.strip()] or None

    # Rating: 0 -> None (Pydantic rejects 0 with ge=1)
    raw_rating = paprika.get("rating")
    rating = None
    if raw_rating and isinstance(raw_rating, (int, float)) and 1 <= raw_rating <= 5:
        rating = int(raw_rating)

    # Time fields
    prep = parse_time_string(paprika.get("prep_time"))
    cook = parse_time_string(paprika.get("cook_time"))

    # Source URL: prefer source_url, fall back to source
    source_url = (paprika.get("source_url") or "").strip() or None
    if not source_url:
        source_field = (paprika.get("source") or "").strip()
        if source_field:
            source_url = source_field  # store as-is, even if not a URL

    # Categories
    categories = paprika.get("categories")
    if isinstance(categories, list):
        categories = [c.strip() for c in categories if isinstance(c, str) and c.strip()] or None
    else:
        categories = None

    # Photo data
    photo_bytes = None
    raw_photo = paprika.get("photo_data") or ""
    if raw_photo and len(raw_photo) <= MAX_PHOTO_BASE64_SIZE:
        try:
            photo_bytes = base64.b64decode(raw_photo, validate=True)
        except Exception as exc:
            warnings.append(f"Photo decode failed: {exc}")
    elif raw_photo and len(raw_photo) > MAX_PHOTO_BASE64_SIZE:
        warnings.append("Photo data exceeds size limit, skipped")

    fields = {
        "title": title,
        "description": (paprika.get("description") or "").strip() or None,
        "ingredients": ingredients,
        "directions": (paprika.get("directions") or "").strip() or None,
        "notes": (paprika.get("notes") or "").strip() or None,
        "source_url": source_url,
        "servings": (paprika.get("servings") or "").strip() or None,
        "prep_time_minutes": prep,
        "cook_time_minutes": cook,
        "rating": rating,
        "is_favorite": bool(paprika.get("on_favorites")),
        "categories": categories,
    }

    return fields, photo_bytes, warnings


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------

async def import_paprika_recipes(
    db: aiosqlite.Connection,
    paprika_recipes: list[dict],
) -> ImportResult:
    """Import mapped Paprika recipes into the database.

    Uses per-recipe error handling so a single failure doesn't stop the batch.
    Deduplicates within the batch by source_url.
    Catches IntegrityError for existing source_url duplicates.
    Cleans up orphan photo files on DB insert failure.
    """
    result = ImportResult()
    seen_urls: set[str] = set()

    for paprika_dict in paprika_recipes:
        title = paprika_dict.get("name") or "Untitled"
        try:
            fields, photo_bytes, warnings = map_paprika_recipe(paprika_dict)
            title = fields.get("title", title)

            # In-batch deduplication
            url = fields.get("source_url")
            if url and url in seen_urls:
                result.skipped.append(SkippedRecipe(title=title, reason="Duplicate within import batch"))
                continue
            if url:
                seen_urls.add(url)

            # Construct Pydantic model (validates rating, etc.)
            recipe_data = RecipeCreate(**fields)

            # Process photo before DB insert
            photo_filename = None
            if photo_bytes:
                try:
                    photo_filename = await save_photo(photo_bytes)
                    recipe_data.photo_path = photo_filename
                except Exception as exc:
                    warnings.append(f"Photo processing failed: {exc}")

            # Insert into DB
            try:
                created = await create_recipe(db, recipe_data)
                result.imported.append(ImportedRecipe(id=created["id"], title=title))
            except Exception as exc:
                # Clean up orphan photo
                if photo_filename:
                    try:
                        await delete_photo(photo_filename)
                    except Exception:
                        pass

                # Check if it's a duplicate (IntegrityError on source_url)
                exc_str = str(exc).lower()
                if "unique" in exc_str or "integrity" in exc_str:
                    result.skipped.append(SkippedRecipe(title=title, reason="Duplicate source_url"))
                else:
                    result.errors.append(ErroredRecipe(title=title, error=str(exc)))
                continue

            if warnings:
                logger.info("Import warnings for '%s': %s", title, "; ".join(warnings))

        except Exception as exc:
            result.errors.append(ErroredRecipe(title=title, error=str(exc)))
            continue

    return result
