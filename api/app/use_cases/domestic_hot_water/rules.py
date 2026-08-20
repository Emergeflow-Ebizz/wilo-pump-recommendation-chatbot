from app.common.schemas import PumpRecommendation
from app.use_cases.base import UseCase
from app.use_cases.domestic_hot_water.questions import QUESTIONS


def select_dhw_pump(num_usage_points: int) -> str:
    if num_usage_points <= 2:
        return "Star-Z NOVA"
    if num_usage_points <= 5:
        return "Star-Z NOVA A"
    return "Star-Z NOVA T"


class DomesticHotWaterUseCase(UseCase):
    slug = "domestic_hot_water"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        num_usage_points = answers["num_usage_points"]
        model_name = select_dhw_pump(num_usage_points)
        return PumpRecommendation(
            model_name=model_name,
            details={"num_usage_points": num_usage_points},
        )
