"""Tests for parse_ingredient with preserve_fractions=True."""

from fractions import Fraction

from recipe_app.ingredient_parser import parse_ingredient


def test_preserve_fractions_returns_fraction():
    result = parse_ingredient("2 cups flour", preserve_fractions=True)
    assert isinstance(result["quantity"], Fraction)
    assert result["quantity"] == Fraction(2)


def test_preserve_fractions_half():
    result = parse_ingredient("1/2 cup milk", preserve_fractions=True)
    assert isinstance(result["quantity"], Fraction)
    assert result["quantity"] == Fraction(1, 2)


def test_preserve_fractions_no_quantity():
    result = parse_ingredient("salt to taste", preserve_fractions=True)
    assert result["quantity"] is None
    assert result["scalable"] is False


def test_default_returns_float():
    result = parse_ingredient("2 cups flour")
    assert isinstance(result["quantity"], float)
    assert result["quantity"] == 2.0


def test_preserve_fractions_scalable():
    result = parse_ingredient("3 tablespoons oil", preserve_fractions=True)
    assert result["scalable"] is True
    assert isinstance(result["quantity"], Fraction)
