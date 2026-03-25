#!/usr/bin/env python3
"""Import recipes from Paprika 3 export files (HTML, JSON, or .paprikarecipes).

Usage:
    # Directory of HTML files (Paprika's default export):
    python import_paprika.py /path/to/Export/Recipes/

    # Single .paprikarecipes archive:
    python import_paprika.py recipes.paprikarecipes

    # JSON files:
    python import_paprika.py recipe.json

    # Mix and match:
    python import_paprika.py exports/Recipes/ backup.paprikarecipes extra.json
"""

import asyncio
import gzip
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from recipe_app.config import settings
from recipe_app.db import connect, create_recipe
from recipe_app.models import RecipeCreate


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def parse_time(val) -> int | None:
    if not val:
        return None
    val = str(val).strip()
    if not val:
        return None

    # Pure digits
    if val.isdigit():
        return int(val) if int(val) > 0 else None

    # "8 mins", "15 minutes", "1 hour 30 mins", etc.
    total = 0
    hours = re.search(r"(\d+)\s*h(?:ou)?r", val, re.IGNORECASE)
    mins = re.search(r"(\d+)\s*min", val, re.IGNORECASE)
    if hours:
        total += int(hours.group(1)) * 60
    if mins:
        total += int(mins.group(1))
    return total if total > 0 else None


# ---------------------------------------------------------------------------
# HTML parser (Paprika's export format)
# ---------------------------------------------------------------------------

