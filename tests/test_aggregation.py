"""Tests for the grocery aggregation pipeline."""

from fractions import Fraction

import pytest

from recipe_app.aggregation import aggregate_ingredients as _aggregate_ingredients


class TestAggregateIngredients:
    def test_sums_same_ingredient(self):
        """2 eggs + 3 eggs = 5 eggs."""
        raw = [
            ("2 eggs", 1, None, None),
            ("3 eggs", 2, None, None),
        ]
        result = _aggregate_ingredients(raw)
        egg_items = [i for i in result if "egg" in i["text"].lower()]
        assert len(egg_items) == 1
        assert "5" in egg_items[0]["text"]

    def test_different_units_not_merged(self):
        """1 cup flour + 200g flour = two separate items."""
        raw = [
            ("1 cup flour", 1, None, None),
            ("200 g flour", 2, None, None),
        ]
        result = _aggregate_ingredients(raw)
        flour_items = [i for i in result if "flour" in i["normalized_name"]]
        assert len(flour_items) == 2

    def test_unquantified_not_merged(self):
        """salt to taste + 1 tsp salt = two items."""
        raw = [
            ("salt to taste", 1, None, None),
            ("1 tsp salt", 2, None, None),
        ]
        result = _aggregate_ingredients(raw)
        salt_items = [i for i in result if "salt" in i["normalized_name"]]
        assert len(salt_items) == 2

    def test_multiplicity_preserved(self):
        """Same recipe on 2 days = double quantities."""
        raw = [
            ("2 eggs", 1, None, None),
            ("2 eggs", 1, None, None),  # same recipe_id, different day
        ]
        result = _aggregate_ingredients(raw)
        egg_items = [i for i in result if "egg" in i["text"].lower()]
        assert len(egg_items) == 1
        assert "4" in egg_items[0]["text"]

    def test_aisle_assignment(self):
        raw = [("1 lb chicken breast", 1, None, None)]
        result = _aggregate_ingredients(raw)
        assert len(result) == 1
        assert result[0]["aisle"] == "Meat & Seafood"

    def test_sorted_by_aisle(self):
        raw = [
            ("1 lb chicken", 1, None, None),
            ("2 tomatoes", 2, None, None),
        ]
        result = _aggregate_ingredients(raw)
        # Produce (order 1) should come before Meat (order 6)
        aisles = [i["aisle"] for i in result]
        produce_idx = next(i for i, a in enumerate(aisles) if a == "Produce")
        meat_idx = next(i for i, a in enumerate(aisles) if a == "Meat & Seafood")
        assert produce_idx < meat_idx

    def test_empty_input(self):
        result = _aggregate_ingredients([])
        assert result == []

    def test_unparseable_ingredient(self):
        """Unparseable ingredients should fall through as raw text."""
        raw = [("", 1, None, None)]
        result = _aggregate_ingredients(raw)
        # Should not crash
        assert isinstance(result, list)

    def test_servings_override_scaling(self):
        """servings_override should scale quantities."""
        raw = [
            ("2 cups flour", 1, 8, 4),  # override=8, base=4 -> 2x
        ]
        result = _aggregate_ingredients(raw)
        flour_items = [i for i in result if "flour" in i["normalized_name"]]
        assert len(flour_items) == 1
        assert "4" in flour_items[0]["text"]

    def test_normalized_name_set(self):
        raw = [("2 Onions (diced)", 1, None, None)]
        result = _aggregate_ingredients(raw)
        assert result[0]["normalized_name"] == "onion"
