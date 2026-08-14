from app.common.catalog_loader import load_sheet
from app.common.features import get_features
from app.common.images import get_image_url
from app.common.schemas import PumpRecommendation
from app.common.units import ft_to_m
from app.use_cases.base import UseCase
from app.use_cases.pressure_boosting.questions import QUESTIONS
from app.use_cases.pressure_boosting.sheet_map import SHEET_SEQUENCE

FLOOR_HEIGHT_FT = 12
HEAD_SAFETY_FACTOR = 1.3
SYSTEM_LOSSES_M = 25.5  # Fixed system losses: friction, fittings, and discharge pressure
FLOW_PER_BATHROOM_LPM = 20
UTILISATION_FACTOR = 0.6

NO_MODEL_AVAILABLE_MESSAGE = "We do not have the pump specification required by you."


class NoPressureBoostingMatchError(Exception):
    pass


def calculate_head(num_floors: int) -> float:
    """Calculate head in meters: (num_floors * 12 ft * 1.3) + 25.5 m system losses."""
    head_ft = (num_floors * FLOOR_HEIGHT_FT) * HEAD_SAFETY_FACTOR
    return ft_to_m(head_ft) + SYSTEM_LOSSES_M


def calculate_required_flow(num_floors: int, bathrooms_per_floor: int) -> float:
    total_bathrooms = num_floors * bathrooms_per_floor
    total_flow_lpm = total_bathrooms * FLOW_PER_BATHROOM_LPM
    return total_flow_lpm * UTILISATION_FACTOR


def _heads_in_catalog(catalog: dict) -> set:
    return {
        point["head"]
        for model in catalog.values()
        for point in model["performance_curves"]
    }


def _match_head(catalog: dict, target_head: float, decimal_mode: bool) -> float | None:
    """Match target head to a head in the catalog, or None if none is high enough.

    Always the smallest listed head that is >= target_head - never rounds
    down, so the safety margin baked into target_head is never eroded.
    decimal_mode is retained for API compatibility but no longer changes the
    matching outcome: rounding target_head before comparing could only ever
    move the threshold down, which this function must never do.
    """
    heads = _heads_in_catalog(catalog)

    candidates = sorted(h for h in heads if h >= target_head)
    if not candidates:
        return None
    return candidates[0]


def _flow_at_head(model: dict, head: float) -> float | None:
    for point in model["performance_curves"]:
        if point["head"] == head:
            return point["flow"]
    return None


def _best_flow_at_head(catalog: dict, head: float) -> float:
    flows = [_flow_at_head(model, head) for model in catalog.values()]
    return max((f for f in flows if f is not None), default=0.0)


def _next_head_above(catalog: dict, head: float) -> float | None:
    higher = sorted(h for h in _heads_in_catalog(catalog) if h > head)
    return higher[0] if higher else None


def resolve_pressure_boosting_catalog(
    target_head: float, required_flow_lpm: float | None = None
) -> tuple[dict, str, float, str]:
    """Walk SHEET_SEQUENCE at each sheet's own matched head, then (if
    needed) exactly one head level higher in that same sheet, to find a
    sheet/head that can deliver required_flow_lpm - never returns a match
    whose best flow at the matched head is below required_flow_lpm.

    When required_flow_lpm is given, two passes over SHEET_SEQUENCE:

    Pass 1: for each sheet, its own matched head (the smallest head in
    that sheet's own catalog that is >= target_head, via _match_head). The
    first sheet whose best flow there reaches required_flow_lpm wins.

    Pass 2 (only if pass 1 found nothing): for each sheet, exactly one head
    level above its own matched head - still that sheet's own next
    available head, not some other sheet's. The first sheet whose best flow
    there reaches required_flow_lpm wins.

    Each sheet's climb is anchored to its own head grid rather than a
    shared list of head values across all sheets - the sheets have
    different, unevenly spaced head points, so comparing across a shared
    list would skip a sheet's genuinely-nearby head just because another
    sheet happened to have a closer point at that exact value.

    When required_flow_lpm is None: unchanged - the first sheet with any
    head >= target wins regardless of flow.

    Returns (catalog, sheet_name, matched_head, sheet_file). Raises
    NoPressureBoostingMatchError if no sheet/head combination satisfies the
    requirement - for required_flow_lpm given, this means neither a
    sheet's matched head nor its next head level up reaches it in any
    sheet; we never fall back to a head that can't deliver enough flow.
    """
    if required_flow_lpm is not None:
        catalogs = {}
        matched_heads = {}
        for sheet_name, sheet_file, decimal_mode in SHEET_SEQUENCE:
            catalog = load_sheet(sheet_file)
            catalogs[sheet_file] = catalog
            matched_heads[sheet_file] = _match_head(catalog, target_head, decimal_mode)

        for sheet_name, sheet_file, _decimal_mode in SHEET_SEQUENCE:
            matched_head = matched_heads[sheet_file]
            if matched_head is not None and _best_flow_at_head(catalogs[sheet_file], matched_head) >= required_flow_lpm:
                return catalogs[sheet_file], sheet_name, matched_head, sheet_file

        for sheet_name, sheet_file, _decimal_mode in SHEET_SEQUENCE:
            matched_head = matched_heads[sheet_file]
            if matched_head is None:
                continue
            next_head = _next_head_above(catalogs[sheet_file], matched_head)
            if next_head is not None and _best_flow_at_head(catalogs[sheet_file], next_head) >= required_flow_lpm:
                return catalogs[sheet_file], sheet_name, next_head, sheet_file

        raise NoPressureBoostingMatchError(NO_MODEL_AVAILABLE_MESSAGE)

    for sheet_name, sheet_file, decimal_mode in SHEET_SEQUENCE:
        catalog = load_sheet(sheet_file)
        matched_head = _match_head(catalog, target_head, decimal_mode)
        if matched_head is not None:
            return catalog, sheet_name, matched_head, sheet_file

    raise NoPressureBoostingMatchError(NO_MODEL_AVAILABLE_MESSAGE)


