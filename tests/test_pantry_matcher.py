"""Unit tests for pantry matching — sync, class-grouped."""

import json

from recipe_app.pantry_matcher import _matches_pantry, find_matching_recipes_sync


class TestMatchesPantry:
    def test_exact_match(self):
        assert _matches_pantry("flour", ["flour"]) is True

    def test_substring_match(self):
        assert _matches_pantry("boneless skinless chicken breast", ["chicken"]) is True

    def test_no_match(self):
        assert _matches_pantry("chicken", ["tofu"]) is False

    def test_case_insensitive(self):
        assert _matches_pantry("Flour", ["flour"]) is True
        assert _matches_pantry("flour", ["FLOUR".lower()]) is True

    def test_short_name(self):
        # Single character pantry item matches substrings broadly
        assert _matches_pantry("egg", ["e"]) is True

    def test_empty_pantry(self):
        assert _matches_pantry("flour", []) is False


class TestFindMatchingRecipesSync:
    def _make_recipe(self, id, title, ingredients):
        return {
            "id": id,
            "title": title,
            "image_url": None,
            "ingredients": ingredients,
        }

    def test_empty_pantry(self):
        recipes = [self._make_recipe(1, "Cake", ["flour", "sugar"])]
        assert find_matching_recipes_sync(recipes, []) == []

    def test_all_matched(self):
        recipes = [self._make_recipe(1, "Simple", ["flour", "eggs"])]
        pantry = [{"name": "flour"}, {"name": "eggs"}]
        results = find_matching_recipes_sync(recipes, pantry, max_missing=0)
        assert len(results) == 1
        assert results[0]["match_percentage"] == 100.0

    def test_partial_match(self):
        recipes = [self._make_recipe(1, "Cake", ["flour", "eggs", "sugar"])]
        pantry = [{"name": "flour"}, {"name": "eggs"}]
        results = find_matching_recipes_sync(recipes, pantry, max_missing=2)
        assert len(results) == 1
        assert results[0]["matched_count"] == 2

    def test_max_missing_filter(self):
        recipes = [self._make_recipe(1, "Cake", ["flour", "eggs", "sugar"])]
        pantry = [{"name": "flour"}]
        # 2 missing (eggs, sugar), max_missing=1 => excluded
        results = find_matching_recipes_sync(recipes, pantry, max_missing=1)
        assert len(results) == 0

    def test_sort_order(self):
        recipes = [
            self._make_recipe(1, "Low", ["flour", "eggs", "sugar", "butter"]),
            self._make_recipe(2, "High", ["flour", "eggs"]),
        ]
        pantry = [{"name": "flour"}, {"name": "eggs"}]
        results = find_matching_recipes_sync(recipes, pantry, max_missing=5)
        assert results[0]["title"] == "High"  # 100% match
        assert results[1]["title"] == "Low"  # 50% match

    def test_json_string_ingredients(self):
        recipe = {
            "id": 1,
            "title": "JSON",
            "image_url": None,
            "ingredients": json.dumps(["flour", "eggs"]),
        }
        pantry = [{"name": "flour"}, {"name": "eggs"}]
        results = find_matching_recipes_sync([recipe], pantry, max_missing=0)
        assert len(results) == 1

    def test_list_ingredients(self):
        recipe = self._make_recipe(1, "List", ["flour", "eggs"])
        pantry = [{"name": "flour"}, {"name": "eggs"}]
        results = find_matching_recipes_sync([recipe], pantry, max_missing=0)
        assert len(results) == 1

    def test_no_ingredients(self):
        recipe = self._make_recipe(1, "Empty", [])
        pantry = [{"name": "flour"}]
        results = find_matching_recipes_sync([recipe], pantry, max_missing=5)
        assert len(results) == 0
