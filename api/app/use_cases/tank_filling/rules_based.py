"""Tank filling rule-based parsing - no LLM, pure pattern matching and keywords.

Used only when LLM is unavailable. Includes clarification with standard messages.
Validates: value extraction, unit matching, rounding, negative rejection.
NO unit conversion - strict matching only.
"""
import re
import logging
import math

from app.common.schemas import Question, ParsedAnswer, ParsedCategory
from app.use_cases.tank_filling.config import (
    CATEGORY_KEYWORDS,
    CATEGORY_LABELS,
    MOTOR_POWER_HP_CONFIG,
    NUM_FLOORS_CONFIG,
    TANK_CAPACITY_CONFIG,
)

logger = logging.getLogger(__name__)


# ===== ROUNDING FUNCTIONS =====

def _round_motor_power_hp(value: float) -> float:
    """Round DOWN to smaller for motor_power_hp (2.5 → 2)."""
    return math.floor(value)


def _apply_rounding(value: float, question_key: str) -> float:
    """Apply question-specific rounding."""
    if question_key == "motor_power_hp":
        return _round_motor_power_hp(value)
    return value


# ===== VALIDATION HELPERS =====

def _reject_negative(value: float) -> bool:
    """Reject negative values."""
    return value < 0


def _reject_below_min(value: float, min_value: float | None) -> bool:
    """Reject values below minimum."""
    if min_value is None:
        return False
    return value < min_value


def _reject_non_integer(value: float) -> bool:
    """Reject non-whole numbers."""
    return value != int(value)


# ===== NUMERIC PARSING (value + unit) =====

def try_parse_numeric(
    user_text: str,
    allowed_units: list[str] | None,
    question: Question,
    previous_value: float | None = None,
) -> dict | None:
    """Try to extract value + unit using regex/pattern matching.

    Returns a dict matching LLM response schema if clear match found, else None.
    Used as fallback when LLM unavailable (rule-based mode).

    Questions handled:
    - tank_capacity: value (litres) - no unit needed, decimals ok
    - num_floors: whole number only, min 0
    - motor_power_hp: value, round DOWN - no unit needed

    Rules:
    - Reject negative values
    - For motor_power_hp: round DOWN to smaller
    - For num_floors: reject decimals and values < min_value
    - Accept previous_value + new_unit combination
    - NO unit conversion (strict matching only)
    """
    user_text = user_text.strip()
    if not user_text:
        return None

    # ===== NO UNITS REQUIRED (tank_capacity, num_floors, motor_power_hp) =====
    if allowed_units is None:
        match = re.match(r'^\s*([+-]?\d+(?:\.\d+)?)\s*$', user_text)
        if not match:
            return None

        value = float(match.group(1))

        # Reject negative
        if _reject_negative(value):
            return None

        # Reject non-integer if required
        if question.requires_integer and _reject_non_integer(value):
            return None

        # Reject below minimum
        if _reject_below_min(value, question.min_value):
            return None

        # Apply rounding if needed
        value = _apply_rounding(value, question.key)

        return {
            "value": value,
            "unit": None,
            "needs_clarification": False,
            "clarification_question": None,
            "skipped": False,
            "redirect_key": None,
            "gave_up": False,
        }

    # Not applicable for tank_filling (no questions with units)
    return None


# ===== CATEGORY PARSING (inside_or_outside, horizontal_or_vertical) =====

def try_parse_category(user_text: str, valid_categories: list[str]) -> str | None:
    """Try to match user text to tank_filling category using keywords only.

    Returns the matched category, or None if no match found or ambiguous.
    Rule-based mode: NO natural language understanding, keyword matching only.
    """
    cleaned = user_text.strip().lower()
    if not cleaned:
        return None

    # Exact match
    if cleaned in valid_categories:
        return cleaned

    # Keyword matching
    matches = set()
    for category in valid_categories:
        if category not in CATEGORY_KEYWORDS:
            continue
        for keyword in CATEGORY_KEYWORDS[category]:
            if keyword in cleaned:
                matches.add(category)
                break

    if len(matches) == 1:
        return next(iter(matches))
    return None


def get_category_label(category: str) -> str:
    """Get human-readable label for tank_filling category."""
    label = CATEGORY_LABELS.get(category)
    if label is None:
        logger.warning("tank_filling rules_based: no label for category %r", category)
        return category.replace("_", " ")
    return label


# ===== CLARIFICATION MESSAGE =====

def get_clarification_message(question_key: str) -> str:
    """Standard clarification message for rule-based mode."""
    field_names = {
        "tank_capacity": "tank capacity",
        "num_floors": "number of floors",
        "motor_power_hp": "motor power",
        "inside_or_outside": "installation type",
        "horizontal_or_vertical": "tank orientation",
    }
    field_name = field_names.get(question_key, question_key.replace("_", " "))
    return f"This is missing. Please provide {field_name}."


# ===== PUBLIC API FOR PARSER =====

def parse_answer_rule_based(
    question: Question,
    user_text: str,
    clarification_attempts: int = 0,
    previous_value: float | None = None,
) -> ParsedAnswer:
    """Rule-based numeric answer parsing (fallback when LLM unavailable).

    Max 3 attempts with standard clarification message.
    After 3 attempts: gave_up=True, move to next question.
    """
    # Handle confirmation of previous value
    if previous_value is not None and user_text.lower().strip() in ("yes", "yeah", "ok", "okay", "confirm", "yes."):
        return ParsedAnswer(
            value=previous_value,
            needs_clarification=False,
        )

    parsed = try_parse_numeric(user_text, question.allowed_units, question, previous_value)

    if parsed is not None:
        return ParsedAnswer(**parsed)

    # Parsing failed
    if question.optional:
        return ParsedAnswer(skipped=True)

    # Check if we've exceeded 3 attempts
    if clarification_attempts >= 3:
        return ParsedAnswer(
            gave_up=True,
            clarification_question="We cannot recommend a pump model without this information.",
        )

    # Ask for clarification
    return ParsedAnswer(
        needs_clarification=True,
        clarification_question=get_clarification_message(question.key),
    )


def parse_category_rule_based(
    question: Question,
    user_text: str,
    valid_categories: list[str],
    clarification_attempts: int = 0,
) -> ParsedCategory:
    """Rule-based category answer parsing (fallback when LLM unavailable).

    Max 3 attempts with standard clarification message.
    After 3 attempts: gave_up=True, move to next question.
    """
    parsed = try_parse_category(user_text, valid_categories)

    if parsed is not None:
        return ParsedCategory(
            category=parsed,
            confirmation_message=f"Got it: {get_category_label(parsed)}",
        )

    # Parsing failed
    if question.optional:
        return ParsedCategory(skipped=True)

    # Check if we've exceeded 3 attempts
    if clarification_attempts >= 3:
        return ParsedCategory(
            gave_up=True,
            clarification_question="We cannot recommend a pump model without this information.",
        )

    # Ask for clarification
    labels = [get_category_label(c) for c in valid_categories]
    return ParsedCategory(
        needs_clarification=True,
        clarification_question=f"This is missing. Please choose: {' or '.join(labels)}.",
    )
