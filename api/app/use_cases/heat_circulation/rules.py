from app.common.features import get_features
from app.common.schemas import PumpRecommendation
from app.common.specs import get_specs
from app.common.units import sqft_to_sqm
from app.use_cases.base import UseCase
from app.use_cases.heat_circulation.questions import QUESTIONS

AREA_THRESHOLD_SQM = 250

# heating_system -> (standard model, premium model or None), keyed by
# whether area_sqm is up to (<=) or above (>) AREA_THRESHOLD_SQM.
MODELS_BY_HEATING_SYSTEM = {
    "ufh": {
        "up_to_threshold": ("Yonos PICO", "Stratos PICO"),
        "above_threshold": ("Yonos MAXO", "Stratos MAXO"),
    },
    "radiators": {
        "up_to_threshold": ("PARA", None),
        "above_threshold": ("PARA MAXO", None),
    },
}


def normalize_area(value: float, unit: str) -> float:
    """Normalize a total_area answer to square meters."""
    if unit == "sqft":
        return sqft_to_sqm(value)
    if unit == "sqm":
        return value
    raise ValueError(f"Unsupported area unit: {unit}")


def select_heat_circulation_pumps(area_sqm: float, heating_system: str) -> tuple[str, str | None]:
    """Return (standard_model_name, premium_model_name_or_none) for the given
    area (always evaluated in sq m) and heating system."""
    try:
        tiers = MODELS_BY_HEATING_SYSTEM[heating_system]
    except KeyError:
        raise ValueError(f"Unknown heating_system: {heating_system}")

    tier = "up_to_threshold" if area_sqm <= AREA_THRESHOLD_SQM else "above_threshold"
    return tiers[tier]


def build_recommendations(area_sqm: float, heating_system: str) -> tuple[PumpRecommendation, PumpRecommendation | None]:
    """Return (standard_recommendation, premium_recommendation_or_none)."""
    standard_model, premium_model = select_heat_circulation_pumps(area_sqm, heating_system)

    details = {"area_sqm": area_sqm, "heating_system": heating_system}
    standard = PumpRecommendation(
        model_name=standard_model,
        details=dict(details, tier="standard", specs=get_specs(standard_model)),
        features=get_features(standard_model),
    )
    premium = (
        PumpRecommendation(
            model_name=premium_model,
            details=dict(details, tier="premium", specs=get_specs(premium_model)),
            features=get_features(premium_model),
        )
        if premium_model is not None
        else None
    )
    return standard, premium


class HeatCirculationUseCase(UseCase):
    slug = "heat_circulation"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        area_sqm = normalize_area(*answers["total_area"])
        heating_system = answers["heating_system"]

        standard, _premium = build_recommendations(area_sqm, heating_system)
        return standard
