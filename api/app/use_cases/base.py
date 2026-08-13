from abc import ABC, abstractmethod

from app.common.schemas import FeasibilityResult, PumpRecommendation, Question


class UseCase(ABC):
    slug: str
    questions: list[Question]

    @abstractmethod
    def select_pump(self, answers: dict) -> PumpRecommendation:
        ...

    def check_feasibility(self, answers: dict) -> FeasibilityResult:
        """Checks whether the answers collected so far already rule out a
        match, without waiting for every question to be answered. Default:
        always pending - use cases with a match-determining field override
        this."""
        return FeasibilityResult(status="pending")
