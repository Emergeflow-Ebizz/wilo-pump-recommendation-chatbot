from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="num_usage_points",
        prompt="How many usage points does the building have, including showers, wash basins, etc.?",
        requires_integer=True,
        min_value=1,
        domain_context=(
            "Counts fixtures drawing hot water (showers, wash basins, etc.) - "
            "determines which DHW recirculation pump is recommended. Must be a "
            "whole number - fractional usage points are meaningless."
        ),
    ),
]


def next_question(answers: dict) -> Question | None:
    """Return the next question to ask given answers collected so far."""
    for question in QUESTIONS:
        if question.key in answers:
            continue
        return question
    return None
