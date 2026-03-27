"""Tests for aisle keyword mapping."""

import pytest

from recipe_app.aisle_map import assign_aisle


class TestAssignAisle:
    @pytest.mark.parametrize("ingredient,expected_aisle", [
        ("tomato", "Produce"),
        ("onion", "Produce"),
        ("garlic", "Produce"),
        ("basil", "Fresh Herbs"),
        ("cilantro", "Fresh Herbs"),
        ("milk", "Dairy & Eggs"),
        ("egg", "Dairy & Eggs"),
        ("butter", "Dairy & Eggs"),
        ("chicken", "Meat & Seafood"),
        ("salmon", "Meat & Seafood"),
        ("pasta", "Pasta, Rice & Grains"),
        ("rice", "Pasta, Rice & Grains"),
        ("flour", "Baking"),
        ("sugar", "Baking"),
        ("soy sauce", "Condiments & Sauces"),
        ("cumin", "Spices & Seasonings"),
        ("olive oil", "Oils & Vinegars"),
        ("broth", "Canned & Jarred"),
    ], ids=lambda x: x)
    def test_known_ingredients(self, ingredient, expected_aisle):
        aisle, order = assign_aisle(ingredient)
        assert aisle == expected_aisle

    def test_coconut_milk_canned_not_dairy(self):
        """coconut milk should match Canned (longest-match-first), not Dairy."""
        aisle, _ = assign_aisle("coconut milk")
        assert aisle == "Canned & Jarred"

    def test_unknown_ingredient_gets_other(self):
        aisle, order = assign_aisle("xanthan gum")
        assert aisle == "Other"
        assert order == 99

    def test_case_insensitive(self):
        aisle, _ = assign_aisle("CHICKEN")
        assert aisle == "Meat & Seafood"

    def test_returns_sort_order(self):
        _, order = assign_aisle("tomato")
        assert isinstance(order, int)
        assert order < 99  # not Other

    def test_sort_order_produce_before_dairy(self):
        _, produce_order = assign_aisle("tomato")
        _, dairy_order = assign_aisle("milk")
        assert produce_order < dairy_order