def select_model(catalog: dict, matched_head: float, required_flow_lpm: float | None) -> list[tuple[str, dict]]:
    """Return every model tied for best match at the matched head.

    No HP filtering (pressure_boosting has no motor-power question). If
    required_flow_lpm is given and a model's flow at the matched head equals
    it exactly, that wins. Otherwise pick the smallest flow that still meets
    or exceeds required_flow_lpm ("next higher flow"). If no requirement was
    given, fall back to the highest flow actually available at that head.
    All within this one sheet/catalog - never looks at other sheets.

    resolve_pressure_boosting_catalog only ever hands this a (catalog,
    matched_head) pair where required_flow_lpm is already known to be
    reachable there, so the "nothing reaches it" branch below should be
    unreachable in practice; it raises rather than silently returning a
    below-required flow, since a caller invoking this directly with a head
    that can't meet the requirement should get the same "no model" outcome
    resolve_pressure_boosting_catalog would have given.
    """
    candidates = [
        (name, model)
        for name, model in catalog.items()
        if _flow_at_head(model, matched_head) is not None
    ]

    if required_flow_lpm is not None:
        exact_matches = [
            (name, model) for name, model in candidates if _flow_at_head(model, matched_head) == required_flow_lpm
        ]
        if exact_matches:
            candidates = exact_matches
        else:
            above = [
                (name, model)
                for name, model in candidates
                if _flow_at_head(model, matched_head) > required_flow_lpm
            ]
            if above:
                next_higher_flow = min(_flow_at_head(model, matched_head) for _, model in above)
                candidates = [(name, model) for name, model in above if _flow_at_head(model, matched_head) == next_higher_flow]
            else:
                raise NoPressureBoostingMatchError(NO_MODEL_AVAILABLE_MESSAGE)
    else:
        highest_flow = max(_flow_at_head(model, matched_head) for _, model in candidates)
        candidates = [(name, model) for name, model in candidates if _flow_at_head(model, matched_head) == highest_flow]

    return candidates


class PressureBoostingUseCase(UseCase):
    slug = "pressure_boosting"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        num_floors = answers["num_floors"]
        bathrooms_per_floor = answers["bathrooms_per_floor"]

        target_head = calculate_head(num_floors)
        required_flow_lpm = calculate_required_flow(num_floors, bathrooms_per_floor)

        catalog, sheet_name, matched_head, sheet_file = resolve_pressure_boosting_catalog(target_head, required_flow_lpm)
        matched_models = select_model(catalog, matched_head, required_flow_lpm)

        def build_recommendation(model_name: str, model: dict) -> PumpRecommendation:
            flow_lpm = _flow_at_head(model, matched_head)
            details = {
                "sheet": sheet_name,
                "target_head": target_head,
                "matched_head": matched_head,
                "required_flow": required_flow_lpm,
                "flow": flow_lpm,
                "hp": model["motor_rating"]["hp"],
                "phase": model.get("phase"),
            }
            return PumpRecommendation(
                model_name=model_name,
                art_no=model.get("art_no"),
                details=details,
                features=get_features(sheet_file),
                image_url=get_image_url(sheet_file),
            )

        primary_name, primary_model = matched_models[0]
        recommendation = build_recommendation(primary_name, primary_model)
        recommendation.tied_alternatives = [
            build_recommendation(name, model) for name, model in matched_models[1:]
        ]
        return recommendation