def parse_paprika_html(filepath: Path) -> dict:
    """Parse a Paprika HTML export file using its schema.org microdata."""
    with open(filepath, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    recipe_div = soup.find(itemtype=re.compile(r"schema\.org/Recipe"))
    if not recipe_div:
        recipe_div = soup  # fallback to whole doc

    # Title
    name_el = recipe_div.find(itemprop="name")
    title = name_el.get_text(strip=True) if name_el else filepath.stem

    # Image URL — from the <a> wrapping the photo, or the img src
    image_url = None
    photo_link = recipe_div.select_one(".photobox a")
    if photo_link and photo_link.get("href"):
        href = photo_link["href"]
        if href.startswith("http"):
            image_url = href

    # Rating
    rating_el = recipe_div.find(itemprop="aggregateRating")
    rating = None
    if rating_el:
        val = rating_el.get("value") or rating_el.get_text(strip=True)
        try:
            r = int(float(val))
            rating = r if 1 <= r <= 5 else None
        except (TypeError, ValueError):
            pass

    # Categories
    cat_el = recipe_div.find(itemprop="recipeCategory")
    categories = None
    if cat_el:
        cat_text = cat_el.get_text(strip=True)
        if cat_text:
            categories = [c.strip() for c in cat_text.split(",") if c.strip()]

    # Metadata row: prep time, cook time, servings, source
    metadata = recipe_div.find(class_="metadata")
    prep_time = None
    cook_time = None
    servings = None
    source_url = None

    if metadata:
        text = metadata.get_text()
        prep_match = re.search(r"Prep Time:\s*(.+?)(?=Cook|Servings|Source|$)", text)
        cook_match = re.search(r"Cook Time:\s*(.+?)(?=Prep|Servings|Source|$)", text)
        serv_match = re.search(r"Servings:\s*(.+?)(?=Prep|Cook|Source|$)", text)
        if prep_match:
            prep_time = parse_time(prep_match.group(1).strip())
        if cook_match:
            cook_time = parse_time(cook_match.group(1).strip())
        if serv_match:
            servings = serv_match.group(1).strip()

        source_link = metadata.find("a", itemprop="url")
        if source_link and source_link.get("href"):
            source_url = source_link["href"]

    # Description (author/source name)
    desc_el = metadata.find(itemprop="author") if metadata else None
    description = desc_el.get_text(strip=True) if desc_el else None

    # Ingredients
    ingredients_div = recipe_div.find(class_="ingredients")
    ingredients = []
    if ingredients_div:
        for p in ingredients_div.find_all("p", class_="line"):
            text = p.get_text(strip=True)
            if text:
                ingredients.append(text)

    # Directions
    directions_div = recipe_div.find(itemprop="recipeInstructions")
    directions = None
    if directions_div:
        steps = []
        for p in directions_div.find_all("p", class_="line"):
            text = p.get_text(strip=True)
            if text:
                steps.append(text)
        if steps:
            directions = "\n\n".join(steps)

    # Notes
    notes_div = recipe_div.find(itemprop="comment")
    notes = None
    if notes_div:
        notes_text = notes_div.get_text(strip=True)
        if notes_text:
            notes = notes_text

    # Nutrition
    nutrition_div = recipe_div.find(itemprop="nutrition")
    nutritional_info = None
    if nutrition_div:
        nut_text = nutrition_div.get_text(strip=True)
        if nut_text:
            nutritional_info = {"info": nut_text}

    return {
        "title": title or "Untitled Recipe",
        "description": description or None,
        "ingredients": ingredients or None,
        "directions": directions or None,
        "notes": notes or None,
        "source_url": source_url or None,
        "image_url": image_url,
        "prep_time_minutes": prep_time,
        "cook_time_minutes": cook_time,
        "servings": servings or None,
        "rating": rating,
        "cuisine": None,
        "nutritional_info": nutritional_info,
        "is_favorite": False,
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# JSON parser (Paprika JSON export)
# ---------------------------------------------------------------------------

def parse_paprika_json(data: dict) -> dict:
    """Convert a Paprika JSON recipe dict to our field names."""
    ingredients_raw = data.get("ingredients", "")
    if isinstance(ingredients_raw, str):
        ingredients = [l.strip() for l in ingredients_raw.split("\n") if l.strip()]
    elif isinstance(ingredients_raw, list):
        ingredients = ingredients_raw
    else:
        ingredients = []

    categories_raw = data.get("categories", "")
    if isinstance(categories_raw, str):
        categories = [c.strip() for c in categories_raw.split(",") if c.strip()]
    elif isinstance(categories_raw, list):
        categories = categories_raw
    else:
        categories = []

    rating_raw = data.get("rating", 0)
    try:
        rating = int(rating_raw)
        rating = rating if 1 <= rating <= 5 else None
    except (TypeError, ValueError):
        rating = None

    nutritional_info = None
    nut_raw = data.get("nutritional_info", "") or data.get("nutrition", "")
    if nut_raw:
        if isinstance(nut_raw, dict):
            nutritional_info = nut_raw
        elif isinstance(nut_raw, str) and nut_raw.strip():
            nutritional_info = {"info": nut_raw.strip()}

    return {
        "title": data.get("name", "") or data.get("title", "") or "Untitled Recipe",
        "description": data.get("description", "") or None,
        "ingredients": ingredients or None,
        "directions": data.get("directions", "") or data.get("instructions", "") or None,
        "notes": data.get("notes", "") or None,
        "source_url": data.get("source_url", "") or data.get("source", "") or None,
        "image_url": data.get("image_url", "") or data.get("photo_url", "") or None,
        "prep_time_minutes": parse_time(data.get("prep_time")),
        "cook_time_minutes": parse_time(data.get("cook_time")),
        "servings": data.get("servings", "") or data.get("yields", "") or None,
        "rating": rating,
        "cuisine": data.get("cuisine", "") or None,
        "nutritional_info": nutritional_info,
        "is_favorite": bool(data.get("is_favorite") or data.get("favorite")),
        "categories": categories or None,
    }


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------

def load_paprikarecipes(filepath: Path) -> list[dict]:
    """Extract from .paprikarecipes (zip of gzipped JSON blobs)."""
    recipes = []
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            for name in zf.namelist():
                with zf.open(name) as f:
                    raw = f.read()
                    try:
                        data = json.loads(gzip.decompress(raw))
                    except gzip.BadGzipFile:
                        data = json.loads(raw)
                    recipes.append(parse_paprika_json(data))
    except zipfile.BadZipFile:
        with gzip.open(filepath, "rb") as f:
            data = json.loads(f.read())
            if isinstance(data, list):
                recipes.extend(parse_paprika_json(d) for d in data)
            else:
                recipes.append(parse_paprika_json(data))
    return recipes


def load_json_file(filepath: Path) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    return [parse_paprika_json(d) for d in items]


# ---------------------------------------------------------------------------
# Main import
# ---------------------------------------------------------------------------

async def import_all(paths: list[Path]):
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    db = await connect()

    all_recipes: list[dict] = []

    for path in paths:
        if path.is_dir():
            # HTML files
            html_files = sorted(path.glob("*.html"))
            if html_files:
                print(f"Found {len(html_files)} HTML recipes in {path}/")
                for hf in html_files:
                    if hf.name == "index.html":
                        continue
                    try:
                        all_recipes.append(parse_paprika_html(hf))
                    except Exception as e:
                        print(f"  WARN: Could not parse {hf.name}: {e}")
            # JSON files
            json_files = sorted(path.glob("*.json"))
            if json_files:
                print(f"Found {len(json_files)} JSON recipes in {path}/")
                for jf in json_files:
                    all_recipes.extend(load_json_file(jf))
            # Recurse into subdirectories (e.g. Export/Recipes/)
            for subdir in sorted(path.iterdir()):
                if subdir.is_dir() and subdir.name != "Images":
                    sub_html = list(subdir.glob("*.html"))
                    if sub_html:
                        print(f"Found {len(sub_html)} HTML recipes in {subdir}/")
                        for hf in sub_html:
                            if hf.name == "index.html":
                                continue
                            try:
                                all_recipes.append(parse_paprika_html(hf))
                            except Exception as e:
                                print(f"  WARN: Could not parse {hf.name}: {e}")
        elif path.suffix == ".paprikarecipes":
            print(f"Loading {path.name}...")
            all_recipes.extend(load_paprikarecipes(path))
        elif path.suffix == ".json":
            all_recipes.extend(load_json_file(path))
        elif path.suffix == ".html" and path.name != "index.html":
            all_recipes.append(parse_paprika_html(path))
        else:
            print(f"  SKIP: {path}")

    print(f"\nParsed {len(all_recipes)} recipes. Importing...")

    imported = 0
    skipped = 0
    errors = 0

    for recipe_dict in all_recipes:
        title = recipe_dict.get("title", "Untitled")
        try:
            create_data = RecipeCreate(
                **{k: v for k, v in recipe_dict.items() if v is not None or k == "title"}
            )
            await create_recipe(db, create_data)
            imported += 1
            if imported % 50 == 0:
                print(f"  ...{imported} imported")
        except sqlite3.IntegrityError:
            skipped += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR importing '{title}': {e}")

    await db.close()
    print(f"\nDone! {imported} imported, {skipped} skipped (duplicate URLs), {errors} errors.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    paths = [Path(p) for p in sys.argv[1:]]
    for p in paths:
        if not p.exists():
            print(f"ERROR: {p} does not exist")
            sys.exit(1)

    asyncio.run(import_all(paths))


if __name__ == "__main__":
    main()
