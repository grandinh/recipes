"""Aisle keyword map for grocery list grouping.

Pure-function module (no DB access), matching the ``scaling.py`` pattern.
15 categories with ~8-10 keywords each.  "Other" catches everything else.
Keywords sorted by descending length at module load so longest-match-first
prevents "coconut milk" from matching Dairy before Canned.
"""

from __future__ import annotations

# (aisle_name, sort_order) -> list of keywords
_AISLE_DATA: dict[tuple[str, int], list[str]] = {
    ("Produce", 1): [
        "lettuce", "tomato", "onion", "apple", "banana", "carrot", "potato",
        "celery", "garlic", "spinach", "avocado", "pepper", "zucchini",
        "broccoli", "mushroom", "cucumber", "corn", "lemon", "lime",
        "ginger", "shallot", "kale", "cabbage", "beet", "squash",
        "sweet potato", "green onion", "scallion", "radish", "pear",
    ],
    ("Fresh Herbs", 2): [
        "basil", "cilantro", "parsley", "thyme", "rosemary", "dill",
        "mint", "chive", "sage", "tarragon", "oregano fresh",
    ],
    ("Bread & Bakery", 3): [
        "bread", "tortilla", "pita", "baguette", "roll", "bun",
        "croissant", "naan", "flatbread",
    ],
    ("Dairy & Eggs", 5): [
        "milk", "cheese", "butter", "yogurt", "cream", "egg",
        "sour cream", "cream cheese", "half and half", "whipped cream",
        "mozzarella", "parmesan", "cheddar", "ricotta", "feta",
    ],
    ("Meat & Seafood", 6): [
        "chicken", "beef", "pork", "salmon", "shrimp", "turkey",
        "lamb", "bacon", "sausage", "ground beef", "ground turkey",
        "steak", "fish", "tuna", "tilapia", "cod", "crab",
    ],
    ("Canned & Jarred", 7): [
        "canned", "coconut milk", "tomato paste", "broth", "stock",
        "beans", "tomato sauce", "diced tomato", "crushed tomato",
        "chickpea", "coconut cream", "artichoke", "olive",
    ],
    ("Pasta, Rice & Grains", 8): [
        "pasta", "spaghetti", "rice", "quinoa", "noodle", "couscous",
        "oat", "farro", "barley", "penne", "linguine", "macaroni",
        "orzo", "risotto",
    ],
    ("Baking", 9): [
        "flour", "sugar", "baking powder", "baking soda", "vanilla",
        "cocoa", "chocolate chip", "yeast", "cornstarch", "powdered sugar",
        "brown sugar", "honey", "maple syrup", "molasses",
    ],
    ("Condiments & Sauces", 10): [
        "soy sauce", "mustard", "ketchup", "vinegar", "hot sauce",
        "mayo", "mayonnaise", "worcestershire", "salsa",
        "barbecue sauce", "teriyaki", "pesto",
    ],
    ("Spices & Seasonings", 11): [
        "cumin", "paprika", "cinnamon", "chili powder", "turmeric",
        "nutmeg", "cayenne", "black pepper", "red pepper flake",
        "garlic powder", "onion powder", "italian seasoning", "bay leaf",
        "clove", "coriander", "cardamom", "allspice",
    ],
    ("Oils & Vinegars", 12): [
        "olive oil", "vegetable oil", "sesame oil", "coconut oil",
        "canola oil", "cooking spray", "balsamic",
    ],
    ("Frozen", 13): [
        "frozen", "ice cream",
    ],
    ("Snacks & Beverages", 14): [
        "wine", "beer", "juice", "coffee", "tea", "nut",
        "almond", "walnut", "pecan", "cashew", "peanut",
    ],
    ("Deli", 15): [
        "deli", "rotisserie", "prepared salad", "cold cuts",
        "sliced turkey", "sliced ham", "sliced salami", "prosciutto",
        "pepperoni", "mortadella",
    ],
    ("International/Ethnic", 16): [
        "curry paste", "fish sauce", "miso", "rice paper", "sriracha",
        "hoisin", "gochujang", "harissa", "sambal",
        "rice vinegar", "mirin", "dashi", "nori", "wonton",
        "dumpling wrapper", "tofu", "tempeh",
    ],
}

# Set of valid aisle names for input validation
VALID_AISLES: frozenset[str] = frozenset(
    aisle for aisle, _ in _AISLE_DATA
) | {"Other"}

# Build a flat lookup sorted by descending keyword length (longest match first)
_KEYWORD_LOOKUP: list[tuple[str, str, int]] = []  # (keyword, aisle_name, sort_order)
for (aisle_name, sort_order), keywords in _AISLE_DATA.items():
    for kw in keywords:
        _KEYWORD_LOOKUP.append((kw, aisle_name, sort_order))
_KEYWORD_LOOKUP.sort(key=lambda x: len(x[0]), reverse=True)


def assign_aisle(normalized_name: str) -> tuple[str, int]:
    """Return (aisle_name, sort_order) for a normalized ingredient name.

    Uses substring matching with longest-match-first priority.
    Falls back to ("Other", 99).
    """
    lower = normalized_name.lower()
    for keyword, aisle_name, sort_order in _KEYWORD_LOOKUP:
        if keyword in lower:
            return (aisle_name, sort_order)
    return ("Other", 99)
