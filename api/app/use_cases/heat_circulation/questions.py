from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="total_area",
        prompt="What is the total area of the building? (in **square meters** or **square feet**)",
        allowed_units=["sqm", "sqft"],
        requires_stated_unit=True,
        min_value=0,
        domain_context=(
            "Determines which Wilo pump tier is recommended - up to 250 sq m vs "
            "above 250 sq m. Valid units are sqm and sqft - the user must state "
            "which one, this is never inferred from the number alone. The user "
            "may phrase the unit as 'meter'/'m'/'sq m'/'square meters' (all map "
            "to sqm) or 'feet'/'ft'/'sq ft'/'square feet' (all map to sqft) - no "
            "other unit words are valid for this question. There is no maximum "
            "area, and zero is a valid (if unusual) area - only negative values "
            "are rejected."
        ),
    ),
]

HEATING_SYSTEM_QUESTION = Question(
    key="heating_system",
    prompt=(
        "How is the building heated? Underfloor Heating (UFH) or Radiators"
    ),
    domain_context=(
        "Determines which pump model family is recommended: Underfloor "
        "Heating (best for heat pumps, typical water temperature 35-40C, "
        "highest efficiency) selects from the Yonos PICO / Stratos PICO / "
        "Yonos MAXO / Stratos MAXO family; Radiators (may require higher "
        "temperatures, common in existing homes) selects from the PARA / "
        "PARA MAXO family. Valid values are 'ufh' and 'radiators'."
    ),
)


def next_question(answers: dict) -> Question | None:
    """Return the next question to ask given answers collected so far."""
    for question in QUESTIONS:
        if question.key in answers:
            continue
        return question

    if "heating_system" not in answers:
        return HEATING_SYSTEM_QUESTION

    return None
