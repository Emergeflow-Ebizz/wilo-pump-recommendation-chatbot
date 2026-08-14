"""Regression tests locking in pressure_boosting rules.py behavior."""
import pytest

from app.use_cases.pressure_boosting.rules import (
    NoPressureBoostingMatchError,
    PressureBoostingUseCase,
    _match_head,
    calculate_head,
    calculate_required_flow,
    resolve_pressure_boosting_catalog,
    select_model,
)


def test_calculate_head_one_floor():
    # 1 floor * 12 ft * 1.3 = 15.6 ft -> meters
    assert calculate_head(1) == pytest.approx(15.6 / 3.28084)


def test_calculate_head_scales_with_floors():
    assert calculate_head(10) == pytest.approx(calculate_head(1) * 10)


def test_calculate_required_flow_example_from_spec():
    # 6 bathrooms on a single floor * 20 LPM * 60% = 72 LPM
    assert calculate_required_flow(1, 6) == pytest.approx(72.0)


def test_calculate_required_flow_multiplies_floors_and_bathrooms():
    assert calculate_required_flow(3, 2) == pytest.approx(3 * 2 * 20 * 0.6)


def _model(flows_by_head, hp=0.5, art_no=1):
    return {
        "motor_rating": {"hp": hp},
        "performance_curves": [{"head": h, "flow": f} for h, f in flows_by_head.items()],
        "art_no": art_no,
        "phase": None,
    }


def test_match_head_decimal_exact():
    catalog = {"A": _model({7.5: 20})}
    assert _match_head(catalog, 7.5, decimal_mode=True) == 7.5


def test_match_head_decimal_rounds_target_then_rounds_up_to_next_available():
    # target 7.2 rounds to 7.2, not present; next higher available is 7.5
    catalog = {"A": _model({6.5: 25, 7.5: 20})}
    assert _match_head(catalog, 7.2, decimal_mode=True) == 7.5


def test_match_head_decimal_none_available_returns_none():
    catalog = {"A": _model({2.0: 30})}
    assert _match_head(catalog, 7.2, decimal_mode=True) is None


def test_match_head_whole_number_exact():
    catalog = {"A": _model({10: 50})}
    assert _match_head(catalog, 10, decimal_mode=False) == 10


def test_match_head_whole_number_rounds_up():
    catalog = {"A": _model({15: 50})}
    assert _match_head(catalog, 10.4, decimal_mode=False) == 15


def test_match_head_whole_number_none_available_returns_none():
    catalog = {"A": _model({5: 50})}
    assert _match_head(catalog, 10, decimal_mode=False) is None


def test_match_head_never_returns_below_fractional_target_whole_number_mode():
    """Regression: a fractional target must never match a lower whole-number
    head just because int(target_head) happens to exist in the catalog."""
    catalog = {"A": _model({14: 40, 15: 38})}
    assert _match_head(catalog, 14.6, decimal_mode=False) == 15


def test_match_head_never_returns_below_fractional_target_decimal_mode():
    catalog = {"A": _model({7.5: 20, 8.0: 18})}
    assert _match_head(catalog, 7.53, decimal_mode=True) == 8.0


def test_select_model_exact_flow_match_wins():
    catalog = {
        "A": _model({10: 72}),
        "B": _model({10: 100}),
    }
    result = select_model(catalog, 10, required_flow_lpm=72)
    assert [name for name, _ in result] == ["A"]


def test_select_model_no_exact_match_picks_next_higher_flow():
    catalog = {
        "A": _model({10: 60}),   # below requirement
        "B": _model({10: 90}),   # smallest flow still >= requirement
        "C": _model({10: 150}),  # higher than B, should not be picked
    }
    result = select_model(catalog, 10, required_flow_lpm=72)
    assert [name for name, _ in result] == ["B"]


def test_select_model_nothing_meets_requirement_raises():
    catalog = {
        "A": _model({10: 30}),
        "B": _model({10: 50}),
    }
    with pytest.raises(NoPressureBoostingMatchError):
        select_model(catalog, 10, required_flow_lpm=1000)


