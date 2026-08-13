from app.common.catalog_loader import load_sheet
from app.common.features import get_features
from app.common.images import get_image_url
from app.common.schemas import FeasibilityResult, PumpRecommendation
from app.common.units import ft_to_m, m_to_ft
from app.use_cases.base import UseCase
from app.use_cases.dewatering.questions import QUESTIONS
from app.use_cases.dewatering.sheet_map import SHEET_SEQUENCE

HEAD_SAFETY_FACTOR = 1.3

NO_MODEL_AVAILABLE_MESSAGE = "We do not have the pump specification required by you."


class NoDewateringMatchError(Exception):
    pass


def normalize_depth_of_pit(value: float, unit: str) -> float:
    """Normalize a depth-of-pit answer to feet."""
    if unit == "m":
        return m_to_ft(value)
    if unit == "ft":
        return value
    raise ValueError(f"Unsupported depth of pit unit: {unit}")


def calculate_head(depth_of_pit_ft: float) -> float:
    """Calculate head in feet, then convert to meters for catalog matching.

    Rounded to 2dp so unit round-trip float noise (e.g. 39.00000000000001)
    never pushes a value into the next catalog head bucket.
    """
    head_ft = depth_of_pit_ft * HEAD_SAFETY_FACTOR
    return round(ft_to_m(head_ft), 2)


def _heads_in_catalog(catalog: dict) -> set:
    return {
        point["head"]
        for model in catalog.values()
        for point in model["performance_curves"]
    }


def _match_head(catalog: dict, target_head: float) -> float | None:
    """Match target head to a head in the catalog, or None if none is high enough.

    Always the smallest listed head that is >= target_head - never rounds
    down, so the safety margin baked into target_head is never eroded.
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


def resolve_dewatering_catalog(target_head: float) -> tuple[dict, str, float, str]:
    """Walk SHEET_SEQUENCE in order; the first sheet with any head >= target wins.

    Returns (catalog, sheet_name, matched_head, sheet_file). Raises
    NoDewateringMatchError if no sheet in the sequence has a head high enough.
    """
    for sheet_name, sheet_file in SHEET_SEQUENCE:
        catalog = load_sheet(sheet_file)
        matched_head = _match_head(catalog, target_head)
        if matched_head is not None:
            return catalog, sheet_name, matched_head, sheet_file

    raise NoDewateringMatchError(NO_MODEL_AVAILABLE_MESSAGE)


def select_model(catalog: dict, matched_head: float, desired_hp: float | None) -> list[tuple[str, dict]]:
    """Return every model tied for best match at the matched head.

    If desired_hp is given and some candidate has exactly that HP, restrict to
    those. Otherwise (no desired_hp given, or the given HP isn't present) fall
    back to the lowest motor_rating.hp among candidates. Ties at the same HP
    are broken by highest flow at the matched head.
    """
    candidates = [
        (name, model)
        for name, model in catalog.items()
        if _flow_at_head(model, matched_head) is not None
    ]

    if desired_hp is not None:
        exact_hp_matches = [
            (name, model) for name, model in candidates if model["motor_rating"]["hp"] == desired_hp
        ]
        if exact_hp_matches:
            candidates = exact_hp_matches
        else:
            lowest_hp = min(model["motor_rating"]["hp"] for _, model in candidates)
            candidates = [(name, model) for name, model in candidates if model["motor_rating"]["hp"] == lowest_hp]
    else:
        lowest_hp = min(model["motor_rating"]["hp"] for _, model in candidates)
        candidates = [(name, model) for name, model in candidates if model["motor_rating"]["hp"] == lowest_hp]

    best_flow = max(_flow_at_head(model, matched_head) for _, model in candidates)
    return [
        (name, model)
        for name, model in candidates
        if _flow_at_head(model, matched_head) == best_flow
    ]


class DewateringUseCase(UseCase):
    slug = "dewatering"
    questions = QUESTIONS

    def check_feasibility(self, answers: dict) -> FeasibilityResult:
        """Checks depth_of_pit as soon as it's answered - it's the only
        field that determines target_head, so motor_power_hp is never
        needed here."""
        depth_of_pit = answers.get("depth_of_pit")
        depth_of_pit_unit = answers.get("depth_of_pit_unit")
        if depth_of_pit is None or depth_of_pit_unit is None:
            return FeasibilityResult(status="pending")

        depth_of_pit_ft = normalize_depth_of_pit(depth_of_pit, depth_of_pit_unit)
        target_head = calculate_head(depth_of_pit_ft)
        try:
            resolve_dewatering_catalog(target_head)
        except NoDewateringMatchError as e:
            return FeasibilityResult(status="rejected", message=str(e))

        return FeasibilityResult(status="ok")

    def select_pump(self, answers: dict) -> PumpRecommendation:
        depth_of_pit_ft = normalize_depth_of_pit(*answers["depth_of_pit"])
        desired_hp = answers.get("motor_power_hp")

        target_head = calculate_head(depth_of_pit_ft)
        catalog, sheet_name, matched_head, sheet_file = resolve_dewatering_catalog(target_head)
        matched_models = select_model(catalog, matched_head, desired_hp)

        def build_recommendation(model_name: str, model: dict) -> PumpRecommendation:
            flow_lpm = _flow_at_head(model, matched_head)
            details = {
                "sheet": sheet_name,
                "target_head": target_head,
                "matched_head": matched_head,
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
