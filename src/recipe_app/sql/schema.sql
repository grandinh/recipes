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
    base_servings INTEGER DEFAULT NULL,
    photo_path TEXT DEFAULT NULL,
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

-- v0.2: Meal plans
CREATE TABLE IF NOT EXISTS meal_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_meal_plans_updated
AFTER UPDATE ON meal_plans FOR EACH ROW BEGIN
    UPDATE meal_plans SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS meal_plan_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_plan_id INTEGER NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    meal_slot TEXT NOT NULL CHECK (meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack')),
    servings_override INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- v0.2: Grocery lists
CREATE TABLE IF NOT EXISTS grocery_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    meal_plan_id INTEGER REFERENCES meal_plans(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_grocery_lists_updated
AFTER UPDATE ON grocery_lists FOR EACH ROW BEGIN
    UPDATE grocery_lists SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS grocery_list_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grocery_list_id INTEGER NOT NULL REFERENCES grocery_lists(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    is_checked INTEGER NOT NULL DEFAULT 0 CHECK (is_checked IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    aisle TEXT DEFAULT 'Other',
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    normalized_name TEXT
);

-- v0.3: Pantry
CREATE TABLE IF NOT EXISTS pantry_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT,
    quantity REAL,
    unit TEXT,
    expiration_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_pantry_items_updated
AFTER UPDATE ON pantry_items FOR EACH ROW BEGIN
    UPDATE pantry_items SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating);
CREATE INDEX IF NOT EXISTS idx_recipes_created ON recipes(created_at);
CREATE INDEX IF NOT EXISTS idx_recipes_favorite ON recipes(is_favorite);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_recipe ON recipe_categories(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_categories_category ON recipe_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_plan ON meal_plan_entries(meal_plan_id);
CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_recipe ON meal_plan_entries(recipe_id);
CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_date ON meal_plan_entries(meal_plan_id, date);
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_list ON grocery_list_items(grocery_list_id);
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_recipe ON grocery_list_items(grocery_list_id, recipe_id);
CREATE INDEX IF NOT EXISTS idx_pantry_items_name ON pantry_items(name COLLATE NOCASE);

PRAGMA user_version = 3;
