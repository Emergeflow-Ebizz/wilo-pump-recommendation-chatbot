"""Regression tests locking in domestic_hot_water rules.py behavior."""
from app.use_cases.domestic_hot_water.rules import select_dhw_pump


def test_one_usage_point():
    assert select_dhw_pump(1) == "Star-Z NOVA"


def test_two_usage_points():
    assert select_dhw_pump(2) == "Star-Z NOVA"


def test_three_usage_points():
    assert select_dhw_pump(3) == "Star-Z NOVA A"


def test_five_usage_points():
    assert select_dhw_pump(5) == "Star-Z NOVA A"


def test_six_usage_points():
    assert select_dhw_pump(6) == "Star-Z NOVA T"


def test_large_usage_points():
    assert select_dhw_pump(20) == "Star-Z NOVA T"
