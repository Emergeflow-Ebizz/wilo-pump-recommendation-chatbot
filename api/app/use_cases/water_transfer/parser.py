"""Water transfer LLM-based parsing with rule-based fallback.

Primary: LLM mode - natural language understanding with unit conversion support.
Fallback: Rule-based mode - when LLM unavailable, uses pattern matching.
"""
import json
import logging

from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import ParsedAnswer, ParsedCategory, Question
from app.use_cases.water_transfer import rules_based
from app.use_cases.water_transfer.sheet_map import MAX_BOREWELL_SIZE, MIN_BOREWELL_SIZE

logger = logging.getLogger(__name__)

GIVE_UP_THRESHOLD = 2


# ===== LLM SYSTEM PROMPTS =====

PARSE_ANSWER_SYSTEM_PROMPT = (
    "You extract a numeric value and its unit from a user's free-text reply "
    "to a water transfer pump selection question. Return only what the user "
    "actually said - do not validate, do not decide whether to ask follow-up "
    "questions, just extract. "
    "For unit words: normalize the user's word to the exact matching string "
    "from the valid units list given to you. Only ask for clarification if "
    "it's genuinely ambiguous which valid unit (if any) they meant. "
    "UNIT CONVERSION: If user states a unit NOT in the valid units list but "
    "it's convertible (e.g., 52 cm when valid units are ft/m), convert and ask: "
    "'52 cm is 0.52 m, would you like to confirm 0.52 meter?' If user confirms "
    "yes, return the converted value in the valid unit. If user says no, ask "
    "them to restate in one of the valid units. "
    "If user's stated unit is a real, different unit that isn't a typo, do not "
    "compute the equivalent value yourself without asking first. "
    "Never perform unit conversion yourself without user confirmation. "
    "If the user said a number with no unit, return the number in value and "
    "leave unit null - the caller will decide what to ask next. "
    "If this question has NO valid units at all (valid units list is empty/null), "
    "it never takes a unit - extract only the number and always leave unit null, "
    "even if the user includes a unit-like word (e.g. 'hp', 'floors') in their reply; "
    "that word is not a real unit for this question and must be dropped silently. "
    "WHOLE NUMBER: If the question requires a whole number, reject any "
    "non-whole reply - set needs_clarification=true, value null, ask for a "
    "whole number. "
    "MINIMUM VALUE: Some questions have a stated minimum value. If a minimum "
    "is stated, reject any value below it - set needs_clarification=true, "
    "value/unit null - but a value equal to the stated minimum is always valid. "
    "If no minimum is stated, zero and negative numbers are always rejected "
    "for physical quantities. "
    "SKIP: If optional and the user says skip/no/idk/don't know/etc, set "
    "skipped=true, leave value/unit/needs_clarification/clarification_question null. "
    "If NOT optional, never skip - ask for clarification instead. "
    "REDIRECT: If the user's reply does NOT answer the current question at all, "
    "and instead clearly corrects a DIFFERENT question in this use case's own "
    "question list (e.g. current question is motor power but user says 'well "
    "depth is 50 meters'), set redirect_key to that question's key, put the "
    "corrected value/unit in value/unit, set needs_clarification=false, "
    "skipped=false. Only if you can determine both a concrete value AND its "
    "unit (when that question needs one) for the other question. Otherwise "
    "treat it as a clarification for the current question. "
    "ADDITIONAL ANSWERS: Different from REDIRECT - if the user's reply DOES "
    "answer the current question (value/unit filled normally) AND ALSO "
    "clearly states a concrete value (and unit, if needed) for one or more "
    "OTHER questions in this use case's question list, add an entry per extra "
    "question to additional_answers: {key, value, unit}. Only add an entry "
    "when the value is genuinely concrete and unambiguous for that specific "
    "other question - never guess or infer. Leave additional_answers as an "
    "empty array if nothing else was volunteered. "
    "EDIT NOT SUPPORTED: If the user's reply clearly tries to change or correct "
    "an answer to a question that is NEITHER the current question NOR listed "
    "in the other questions given to you - most often one of the "
    "already-answered questions listed separately below (if any) - this "
    "system has no way to go back and edit an answer once the conversation "
    "has moved past it. Set edit_not_supported=true, value/unit null, "
    "needs_clarification=false, skipped=false, redirect_key null. Do not use "
    "REDIRECT for this case. If the reply references something that matches "
    "neither the current question, the other-questions list, NOR any "
    "already-answered question given to you, it is not an edit attempt - "
    "treat it as AMBIGUOUS instead. "
    "AMBIGUOUS: A typo, phonetic spelling, or partial word is not by itself "
    "ambiguous - if only one number or unit is a plausible reading of it, "
    "extract that reading with confidence. Reserve needs_clarification=true "
    "(value/unit null, short clarification_question) for replies where more "
    "than one reading is genuinely plausible. When needs_clarification=true "
    "and exactly one reading is nonetheless the most likely of the plausible "
    "ones, put that reading in suggested_value (value itself still stays null). "
    "redirect_key, skipped, needs_clarification, and edit_not_supported are "
    "mutually exclusive."
)

