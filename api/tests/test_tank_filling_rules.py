"""Regression tests locking in tank_filling rules.py behavior."""
import pytest

from app.use_cases.tank_filling.rules import (
    NoTankFillingMatchError,
    _has_exact_head,
    _match_head,
    calculate_head,
    resolve_monoblock_catalog,
    select_model,
)


def test_calculate_head_one_floor():
    # 1 floor * 12 ft * 1.3 = 15.6 ft -> meters
    assert calculate_head(1) == pytest.approx(15.6 / 3.28084)


def test_calculate_head_zero_floors_is_zero():
    assert calculate_head(0) == 0


def _model(hp, flows_by_head, art_no=1):
    return {
        "motor_rating": {"hp": hp},
        "performance_curves": [{"head": h, "flow": f} for h, f in flows_by_head.items()],
        "art_no": art_no,
        "phase": None,
    }


def test_match_head_exact():
    catalog = {"A": _model(1.0, {10: 100})}
    assert _match_head(catalog, 10) == 10


def test_match_head_rounds_up():
    catalog = {"A": _model(1.0, {15: 50})}
    assert _match_head(catalog, 10) == 15


def test_match_head_never_returns_below_fractional_target():
    """Regression: a fractional target must never match a lower whole-number
    head just because int(target_head) happens to exist in the catalog -
    that would erode the safety margin baked into target_head."""
    catalog = {"A": _model(1.0, {14: 40, 15: 38})}
    assert _match_head(catalog, 14.6) == 15


def test_match_head_no_head_available_raises():
    catalog = {"A": _model(1.0, {5: 50})}
    with pytest.raises(NoTankFillingMatchError):
        _match_head(catalog, 10)


def test_select_model_exact_hp_match():
    catalog = {
        "A": _model(1.0, {10: 100}),
        "B": _model(2.0, {10: 80}),
    }
    result = select_model(catalog, 10, desired_hp=2.0)
    assert [name for name, _ in result] == ["B"]


def test_select_model_no_hp_given_uses_lowest_hp():
    catalog = {
        "A": _model(1.0, {10: 100}),
        "B": _model(2.0, {10: 80}),
    }
    result = select_model(catalog, 10, desired_hp=None)
    assert [name for name, _ in result] == ["A"]


def test_select_model_ties_all_returned():
    catalog = {
        "A": _model(1.0, {10: 100}, art_no=1),
        "B": _model(1.0, {10: 100}, art_no=2),
    }
    result = select_model(catalog, 10, desired_hp=None)
    assert {name for name, _ in result} == {"A", "B"}


def test_has_exact_head_true_and_false():
    catalog = {"A": _model(1.0, {10: 100})}
    assert _has_exact_head(catalog, 10) is True
    assert _has_exact_head(catalog, 11) is False


def test_resolve_monoblock_catalog_exact_head_first_sheet_wins():
    # Kushal.json has heads as low as 3 - a small target head should resolve
    # there before any later sheet in MONOBLOCK_SEQUENCE is even considered.
    catalog, sheet_name, sheet_file = resolve_monoblock_catalog(3, desired_hp=None)
    assert sheet_name == "Khushal"


def test_resolve_monoblock_catalog_never_matches_below_fractional_target():
    """End-to-end regression against the real catalog: a fractional target
    head must resolve to a sheet reaching at least that head, not one whose
    truncated-integer head happens to already exist."""
    catalog, sheet_name, sheet_file = resolve_monoblock_catalog(14.6, desired_hp=None)
    heads = {p["head"] for m in catalog.values() for p in m["performance_curves"]}
    assert any(h >= 14.6 for h in heads)


def test_resolve_monoblock_catalog_impossible_head_raises():
    with pytest.raises(NoTankFillingMatchError):
        resolve_monoblock_catalog(10_000.0, desired_hp=None)
