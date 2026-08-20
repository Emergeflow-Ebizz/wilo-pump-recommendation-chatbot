"""Regression tests locking in heat_circulation rules.py behavior."""
import pytest

from app.use_cases.heat_circulation.rules import (
    AREA_THRESHOLD_SQM,
    build_recommendations,
    normalize_area,
    select_heat_circulation_pumps,
)
from app.common.units import sqft_to_sqm


def test_normalize_area_sqm_passthrough():
    assert normalize_area(100, "sqm") == 100


def test_normalize_area_sqft_converts():
    assert normalize_area(1000, "sqft") == pytest.approx(sqft_to_sqm(1000))


def test_normalize_area_unknown_unit_raises():
    with pytest.raises(ValueError):
        normalize_area(100, "cm")


def test_ufh_up_to_threshold():
    assert select_heat_circulation_pumps(AREA_THRESHOLD_SQM, "ufh") == ("Yonos PICO", "Stratos PICO")


def test_ufh_above_threshold():
    assert select_heat_circulation_pumps(AREA_THRESHOLD_SQM + 0.01, "ufh") == ("Yonos MAXO", "Stratos MAXO")


def test_radiators_up_to_threshold():
    assert select_heat_circulation_pumps(AREA_THRESHOLD_SQM, "radiators") == ("PARA", None)


def test_radiators_above_threshold():
    assert select_heat_circulation_pumps(AREA_THRESHOLD_SQM + 0.01, "radiators") == ("PARA MAXO", None)


def test_unknown_heating_system_raises():
    with pytest.raises(ValueError):
        select_heat_circulation_pumps(100, "gas_boiler")


def test_build_recommendations_ufh_includes_premium():
    standard, premium = build_recommendations(100, "ufh")
    assert standard.model_name == "Yonos PICO"
    assert premium.model_name == "Stratos PICO"
    assert standard.features
    assert premium.features
    assert standard.details["specs"]["flow"] == "Up to 4 m3/hr"
    assert premium.details["specs"]["flow"] == "Up to 4 m3/hr"


def test_build_recommendations_radiators_has_no_premium():
    standard, premium = build_recommendations(100, "radiators")
    assert standard.model_name == "PARA"
    assert premium is None