PARSE_CATEGORY_SYSTEM_PROMPT = (
    "You determine which one of a fixed set of categories the user's "
    "free-text reply means, for a water transfer delivery type question. "
    "The valid categories are given to you exactly - you must return one of "
    "those exact strings (or null), never a synonym, paraphrase, or a category "
    "not in the list. Use natural-language understanding, not just literal "
    "keyword matching - e.g. if the categories are 'ground_floor'/'overhead_tank' "
    "and the user replies 'it's on the roof' or 'elevated storage', that means "
    "'overhead_tank'; if they reply 'at ground level' or 'on the ground', that "
    "means 'ground_floor'. "
    "If the question is marked optional and the user's reply indicates they "
    "don't have or don't want to choose - 'skip', 'not sure', 'no', 'don't know', "
    "or similar - set skipped to true and leave category/needs_clarification/"
    "clarification_question at their default. Never do this for a non-optional "
    "question - ask for clarification instead. "
    "If the reply genuinely doesn't map to any valid category, set "
    "needs_clarification to true, leave category null, and ask a short "
    "clarification_question naming the valid options - do not guess a category "
    "just to fill the field."
)


# ===== SCHEMA BUILDERS =====

def _parse_answer_schema(allowed_units: list[str] | None, other_questions: list[Question] = ()) -> dict:
    """Build JSON schema for answer parsing.

    redirect_key is constrained to the exact keys of the other questions in
    this use case's sequence, so the LLM can only name a question that
    actually exists (see REDIRECT in PARSE_ANSWER_SYSTEM_PROMPT).
    """
    other_question_keys = [q.key for q in other_questions]
    redirect_schema = {"type": ["string", "null"]}
    if other_question_keys:
        redirect_schema["enum"] = [*other_question_keys, None]

    additional_answer_key_schema = {"type": "string"}
    if other_question_keys:
        additional_answer_key_schema["enum"] = other_question_keys

    return {
        "type": "object",
        "properties": {
            "value": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
            "redirect_key": redirect_schema,
            "gave_up": {"type": "boolean"},
            "suggested_value": {"type": ["number", "null"]},
            "additional_answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": additional_answer_key_schema,
                        "value": {"type": "number"},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["key", "value", "unit"],
                },
            },
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


# ===== VALIDATION =====

def _validate_borewell_size_llm(value: float) -> tuple[bool, str | None]:
    """Validate borewell_size against MIN and MAX constraints for LLM mode.

    Returns: (should_ask_clarification, clarification_message)
    """
    if value < MIN_BOREWELL_SIZE:
        return False, f"No suitable pump is available for a borewell smaller than {MIN_BOREWELL_SIZE} inch."
    if value > MAX_BOREWELL_SIZE:
        return True, f"We only have up to {MAX_BOREWELL_SIZE} inch available. Would you like to proceed with the {MAX_BOREWELL_SIZE} inch model?"
    return False, None


def _validate_additional_answers(
    raw_entries: list[dict], other_questions: list[Question], current_question_key: str
) -> list[dict]:
    """Apply the same defensive checks used for the primary answer to each
    additional_answers entry, dropping anything that doesn't hold up.

    An entry that fails any check is dropped silently - the caller will
    simply ask that question normally later, rather than accepting a shaky
    value volunteered by the LLM.
    """
    validated = []
    for entry in raw_entries:
        key = entry.get("key")
        if not key or key == current_question_key:
            continue
        target_question = next((q for q in other_questions if q.key == key), None)
        if target_question is None:
            continue
        value = entry.get("value")
        if value is None:
            continue
        unit = entry.get("unit")
        if target_question.allowed_units and len(target_question.allowed_units) == 1:
            unit = target_question.allowed_units[0]
        elif not target_question.allowed_units:
            unit = None
        if target_question.requires_stated_unit and unit is None:
            continue
        if target_question.requires_integer:
            if value != int(value):
                continue
            if target_question.min_value is not None and value < target_question.min_value:
                continue
        elif target_question.min_value is not None:
            if value < target_question.min_value:
                continue
        elif value <= 0:
            continue
        validated.append({"key": key, "value": value, "unit": unit})
    return validated


