"""Unit tests for ingredient scaling — sync, class-grouped, parametrized."""

import pytest

from recipe_app.scaling import (
    _build_scaled_text,
    format_quantity,
    scale_ingredient,
    scale_recipe_ingredients,
)


class TestFormatQuantity:
    @pytest.mark.parametrize(
        "value,expected",
        [
            pytest.param(3.0, "3", id="whole"),
            pytest.param(0.5, "1/2", id="half"),
            pytest.param(1.5, "1 1/2", id="mixed"),
            pytest.param(0.25, "1/4", id="quarter"),
            pytest.param(0.125, "1/8", id="eighth"),
            pytest.param(0.0, "0", id="zero"),
            pytest.param(1000.0, "1000", id="large-whole"),
        ],
    )
    def test_format_quantity(self, value, expected):
        assert format_quantity(value) == expected

    def test_format_quantity_negative(self):
        """Negative values should not crash."""
        result = format_quantity(-0.5)
        assert isinstance(result, str)


class TestScaleIngredient:
    def test_double(self):
        parsed = {"quantity": 2.0, "quantity_max": None, "scalable": True}
        result = scale_ingredient(parsed, 2.0)
        assert result["scaled_quantity"] == 4.0
        assert result["formatted_quantity"] == "4"

    def test_half(self):
        parsed = {"quantity": 2.0, "quantity_max": None, "scalable": True}
        result = scale_ingredient(parsed, 0.5)
        assert result["scaled_quantity"] == 1.0
        assert result["formatted_quantity"] == "1"

    def test_not_scalable(self):
        parsed = {"quantity": None, "scalable": False}
        result = scale_ingredient(parsed, 2.0)
        assert result["scaled_quantity"] is None
        assert result["formatted_quantity"] is None

    def test_range(self):
        parsed = {"quantity": 2.0, "quantity_max": 3.0, "scalable": True}
        result = scale_ingredient(parsed, 2.0)
        assert result["scaled_quantity"] == 4.0
        assert result["scaled_quantity_max"] == 6.0

    def test_no_quantity(self):
        parsed = {"quantity": None, "scalable": True}
        result = scale_ingredient(parsed, 2.0)
        assert result["scaled_quantity"] is None

    def test_zero_factor(self):
        parsed = {"quantity": 2.0, "quantity_max": None, "scalable": True}
        result = scale_ingredient(parsed, 0.0)
        assert result["scaled_quantity"] == 0.0
        assert result["formatted_quantity"] == "0"


class TestBuildScaledText:
    def test_with_unit(self):
        scaled = {
            "scalable": True,
            "formatted_quantity": "4",
            "formatted_quantity_max": "4",
            "unit": "cups",
            "name": "flour",
            "preparation": None,
        }
        assert _build_scaled_text(scaled) == "4 cups flour"

    def test_no_unit(self):
        scaled = {
            "scalable": True,
            "formatted_quantity": "3",
            "formatted_quantity_max": "3",
            "unit": None,
            "name": "eggs",
            "preparation": None,
        }
        assert _build_scaled_text(scaled) == "3 eggs"

    def test_with_prep(self):
        scaled = {
            "scalable": True,
            "formatted_quantity": "2",
            "formatted_quantity_max": "2",
            "unit": "cups",
            "name": "flour",
            "preparation": "sifted",
        }
        assert _build_scaled_text(scaled) == "2 cups flour , sifted"

    def test_range(self):
        scaled = {
            "scalable": True,
            "formatted_quantity": "4",
            "formatted_quantity_max": "6",
            "unit": "cups",
            "name": "flour",
            "preparation": None,
        }
        assert _build_scaled_text(scaled) == "4-6 cups flour"

    def test_not_scalable(self):
        scaled = {
            "scalable": False,
            "formatted_quantity": None,
            "original_text": "salt to taste",
        }
        assert _build_scaled_text(scaled) == "salt to taste"


class TestScaleRecipeIngredients:
    def test_multiple(self):
        results = scale_recipe_ingredients(["2 cups flour", "1 cup milk"], 2.0)
        assert len(results) == 2
        for r in results:
            assert "original_text" in r
            assert "scaled_text" in r

    def test_empty_list(self):
        assert scale_recipe_ingredients([], 2.0) == []
