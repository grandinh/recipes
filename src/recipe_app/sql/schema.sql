PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    ingredients TEXT CHECK(ingredients IS NULL OR json_valid(ingredients)),
    directions TEXT,
    notes TEXT,
    source_url TEXT UNIQUE,
    image_url TEXT,
    prep_time_minutes INTEGER,
    cook_time_minutes INTEGER,
    total_time_minutes INTEGER GENERATED ALWAYS AS (
        CASE WHEN prep_time_minutes IS NULL AND cook_time_minutes IS NULL THEN NULL
             ELSE COALESCE(prep_time_minutes, 0) + COALESCE(cook_time_minutes, 0)
        END
    ) STORED,
    servings TEXT,
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    difficulty TEXT CHECK(difficulty IN ('easy', 'medium', 'hard')),
    cuisine TEXT,
    nutritional_info TEXT CHECK(nutritional_info IS NULL OR json_valid(nutritional_info)),
    is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS recipes_update_timestamp
AFTER UPDATE ON recipes FOR EACH ROW BEGIN
    UPDATE recipes SET updated_at = datetime('now') WHERE id = old.id;
END;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS recipe_categories (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, category_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    title,
    description,
    ingredients,
    directions,
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating);
CREATE INDEX IF NOT EXISTS idx_recipes_created ON recipes(created_at);
CREATE INDEX IF NOT EXISTS idx_recipes_favorite ON recipes(is_favorite);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_recipe ON recipe_categories(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_category ON recipe_categories(category_id);