def _generate_clarification_question(
    question: Question,
    reason: str,
    attempts: int,
    extracted_value: float | None = None,
    extracted_unit: str | None = None,
    user_text: str | None = None,
    suggested_value: float | None = None,
) -> str:
    """Generate a natural clarification question, grounded in this
    question's own domain context and the user's actual reply, instead of
    reusing whatever (possibly generic) wording the primary extraction call
    produced.

    Falls back to a plain templated sentence only if the LLM itself is
    unreachable.
    """
    subject = question.key.replace("_", " ")
    units_str = ", ".join(question.allowed_units) if question.allowed_units else "the available units"
    user_reply_line = f"The user's actual reply just now: {user_text!r}. " if user_text else ""
    suggested_value_line = (
        f"The system already identified {suggested_value!r} as the single most "
        f"likely reading of that reply, still unconfirmed. Ask the user directly "
        f"whether that's correct (a 'did you mean {suggested_value!r}?' style "
        f"question) rather than a generic re-ask. "
        if suggested_value is not None
        else ""
    )

    prompt = (
        f"User is being asked about: {subject}. Question as shown to the user: "
        f"{question.prompt!r}. "
        f"Domain context - facts about THIS system, e.g. constraints, ranges, "
        f"why the question matters: {question.domain_context or 'none provided.'} "
        f"Valid units: {units_str}. "
        f"Reason clarification is needed: {reason}. "
        f"What was extracted so far: value={extracted_value!r}, unit={extracted_unit!r}. "
        f"{user_reply_line}"
        f"{suggested_value_line}"
        f"They've been asked {attempts + 1} time(s) about this question. "
        f"If the user's reply shows they don't know HOW to find or determine this "
        f"value, rather than just being noncommittal, fold in ONE short practical "
        f"pointer. Otherwise just ask again in different words. "
        f"If the reason is missing_unit and the user's reply stated a unit that "
        f"is NOT one of the valid units listed above - don't ask a vague 'did you "
        f"mean X or Y' question and don't do the conversion yourself. State plainly "
        f"which units this question accepts and ask them to restate the number in "
        f"one of those. "
        f"ONE sentence, 15 words max, no preamble. Output only that one sentence, "
        f"nothing else."
    )

    try:
        response = llm_client.complete(
            "Generate ONE short chat-message sentence, 15 words maximum, for a "
            "pump-selection follow-up question. Hard rules: (1) exactly one "
            "sentence, no more than 15 words, no preamble or empathy opener - go "
            "straight to the point. (2) Never state any specific number, size, "
            "range, or 'typical'/'most common' value for what the user is being "
            "asked, even a plausible-sounding one from general knowledge, unless "
            "that exact number appears in the domain context given in the user "
            "message. (3) At most one practical pointer folded into that same "
            "single sentence - never a list of options.",
            prompt,
            temperature=1.0,
        ).strip()
        response = "\n".join(line.strip() for line in response.split("\n") if line.strip() and not line.startswith("#"))
        return response.strip() if response else REASON_FALLBACKS[reason].format(subject=subject)
    except LLMUnavailableError:
        return REASON_FALLBACKS[reason].format(subject=subject)


REASON_FALLBACKS: dict[str, str] = {
    "missing_unit": "Please provide {subject} along with its unit.",
    "missing_value": "Please provide {subject}.",
    "non_integer": "{subject} must be a whole number - could you give a whole number?",
    "non_positive": "{subject} must be greater than zero - could you give a valid value?",
    "generic": "Could you clarify your answer for {subject}?",
}


# ===== PUBLIC API =====

