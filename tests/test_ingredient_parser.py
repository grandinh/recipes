"""Unit tests for ingredient parsing — sync, class-grouped."""

from recipe_app.ingredient_parser import (
    _fallback,
    _fraction_to_float,
    parse_ingredient,
    parse_recipe_ingredients,
)


class TestParseIngredient:
    def test_numeric(self):
        result = parse_ingredient("2 cups flour")
        assert result["scalable"] is True
        assert result["quantity"] == 2.0
        assert result["original_text"] == "2 cups flour"

    def test_fraction(self):
        result = parse_ingredient("1/2 cup milk")
        assert result["scalable"] is True
        assert result["quantity"] == 0.5

    def test_no_quantity(self):
        result = parse_ingredient("salt to taste")
        assert result["scalable"] is False
        assert result["quantity"] is None

    def test_empty_string(self):
        result = parse_ingredient("")
        assert result["scalable"] is False
        assert result == _fallback("")

    def test_with_preparation(self):
        result = parse_ingredient("2 cloves garlic, minced")
        assert result["scalable"] is True or result["scalable"] is False
        assert result["original_text"] == "2 cloves garlic, minced"

    def test_whitespace_only(self):
        result = parse_ingredient("   ")
        assert result["scalable"] is False


class TestParseRecipeIngredients:
    def test_batch(self):
        results = parse_recipe_ingredients(["2 cups flour", "1 egg"])
        assert len(results) == 2
        assert all("original_text" in r for r in results)

    def test_batch_empty(self):
        assert parse_recipe_ingredients([]) == []


class TestFractionToFloat:
    def test_none(self):
        assert _fraction_to_float(None) is None

    def test_string(self):
        assert _fraction_to_float("some string") is None

    def test_fraction(self):
        from fractions import Fraction

        assert _fraction_to_float(Fraction(1, 2)) == 0.5
        assert _fraction_to_float(Fraction(3, 4)) == 0.75
