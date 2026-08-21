"""Water transfer rule-based parsing - no LLM, pure pattern matching and keywords.

Used only when LLM is unavailable. Includes clarification with standard messages.
Validates: value extraction, unit matching, rounding, negative rejection, borewell size constraints.
NO unit conversion - strict matching only.
"""
import re
import logging
import math

from app.common.schemas import Question, ParsedAnswer, ParsedCategory
from app.use_cases.water_transfer.sheet_map import MAX_BOREWELL_SIZE, MIN_BOREWELL_SIZE

logger = logging.getLogger(__name__)


# ===== CATEGORY KEYWORDS (delivery_type only) =====

CATEGORY_KEYWORDS = {
    "ground_floor": ["ground floor", "ground-floor", "ground level", "groundfloor", "ground"],
    "overhead_tank": ["overhead tank", "overhead", "above", "terrace", "rooftop tank", "terrace tank", "rooftop"],
}

CATEGORY_LABELS = {
    "ground_floor": "Ground floor",
    "overhead_tank": "Overhead tank",
}


# ===== ROUNDING FUNCTIONS =====

def _round_borewell_size(value: float) -> float:
    """Round UP to next higher for borewell_size (2.5 → 3)."""
    return math.ceil(value)


def _round_well_depth(value: float) -> float:
    """Round UP to next higher for well_depth (2.5 → 3)."""
    return math.ceil(value)


def _round_motor_power_hp(value: float) -> float:
    """Round DOWN to smaller for motor_power_hp (2.5 → 2)."""
    return math.floor(value)


def _round_roof_tank_capacity(value: float) -> float:
    """Round DOWN to smaller for roof_tank_capacity (6.5 → 6, 7.5 → 7)."""
    return math.floor(value)


def _apply_rounding(value: float, question_key: str) -> float:
    """Apply question-specific rounding."""
    if question_key == "borewell_size":
        return _round_borewell_size(value)
    elif question_key == "well_depth":
        return _round_well_depth(value)
    elif question_key == "motor_power_hp":
        return _round_motor_power_hp(value)
    elif question_key == "roof_tank_capacity":
        return _round_roof_tank_capacity(value)
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


def _validate_borewell_size(value: float) -> tuple[bool, str | None]:
    """Validate borewell_size against MIN and MAX constraints.

    Returns: (is_valid, clarification_message)
    - If < MIN: reject with message
    - If > MAX: ask for confirmation
    - Otherwise: valid
    """
    if value < MIN_BOREWELL_SIZE:
        return False, f"No suitable pump is available for a borewell smaller than {MIN_BOREWELL_SIZE} inch."
    if value > MAX_BOREWELL_SIZE:
        return True, f"We only have up to {MAX_BOREWELL_SIZE} inch available. Would you like to proceed with the {MAX_BOREWELL_SIZE} inch model?"
    return True, None


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
    - borewell_size: value (4-10 inch / 100-250mm) + unit, round UP
    - well_depth: value + unit (ft/m), round UP
    - motor_power_hp: value, round DOWN - no unit needed
    - num_floors: whole number only, min 1
    - roof_tank_capacity: value (litres) - no unit needed

    Rules:
    - Reject negative values
    - For borewell_size and well_depth: round UP to next higher
    - For motor_power_hp: round DOWN to smaller
    - For num_floors: reject decimals and values < min_value
    - Accept previous_value + new_unit combination
    - NO unit conversion (strict matching only)
    """
    user_text = user_text.strip()
    if not user_text:
        return None

    # ===== NO UNITS REQUIRED (num_floors, roof_tank_capacity, motor_power_hp) =====
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

    # ===== WITH UNITS REQUIRED (borewell_size, well_depth) =====
    unit_pattern = "|".join(re.escape(unit) for unit in allowed_units)
    pattern = rf'^\s*([+-]?\d+(?:\.\d+)?)\s*({unit_pattern})\s*$'
    match = re.match(pattern, user_text, re.IGNORECASE)

    if not match:
        # Check if it's just a unit correction (no number, but valid unit + previous_value)
        cleaned = user_text.lower()
        for unit in allowed_units:
            if cleaned == unit or cleaned in unit or unit in cleaned:
                if previous_value is not None:
                    # Reject negative
                    if _reject_negative(previous_value):
                        return None
                    return {
                        "value": previous_value,
                        "unit": unit,
                        "needs_clarification": False,
                        "clarification_question": None,
                        "skipped": False,
                        "redirect_key": None,
                        "gave_up": False,
                    }
        return None

    value_str, unit_str = match.groups()
    value = float(value_str)
    unit = unit_str.lower()

    # Normalize unit to canonical form (case-insensitive match)
    matched_unit = None
    for allowed_unit in allowed_units:
        if unit == allowed_unit.lower():
            matched_unit = allowed_unit
            break

    if matched_unit is None:
        return None

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

    # Validate borewell_size constraints
    if question.key == "borewell_size":
        is_valid, clarification_msg = _validate_borewell_size(value)
        if not is_valid:
            return None  # Too small, reject
        if clarification_msg:
            # Too large, ask for confirmation
            return {
                "value": value,
                "unit": matched_unit,
                "needs_clarification": True,
                "clarification_question": clarification_msg,
                "skipped": False,
                "redirect_key": None,
                "gave_up": False,
            }

    return {
        "value": value,
        "unit": matched_unit,
        "needs_clarification": False,
        "clarification_question": None,
        "skipped": False,
        "redirect_key": None,
        "gave_up": False,
    }


# ===== CATEGORY PARSING (delivery_type: ground_floor vs overhead_tank) =====

def try_parse_category(user_text: str, valid_categories: list[str]) -> str | None:
    """Try to match user text to water transfer delivery_type using keywords only.

    Returns the matched category, or None if no match found or ambiguous.
    Rule-based mode: NO natural language understanding, keyword matching only.

    Valid categories: ground_floor, overhead_tank
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
    """Get human-readable label for water transfer delivery_type."""
    label = CATEGORY_LABELS.get(category)
    if label is None:
        logger.warning("water_transfer rules_based: no label for category %r", category)
        return category.replace("_", " ")
    return label


# ===== CLARIFICATION MESSAGE =====

def get_clarification_message(question_key: str) -> str:
    """Standard clarification message for rule-based mode."""
    field_names = {
        "borewell_size": "borewell size",
        "well_depth": "well depth",
        "motor_power_hp": "motor power",
        "num_floors": "number of floors",
        "roof_tank_capacity": "tank capacity",
        "delivery_type": "delivery type",
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

    If user says "yes/yeah/ok/confirm" with previous_value set, accept it immediately.
    """
    # Handle confirmation of previous value
    if previous_value is not None and user_text.lower().strip() in ("yes", "yeah", "ok", "okay", "confirm", "yes."):
        return ParsedAnswer(
            value=previous_value,
            needs_clarification=False,
            confirmation_message=f"Got it: {previous_value}",
        )

    parsed = try_parse_numeric(user_text, question.allowed_units, question, previous_value)

    if parsed is not None:
        if not parsed.get("needs_clarification") and not parsed.get("skipped") and parsed.get("value") is not None:
            parsed["confirmation_message"] = (
                f"Got it: {parsed['value']} {parsed['unit']}" if parsed.get("unit") else f"Got it: {parsed['value']}"
            )
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