def parse_answer(
    question: Question,
    user_text: str,
    previous_value: float | None = None,
    previous_unit: str | None = None,
    pending_suggestion: float | None = None,
    other_questions: list[Question] = (),
    clarification_attempts: int = 0,
    locked_in_answers: dict[str, str] | None = None,
) -> ParsedAnswer:
    """Parse water transfer numeric question answer.

    Primary: LLM mode with natural language understanding and unit conversion.
    Fallback: Rule-based mode when LLM unavailable.

    If user says "yes/yeah/ok/confirm" with previous_value set, accept it immediately.

    other_questions/locked_in_answers/pending_suggestion mirror the generic
    llm_parser.parse_answer parameters of the same name - see there for full
    semantics (redirect detection, edit-not-supported detection, and
    carrying forward an unconfirmed ambiguous reading).
    """
    # Handle confirmation of previous value
    if previous_value is not None and user_text.lower().strip() in ("yes", "yeah", "ok", "okay", "confirm", "yes."):
        return ParsedAnswer(
            value=previous_value,
            unit=previous_unit,
            needs_clarification=False,
            confirmation_message=f"Got it: {previous_value} {previous_unit}" if previous_unit else f"Got it: {previous_value}",
        )

    other_questions_line = (
        "This use case's OTHER questions, in case the reply corrects one of "
        "these instead of answering the current question, or volunteers an "
        f"answer for one of them too - each is (key, prompt): "
        f"{[(q.key, q.prompt) for q in other_questions]!r}\n"
        if other_questions
        else ""
    )
    locked_in_answers_line = (
        "Already-answered questions from earlier in this conversation that "
        "are OUTSIDE this use case's question list and CANNOT be edited or "
        "redirected to (see EDIT NOT SUPPORTED) - each is (question, chosen "
        f"answer): {list(locked_in_answers.items())!r}.\n"
        if locked_in_answers
        else ""
    )
    pending_suggestion_line = (
        f"A pending, UNCONFIRMED suggestion from last turn for this question: {pending_suggestion!r}. "
        "Only set value to it (and needs_clarification=false) if the user's CURRENT "
        "reply is a clear affirmative response to it (e.g. 'yes', 'correct'). Simply "
        "repeating the same unclear word/spelling again is NOT confirmation.\n"
        if pending_suggestion is not None
        else ""
    )
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid units: {question.allowed_units!r}\n"
        f"Domain context: {question.domain_context or 'none provided'}\n"
        f"{other_questions_line}"
        f"{locked_in_answers_line}"
        f"{pending_suggestion_line}"
        f"User's reply: {user_text!r}"
    )

    # Try LLM first
    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_answer_schema(question.allowed_units, other_questions),
        )
        data = json.loads(raw)

        # Point 2: "skipped" is only a valid outcome for optional questions -
        # don't trust the model to honor that on its own.
        if not question.optional:
            data["skipped"] = False

        # Point 3: a question with no allowed_units never takes a unit - drop
        # anything the model put there (e.g. user said "4 hp", "6 floorsss").
        if not question.allowed_units:
            data["unit"] = None

        if data.get("edit_not_supported"):
            try:
                message = llm_client.complete(
                    "Generate ONE short, friendly chat-message sentence, 15 words "
                    "maximum, no preamble. Tell the user this system cannot go back "
                    "and edit an earlier answer once the conversation has moved on, "
                    "and that they should restart/refresh to choose differently. "
                    "Output only that one sentence, nothing else.",
                    f"The user just tried to change an earlier answer while being "
                    f"asked about {question.key.replace('_', ' ')}. Their reply: "
                    f"{user_text!r}.",
                    temperature=1.0,
                ).strip()
            except LLMUnavailableError:
                message = (
                    "Sorry, I can't go back and change an earlier answer - "
                    "please refresh and start over to choose differently."
                )
            return ParsedAnswer(edit_not_supported=True, clarification_question=message)

        # Validate borewell_size constraints
        if question.key == "borewell_size" and data.get("value") is not None and not data.get("needs_clarification"):
            ask_clarification, clarification_msg = _validate_borewell_size_llm(data["value"])
            if clarification_msg:
                if ask_clarification:
                    # Too large, ask for confirmation
                    data["needs_clarification"] = True
                    data["clarification_question"] = clarification_msg
                else:
                    # Too small, reject completely
                    return ParsedAnswer(
                        needs_clarification=True,
                        clarification_question=clarification_msg,
                    )

        # Point 9: defensive re-check - the LLM is told the negative/min/integer
        # rules in the prompt, but nothing in the schema enforces them, so an
        # occasional LLM response can still violate them. Catch it here before
        # a bad value reaches the caller/rules.py.
        target_key = data.get("redirect_key") or question.key
        target_question = next((q for q in other_questions if q.key == target_key), question)
        rejected_value = data.get("value")
        if rejected_value is not None:
            should_reject = False
            if target_question.requires_integer:
                if rejected_value != int(rejected_value):
                    should_reject = True
                elif target_question.min_value is not None and rejected_value < target_question.min_value:
                    should_reject = True
            elif target_question.min_value is not None:
                should_reject = rejected_value < target_question.min_value
            else:
                should_reject = rejected_value <= 0

            if should_reject:
                data["value"] = None
                data["unit"] = None
                data["redirect_key"] = None
                data["skipped"] = False
                data["needs_clarification"] = True
                reason = "non_integer" if target_question.requires_integer and rejected_value != int(rejected_value) else "non_positive"
                data["clarification_question"] = _generate_clarification_question(
                    target_question, reason, clarification_attempts, rejected_value, user_text=user_text
                )
                data["gave_up"] = False

        # Point 8: give-up threshold - if required info is still missing at
        # attempt GIVE_UP_THRESHOLD or beyond, stop and give up instead of
        # asking again.
        missing_required_info = not question.optional and (
            data.get("value") is None or (question.requires_stated_unit and data.get("unit") is None)
        )
        not_redirect_or_skip = not data.get("redirect_key") and not data.get("skipped")

        if not_redirect_or_skip and missing_required_info and clarification_attempts >= GIVE_UP_THRESHOLD:
            data["value"] = None
            data["unit"] = None
            data["needs_clarification"] = False
            data["gave_up"] = True
            allowed_units_note = (
                f" The valid units for this question are: {', '.join(question.allowed_units)}."
                if question.allowed_units
                else ""
            )
            try:
                data["clarification_question"] = llm_client.complete(
                    "Generate ONE short, friendly chat-message sentence, 15 words "
                    "maximum, no preamble. Never state a specific number or 'typical' "
                    "value from general knowledge - only use facts given in the user "
                    "message. If valid units are named in the user message, state them "
                    "plainly. Output only that one sentence, nothing else.",
                    f"The user couldn't provide the {question.key.replace('_', ' ')} information after "
                    f"being asked twice.{allowed_units_note} Domain context: {question.domain_context or 'none provided.'} "
                    "Generate a brief, friendly message saying we cannot recommend a pump model without "
                    "this information.",
                    temperature=1.0,
                ).strip()
            except LLMUnavailableError:
                data["clarification_question"] = (
                    f"We cannot recommend you a model without this in {' or '.join(question.allowed_units)}."
                    if question.allowed_units
                    else "We cannot recommend you a model because of missing information."
                )
        elif not_redirect_or_skip and missing_required_info:
            # Point 4: generate a dynamic, domain-grounded clarification
            # question instead of trusting the primary call's own wording.
            data["needs_clarification"] = True
            reason = "missing_unit" if data.get("value") is not None else "missing_value"
            data["clarification_question"] = _generate_clarification_question(
                question,
                reason,
                clarification_attempts,
                data.get("value"),
                data.get("unit"),
                user_text=user_text,
                suggested_value=data.get("suggested_value"),
            )

        # A malformed redirect (no concrete value) is not usable - fall back
        # to asking for clarification on the current question instead.
        if data.get("redirect_key") and data.get("value") is None:
            data["redirect_key"] = None
            data["needs_clarification"] = True
            data["skipped"] = False
            data["clarification_question"] = _generate_clarification_question(
                question, "generic", clarification_attempts, user_text=user_text
            )
        elif data.get("redirect_key"):
            data["needs_clarification"] = False
            data["skipped"] = False

        data.setdefault("gave_up", False)
        data["additional_answers"] = _validate_additional_answers(
            data.get("additional_answers") or [], other_questions, question.key
        )

        if (
            not data.get("needs_clarification")
            and not data.get("skipped")
            and not data.get("gave_up")
            and data.get("value") is not None
        ):
            data["confirmation_message"] = (
                f"Got it: {data['value']} {data['unit']}" if data.get("unit") else f"Got it: {data['value']}"
            )

        return ParsedAnswer(**data)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "water_transfer parse_answer: LLM extraction failed for question=%r, "
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
    """Parse water transfer category question answer (delivery_type).

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
            "water_transfer parse_category: LLM extraction failed, "
            "falling back to rule-based: %r",
            e,
        )
        # Fall back to rule-based mode
        return rules_based.parse_category_rule_based(
            question, user_text, valid_categories, clarification_attempts
        )