def test_select_model_no_required_flow_uses_highest_available():
    catalog = {
        "A": _model({10: 30}),
        "B": _model({10: 50}),
    }
    result = select_model(catalog, 10, required_flow_lpm=None)
    assert [name for name, _ in result] == ["B"]


def test_select_model_ties_all_returned():
    catalog = {
        "A": _model({10: 90}, art_no=1),
        "B": _model({10: 90}, art_no=2),
    }
    result = select_model(catalog, 10, required_flow_lpm=72)
    assert {name for name, _ in result} == {"A", "B"}


def test_resolve_catalog_low_head_matches_first_sheet_pb():
    # PB.json has heads as low as 2, well within a small building's head - it
    # should win before any other sheet in the sequence is even considered.
    catalog, sheet_name, matched_head, sheet_file = resolve_pressure_boosting_catalog(2.0)
    assert sheet_name == "PB"
    assert matched_head >= 2.0


def test_resolve_catalog_falls_through_to_later_sheet_when_earlier_sheets_cant_reach():
    # PB tops out well below the heads HWJ-FWJ/FMHIL/HMHIL reach; a very high
    # target head should skip PB/PW and land on a later sheet in the sequence.
    catalog, sheet_name, matched_head, sheet_file = resolve_pressure_boosting_catalog(29.0)
    assert sheet_name in {"HWJ-FWJ", "FMHIL", "HMHIL"}
    assert matched_head >= 29.0


def test_resolve_catalog_impossible_head_raises():
    with pytest.raises(NoPressureBoostingMatchError):
        resolve_pressure_boosting_catalog(10_000.0)


def test_resolve_catalog_skips_sheet_that_reaches_head_but_not_flow():
    """Regression: PB.json reaches head 12 but its best flow there (40 LPM)
    can't meet a 45 LPM requirement - the resolver must skip past PB (and PW,
    also short) to HWJ-FWJ, which reaches both, rather than locking onto PB
    just because it was first in the sequence and satisfied head alone."""
    catalog, sheet_name, matched_head, sheet_file = resolve_pressure_boosting_catalog(12, required_flow_lpm=45)
    assert sheet_name == "HWJ-FWJ"
    assert matched_head == 12


def test_resolve_catalog_climbs_one_head_level_when_matched_head_flow_insufficient():
    """PB.json's head 12.5 (PB-200) is the only sheet with that exact head,
    and its best flow there is only 15 LPM. A requirement of 30 LPM can't
    be met by any sheet at 12.5, but the next distinct head value across
    every sheet (13, also in PB via PB-400) offers 35 LPM - enough. The
    resolver should climb exactly one level, from 12.5 to 13, and land back
    on PB (checked first in SHEET_SEQUENCE) rather than stopping at 12.5 or
    needing to check any other sheet."""
    catalog, sheet_name, matched_head, sheet_file = resolve_pressure_boosting_catalog(12.5, required_flow_lpm=30)
    assert sheet_name == "PB"
    assert matched_head == 13


def test_resolve_catalog_raises_when_flow_unreachable_even_one_head_higher():
    """When neither the matched head (12.5) nor the single next-higher head
    (13) can meet an impossible required_flow_lpm in any sheet, raise
    rather than climbing further or falling back to an insufficient head -
    no model is recommended in that case."""
    with pytest.raises(NoPressureBoostingMatchError):
        resolve_pressure_boosting_catalog(12.5, required_flow_lpm=1_000_000)


def test_select_pump_end_to_end_falls_through_for_flow_when_head_alone_is_insufficient():
    uc = PressureBoostingUseCase()
    # 4 floors * 1 bathroom -> required_flow = 4*1*20*0.6 = 48 LPM, which PB
    # cannot deliver at its matched head even though PB reaches that head.
    rec = uc.select_pump({"num_floors": 4, "bathrooms_per_floor": 1})
    assert rec.details["required_flow"] == pytest.approx(48.0)
    assert rec.details["flow"] >= 48.0
    assert rec.details["sheet"] != "PB"
