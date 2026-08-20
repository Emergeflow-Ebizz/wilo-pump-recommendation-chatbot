"""Tank filling LLM-based parsing with rule-based fallback.

Primary: LLM mode - natural language understanding.
Fallback: Rule-based mode - when LLM unavailable, uses pattern matching.
"""
import json
import logging

from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import ParsedAnswer, ParsedCategory, Question
from app.use_cases.tank_filling import rules_based

logger = logging.getLogger(__name__)


# ===== LLM SYSTEM PROMPTS =====

PARSE_ANSWER_SYSTEM_PROMPT = (
    "You extract a numeric value from a user's free-text reply to a tank filling "
    "pump selection question. Return only what the user actually said - do not "
    "validate, do not decide whether to ask follow-up questions, just extract. "
    "If the user said a number with no unit, return the number in value and leave "
    "unit null. "
    "WHOLE NUMBER: If the question requires a whole number, reject any non-whole "
    "reply - set needs_clarification=true, value null, ask for a whole number. "
    "MINIMUM VALUE: Some questions have a stated minimum value. If a minimum is "
    "stated, reject any value below it - set needs_clarification=true, value null. "
    "SKIP: If optional and the user says skip/no/idk/don't know/etc, set "
    "skipped=true, leave value/unit/needs_clarification/clarification_question null. "
    "If NOT optional, never skip - ask for clarification instead."
)

PARSE_CATEGORY_SYSTEM_PROMPT = (
    "You determine which one of a fixed set of categories the user's free-text "
    "reply means, for a tank filling pump selection question. The valid categories "
    "are given to you exactly - you must return one of those exact strings (or null), "
    "never a synonym, paraphrase, or a category not in the list. Use natural-language "
    "understanding, not just literal keyword matching - e.g. if categories are "
    "'inside'/'outside' and user replies 'it's kept indoors' that means 'inside'; if "
    "'on the ground' that means 'outside'. "
    "If the question is marked optional and the user's reply indicates they don't "
    "have or don't want to choose - 'skip', 'not sure', 'no', 'don't know', or "
    "similar - set skipped to true and leave category/needs_clarification/"
    "clarification_question at their default. Never do this for a non-optional "
    "question - ask for clarification instead. "
    "If the reply genuinely doesn't map to any valid category, set "
    "needs_clarification to true, leave category null, and ask a short "
    "clarification_question naming the valid options."
)


# ===== SCHEMA BUILDERS =====

def _parse_answer_schema(allowed_units: list[str] | None) -> dict:
    """Build JSON schema for answer parsing."""
    return {
        "type": "object",
        "properties": {
            "value": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
            "redirect_key": {"type": ["string", "null"]},
            "gave_up": {"type": "boolean"},
            "suggested_value": {"type": ["number", "null"]},
            "additional_answers": {"type": "array", "items": {"type": "object"}},
            "edit_not_supported": {"type": "boolean"},
        },
        "required": [
            "value", "unit", "needs_clarification", "clarification_question",
            "skipped", "redirect_key", "gave_up", "suggested_value",
            "additional_answers", "edit_not_supported",
        ],
    }


def _parse_category_schema(valid_categories: list[str]) -> dict:
    """Build JSON schema for category parsing."""
    return {
        "type": "object",
        "properties": {
            "category": {"type": ["string", "null"], "enum": [*valid_categories, None]},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
        },
        "required": ["category", "needs_clarification", "clarification_question", "skipped"],
    }


# ===== PUBLIC API =====

def parse_answer(
    question: Question,
    user_text: str,
    previous_value: float | None = None,
    previous_unit: str | None = None,
    clarification_attempts: int = 0,
) -> ParsedAnswer:
    """Parse tank filling numeric question answer.

    Primary: LLM mode with natural language understanding.
    Fallback: Rule-based mode when LLM unavailable.

    If user says "yes/yeah/ok/confirm" with previous_value set, accept it immediately.
    """
    # Handle confirmation of previous value
    if previous_value is not None and user_text.lower().strip() in ("yes", "yeah", "ok", "okay", "confirm", "yes."):
        return ParsedAnswer(
            value=previous_value,
            unit=previous_unit,
            needs_clarification=False,
            confirmation_message=f"Got it: {previous_value} {previous_unit}" if previous_unit else f"Got it: {previous_value}",
        )

    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid units: {question.allowed_units!r}\n"
        f"Domain context: {question.domain_context or 'none provided'}\n"
        f"User's reply: {user_text!r}"
    )

    # Try LLM first
    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_answer_schema(question.allowed_units),
        )
        data = json.loads(raw)
        return ParsedAnswer(**data)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "tank_filling parse_answer: LLM extraction failed for question=%r, "
            "falling back to rule-based: %r",
            question.key, e,
        )
        # Fall back to rule-based mode
        return rules_based.parse_answer_rule_based(
            question, user_text, clarification_attempts, previous_value
        )


def parse_category(
    question: Question,
    user_text: str,
    valid_categories: list[str],
    clarification_attempts: int = 0,
) -> ParsedCategory:
    """Parse tank filling category question answer (inside_or_outside, horizontal_or_vertical).

    Primary: LLM mode with natural language understanding.
    Fallback: Rule-based mode when LLM unavailable.
    """
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid categories: {valid_categories!r}\n"
        f"User's reply: {user_text!r}"
    )

    # Try LLM first
    try:
        raw = llm_client.complete(
            PARSE_CATEGORY_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_category_schema(valid_categories),
        )
        data = json.loads(raw)

        # Add confirmation message if successful
        if not data.get("needs_clarification") and not data.get("skipped") and data.get("category"):
            data["confirmation_message"] = f"Got it: {rules_based.get_category_label(data['category'])}"

        return ParsedCategory(**data)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "tank_filling parse_category: LLM extraction failed, "
            "falling back to rule-based: %r",
            e,
        )
        # Fall back to rule-based mode
        return rules_based.parse_category_rule_based(
            question, user_text, valid_categories, clarification_attempts
        )
