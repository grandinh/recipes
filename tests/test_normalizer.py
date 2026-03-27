"""Tests for ingredient name normalization."""

import pytest

from recipe_app.normalizer import NormalizedResult, normalize_ingredient_name, singularize


class TestSingularize:
    @pytest.mark.parametrize("word,expected", [
        ("tomatoes", "tomato"),
        ("onions", "onion"),
        ("eggs", "egg"),
        ("potatoes", "potato"),
        ("berries", "berry"),
        ("cherries", "cherry"),
        ("leaves", "leaf"),
        ("halves", "half"),
        ("dishes", "dish"),
        ("bunches", "bunch"),
    ], ids=lambda x: x)
    def test_regular_plurals(self, word, expected):
        assert singularize(word) == expected

    @pytest.mark.parametrize("word", [
        "asparagus", "couscous", "hummus", "molasses", "grits",
        "oats", "brussels", "harissa", "swiss", "bass",
    ], ids=lambda x: x)
    def test_exception_words_unchanged(self, word):
        assert singularize(word) == word

    def test_already_singular(self):
        assert singularize("chicken") == "chicken"
        assert singularize("flour") == "flour"
        assert singularize("rice") == "rice"


class TestStripParentheticals:
    def test_strip_parenthetical(self):
        result = normalize_ingredient_name("flour (all-purpose)")
        assert "all-purpose" not in result.name
        assert "flour" in result.name

    def test_multiple_parentheticals(self):
        result = normalize_ingredient_name("sugar (granulated) (white)")
        assert "granulated" not in result.name
        assert "white" not in result.name
        assert "sugar" in result.name

    def test_no_parenthetical(self):
        result = normalize_ingredient_name("olive oil")
        assert result.name == "olive oil"


class TestNormalizeHyphens:
    def test_hyphenated_word(self):
        result = normalize_ingredient_name("extra-virgin olive oil")
        assert result.name == "extra virgin olive oil"

    def test_no_hyphens(self):
        result = normalize_ingredient_name("olive oil")
        assert result.name == "olive oil"


class TestNormalizeIngredientName:
    def test_returns_normalized_result(self):
        result = normalize_ingredient_name("Tomatoes")
        assert isinstance(result, NormalizedResult)
        assert result.original_name == "Tomatoes"
        assert result.name == "tomato"

    def test_combined_strategies(self):
        result = normalize_ingredient_name("Onions (diced)")
        assert result.name == "onion"
        assert result.original_name == "Onions (diced)"

    def test_lowercased(self):
        result = normalize_ingredient_name("FLOUR")
        assert result.name == "flour"

    def test_whitespace_normalized(self):
        result = normalize_ingredient_name("  olive   oil  ")
        assert result.name == "olive oil"

    def test_empty_after_strip_falls_back(self):
        # Edge case: name is entirely a parenthetical
        result = normalize_ingredient_name("(garnish)")
        # Should not be empty
        assert result.name != ""
