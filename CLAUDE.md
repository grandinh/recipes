# Recipe App

Personal recipe manager built as a Paprika 3 replacement with both a web UI and MCP agent access.

## Stack

- **Python 3.12+** with FastAPI + aiosqlite (async SQLite)
- **HTMX** frontend with Jinja2 templates (jinja2-fragments for partial rendering)
- **MCP server** (fastmcp) for Claude/agent integration
- **Pydantic** models for validation, pydantic-settings for config
- **bleach** for HTML sanitization

## Project Structure

```
src/recipe_app/
  main.py          # FastAPI app, web UI routes, middleware
  db.py            # All database operations (aiosqlite)
  models.py        # Pydantic models (Recipe, MealPlan, etc.)
  config.py        # Settings via pydantic-settings
  mcp_server.py    # MCP tool definitions
  aggregation.py   # Nutrition/ingredient aggregation
  aisle_map.py     # Grocery aisle mapping for shopping lists
  calendar_models.py  # Calendar/meal plan date models
  ingredient_parser.py  # NLP-based ingredient parsing
  normalizer.py    # Ingredient name normalization
  paprika_import.py    # Paprika 3 recipe import
  pantry_matcher.py     # "What can I make?" logic
  photos.py        # Recipe photo storage and serving
  sanitize.py      # Input sanitization
  scaling.py       # Ingredient scaling
  scraper.py       # Recipe URL scraping
  routers/         # API routers (recipes, categories, search, meal_plans, pantry)
  templates/       # Jinja2 HTML templates
  sql/schema.sql   # SQLite schema
static/            # JS (htmx) and CSS
data/              # SQLite DB + photos (gitignored)
tests/             # pytest + pytest-asyncio
```

## Access & Environment

- Web UI: bound to `127.0.0.1:8420` via systemd drop-in (`/etc/systemd/system/recipe-server.service.d/10-hub-bind-loopback.conf`). External access via Tailscale Serve at the path published by `grandin publish recipes 8420` — not raw 0.0.0.0.
- MCP server (`recipe-mcp`) is wired into **Hermes** as `chef`, via wrapper at `/root/.local/bin/chef-mcp` → `uv --directory /root/recipes run recipe-mcp`. Registered in `~/.hermes/config.yaml` under `mcp_servers.chef`. NOT wired into Claude Code sessions (no entry in `~/.claude.json`).
- SQLite DB at `data/recipes.db` (gitignored). **Journal mode: WAL** — required so the FastAPI server (recipe-server) and chef MCP can both write without SQLITE_BUSY. WAL is sticky in the file header; if the db file is rebuilt from scratch, re-run `sqlite3 data/recipes.db "PRAGMA journal_mode=WAL"`.

## Commands

```bash
# Run the web server
uv run recipe-server

# Run tests
uv run pytest

# Run a single test file
uv run pytest tests/test_recipes_crud.py -v

# Run MCP server
uv run recipe-mcp
```

## Key Patterns

- **DB access**: All DB functions are in `db.py`, called with `get_db(request)` in routes
- **Write serialization**: SQLite writes go through a serialized queue to avoid SQLITE_BUSY
- **HTMX partials**: Routes check `hx-request` header and return block fragments via `block_name=`
- **Sanitization**: Free-text inputs (recipe title, description, ingredients, etc.) are sanitized via `sanitize_field()` in the DB layer before writing. **Controlled-vocabulary fields** (currently `aisle`, sourced from `aisle_map.VALID_AISLES`) are validated against an allowlist instead — sanitizing an enum-shaped value would HTML-escape legitimate content (e.g. `"Dairy & Eggs"` → `"Dairy &amp; Eggs"`). Field's owning module decides which pattern applies; do not add `sanitize_field()` to allowlist-validated fields "for consistency."
- **Column allowlists**: Dynamic queries use allowlists for sortable/filterable columns
- **Tests**: Use pytest-asyncio with `asyncio_mode = "auto"`, test client via httpx
