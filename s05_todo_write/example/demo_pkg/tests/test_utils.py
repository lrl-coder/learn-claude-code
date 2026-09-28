"""Tests for :mod:`demo_pkg.utils`."""

from demo_pkg.utils import add


def test_adds_positive_numbers() -> None:
    """Add two positive numbers."""
    assert add(2, 3) == 5


def test_adds_negative_and_positive_numbers() -> None:
    """Add numbers with different signs."""
    assert add(-2, 3) == 1


def test_adds_zero() -> None:
    """Adding zero leaves a number unchanged."""
    assert add(7, 0) == 7
