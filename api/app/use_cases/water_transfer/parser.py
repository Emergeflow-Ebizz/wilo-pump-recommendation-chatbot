"""Water transfer LLM-based parsing with rule-based fallback.

Primary: LLM mode - natural language understanding with unit conversion support.
Fallback: Rule-based mode - when LLM unavailable, uses pattern matching.

Design: the LLM classifies every reply into exactly ONE intent (see INTENTS
below), rather than returning a pile of independent booleans the caller has
to reconcile after the fact. Each intent has its own small handler function
with only the fields that intent needs - adding a new intent means adding
one enum value, one prompt line, and one handler, not threading a new flag
through every existing branch.
"""
import json
import logging

from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import ParsedAnswer, ParsedCategory, Question
from app.use_cases.water_transfer import rules_based
from app.use_cases.water_transfer.rules_based import _apply_rounding
from app.use_cases.water_transfer.sheet_map import MAX_BOREWELL_SIZE, MIN_BOREWELL_SIZE

logger = logging.getLogger(__name__)

GIVE_UP_THRESHOLD = 2

# Below this, a reply is never auto-accepted even if the model picked a
# confident-sounding intent - it goes through the "did you mean X?" tier
# instead. At or above it, a reply is accepted directly even if the model
# hedged. This is a code-level gate, not just prompt wording, precisely
# because relying on the model's own intent choice alone was inconsistent
# call to call for borderline replies (see the "g" vs "G" case this replaces).
CONFIDENCE_THRESHOLD = 50

OUT_OF_SCOPE_MESSAGE = (
    "I can only help with questions about selecting a pump for your water "
    "transfer setup - could you answer the question above?"
)
EDIT_NOT_SUPPORTED_MESSAGE = (
    "Sorry, I can't go back and change an earlier answer - "
    "please refresh and start over to choose differently."
)

# Every value the LLM may put in "intent". One label, one meaning, no
# combination of booleans to reconcile.
INTENTS = (
    "answer",        # a clean value (+ unit, if this question needs one)
    "ambiguous",     # more than one plausible reading; suggested_value may hold the best guess
    "redirect",      # answers a DIFFERENT question in this use case instead
    "additional",    # answers the current question AND volunteers others
    "edit_attempt",  # tries to change an already-answered question outside this use case
    "doesnt_know",   # explicit "I don't know" - no number attempted at all
    "skip",          # optional question, user declined to answer
    "out_of_scope",  # unrelated to this question or use case entirely
)


# ===== LLM SYSTEM PROMPT =====

PARSE_ANSWER_SYSTEM_PROMPT = (
    "You classify a user's free-text reply to ONE water transfer pump "
    "selection question into exactly one intent, then extract only the "
    "fields that intent needs. Never validate or decide follow-up wording "
    "yourself beyond what's listed per intent - that belongs to the caller. "
    "CONFIDENCE: for intents 'answer', 'ambiguous', and 'redirect', also give "
    "a confidence score from 0 to 100 for how sure you are the extracted "
    "value (and unit, if any) is exactly what the user meant - 100 means "
    "completely certain (a clean, unambiguous number stated plainly), 0 means "
    "pure guesswork. A typo or phonetic spelling that still has only one "
    "plausible reading should score high (80+); a real toss-up between two "
    "or more readings should score low (below 50). This score is the primary "
    "signal the caller uses to decide whether to accept the value directly "
    "or ask the user to confirm it first - pick it carefully and "
    "independently of which intent you chose, since even an 'answer' can "
    "still be a low-confidence guess. Leave confidence null for every other "
    "intent.\n"
    "Pick exactly one of these intents:\n"
    "answer - the reply gives a usable value for the CURRENT question (and "
    "its unit, if the question has valid units and the user stated one). "
    "If the question has no valid units at all, never attach a unit, even "
    "if the user says a unit-like word (e.g. 'hp', 'floors') - that word is "
    "not real for this question. If the user gave a number but no unit and "
    "this question needs one, use 'ambiguous' instead, not 'answer'.\n"
    "ambiguous - genuinely more than one plausible reading of the number or "
    "unit (or a number given with no unit for a question that needs one). "
    "When exactly one reading is nonetheless the most likely, put it in "
    "suggested_value.\n"
    "redirect - the reply does not answer the current question at all, and "
    "instead clearly gives a value for a DIFFERENT question in this use "
    "case's own question list (e.g. current question is motor power but "
    "user says 'well depth is 50 meters'). Only use this when you have both "
    "a concrete value AND its unit (if that question needs one); otherwise "
    "treat the reply as ambiguous or out_of_scope instead.\n"
    "additional - the reply DOES answer the current question normally AND "
    "ALSO clearly states a concrete value for one or more OTHER questions in "
    "this use case's list. Only add an entry when the value is genuinely "
    "concrete and unambiguous for that specific other question - never "
    "guess or infer.\n"
    "edit_attempt - the reply clearly tries to change an answer to a "
    "question that is NEITHER the current question NOR in this use case's "
    "own question list - most often one of the already-answered questions "
    "listed separately below. This system cannot go back and edit a past "
    "answer. If the reply references something that matches none of those, "
    "it is not an edit attempt - use out_of_scope instead.\n"
    "doesnt_know - the question is NOT optional and the reply is a genuine "
    "'I don't know'/'idk'/'no idea'/'not sure how to find this', with no "
    "number and no attempted number anywhere in it.\n"
    "skip - the question IS optional and the reply declines to answer "
    "(skip/no/idk/don't know/etc). Never use this for a non-optional "
    "question - use doesnt_know or ambiguous instead.\n"
    "out_of_scope - the reply is unrelated to this question and to every "
    "other question/answer given to you - a different topic entirely, small "
    "talk, a complaint, or a question of its own that isn't about the pump "
    "selection process itself.\n"
    "PREVIOUS VALUE: if a previously confirmed value/unit is given to you "
    "for this question and the current reply states only a unit (no number) "
    "or only a number (no unit), combine it with that previous value/unit "
    "and use 'answer' - do not use 'ambiguous' just because this one reply "
    "alone looks incomplete. Keep carrying the previous value/unit forward "
    "unless the current reply states a new, different number, in which case "
    "the new number wins outright. If the previous value has no unit "
    "recorded (still null), never invent one just because the reply "
    "confirms the number - unit stays null until the user actually states it.\n"
    "UNIT CONVERSION: if the user states a unit that is a real unit but not "
    "in the valid units list (e.g. cm when valid units are ft/m), use "
    "'ambiguous' and ask them to restate in one of the valid units yourself "
    "- never compute the equivalent value.\n"
    "MINIMUM VALUE / WHOLE NUMBER: if this question has a stated minimum or "
    "requires a whole number and the reply's value violates it, use "
    "'ambiguous' rather than 'answer' - the caller re-validates this "
    "regardless, but do not present a violating value as a clean answer."
)


# ===== SCHEMA BUILDER =====

def _parse_answer_schema(other_questions: list[Question] = ()) -> dict:
    """Build the JSON schema for answer parsing.

    All intent-specific fields are present regardless of which intent is
    chosen (JSON schema has no clean "fields depend on this enum" shape),
    but the handler for each intent only ever reads the fields relevant to
    it - see _INTENT_HANDLERS.
    """
    other_question_keys = [q.key for q in other_questions]
    redirect_key_schema = {"type": ["string", "null"]}
    if other_question_keys:
        redirect_key_schema["enum"] = [*other_question_keys, None]

    additional_key_schema = {"type": "string"}
    if other_question_keys:
        additional_key_schema["enum"] = other_question_keys

    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "value": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
            "suggested_value": {"type": ["number", "null"]},
            "redirect_key": redirect_key_schema,
            "additional_answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": additional_key_schema,
                        "value": {"type": "number"},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["key", "value", "unit"],
                },
            },
        },
        "required": [
            "intent", "value", "unit", "confidence", "suggested_value",
            "redirect_key", "additional_answers",
        ],
    }


# ===== SHARED HELPERS =====

def _validate_additional_answers(
    raw_entries: list[dict], other_questions: list[Question], current_question_key: str
) -> list[dict]:
    """Apply the same value/unit checks used for the primary answer to each
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
        if not _value_within_bounds(value, target_question):
            continue
        value = _display_value(_apply_rounding(value, target_question.key))
        validated.append({"key": key, "value": value, "unit": unit})
    return validated


def _value_within_bounds(value: float, question: Question) -> bool:
    """A single place for the negative/minimum/whole-number floor every
    question value must clear, regardless of which intent produced it.
    """
    if question.requires_integer:
        if value != int(value):
            return False
        if question.min_value is not None and value < question.min_value:
            return False
        return True
    if question.min_value is not None:
        return value >= question.min_value
    return value > 0


def _display_value(value: float) -> float | int:
    """Every water_transfer numeric field is logically whole - rounded per
    question via _apply_rounding - so display as int (6, not 6.0) whenever
    the value has no fractional part left.
    """
    return int(value) if value == int(value) else value


def _confirmation_message(value: float, unit: str | None) -> str:
    value = _display_value(value)
    return f"Got it: {value} {unit}" if unit else f"Got it: {value}"


def _clarification_text(prompt: str, user_message: str) -> str:
    """Call the LLM for one short chat-message sentence; on failure, use a
    plain fallback derived from the caller-supplied fallback text baked into
    user_message's caller instead of a second LLM round-trip.
    """
    return llm_client.complete(prompt, user_message, temperature=1.0).strip()


def _give_up_message(question: Question, attempted_twice: bool) -> str:
    """The "cannot recommend without this" message shown when we stop
    asking for this question's value - either the user couldn't provide it
    after GIVE_UP_THRESHOLD attempts, or they said outright they don't know it.
    """
    allowed_units_note = (
        f" The valid units for this question are: {', '.join(question.allowed_units)}."
        if question.allowed_units
        else ""
    )
    reason_note = (
        "couldn't provide this information after being asked twice"
        if attempted_twice
        else "said they don't know this information"
    )
    try:
        return _clarification_text(
            "Generate ONE short, friendly chat-message sentence, 15 words "
            "maximum, no preamble. Never state a specific number or 'typical' "
            "value from general knowledge - only use facts given in the user "
            "message. If valid units are named in the user message, state "
            "them plainly. Output only that one sentence, nothing else.",
            f"The user {reason_note} for {question.key.replace('_', ' ')}."
            f"{allowed_units_note} Domain context: {question.domain_context or 'none provided.'} "
            "Generate a brief, friendly message saying we cannot recommend a "
            "pump model without this information.",
        )
    except LLMUnavailableError:
        return (
            f"We cannot recommend you a model without this in {' or '.join(question.allowed_units)}."
            if question.allowed_units
            else "We cannot recommend you a model because of missing information."
        )


def _generate_clarification_question(
    question: Question,
    reason: str,
    attempts: int,
    extracted_value: float | None = None,
    user_text: str | None = None,
    suggested_value: float | None = None,
) -> str:
    """A natural clarification question, grounded in this question's own
    domain context and the user's actual reply.

    Falls back to a plain templated sentence only if the LLM itself is
    unreachable.
    """
    subject = question.key.replace("_", " ")
    units_str = ", ".join(question.allowed_units) if question.allowed_units else "the available units"
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
        f"Domain context: {question.domain_context or 'none provided.'} "
        f"Valid units: {units_str}. "
        f"Reason clarification is needed: {reason}. "
        f"What was extracted so far: value={extracted_value!r}. "
        f"The user's actual reply just now: {user_text!r}. "
        f"{suggested_value_line}"
        f"They've been asked {attempts + 1} time(s) about this question. "
        f"If the user's reply shows they don't know HOW to find or determine "
        f"this value, fold in ONE short practical pointer. Otherwise just ask "
        f"again in different words. "
        f"If the reason is 'unit_not_valid', state plainly which units this "
        f"question accepts and ask them to restate the number in one of those "
        f"- do not do the conversion yourself. "
        f"ONE sentence, 15 words max, no preamble. Output only that one "
        f"sentence, nothing else."
    )
    try:
        response = _clarification_text(
            "Generate ONE short chat-message sentence, 15 words maximum, for a "
            "pump-selection follow-up question. Hard rules: (1) exactly one "
            "sentence, no more than 15 words, no preamble or empathy opener. "
            "(2) Never state any specific number, size, range, or "
            "'typical'/'most common' value for what the user is being asked, "
            "unless that exact number appears in the domain context given in "
            "the user message. (3) At most one practical pointer folded into "
            "that same single sentence - never a list of options.",
            prompt,
        )
        return response if response else REASON_FALLBACKS[reason].format(subject=subject)
    except LLMUnavailableError:
        return REASON_FALLBACKS[reason].format(subject=subject)


REASON_FALLBACKS: dict[str, str] = {
    "ambiguous": "Could you clarify your answer for {subject}?",
    "unit_not_valid": "Please restate {subject} using one of the valid units.",
}


def _validate_borewell_size(value: float) -> tuple[bool, str | None]:
    """Validate borewell_size against MIN and MAX constraints.

    Returns: (should_ask_confirmation, message). Caller treats a truthy
    message + should_ask_confirmation=False as an outright rejection.
    """
    if value < MIN_BOREWELL_SIZE:
        return False, f"No suitable pump is available for a borewell smaller than {MIN_BOREWELL_SIZE} inch."
    if value > MAX_BOREWELL_SIZE:
        return True, f"We only have up to {MAX_BOREWELL_SIZE} inch available. Would you like to proceed with the {MAX_BOREWELL_SIZE} inch model?"
    return False, None


# ===== INTENT HANDLERS =====
# Each handler takes (question, data, ctx) and returns a ParsedAnswer, or
# None to signal "fall through to the next handling step" (only 'answer'
# does this, since a clean value still needs the borewell/bounds checks).

class _Ctx:
    __slots__ = (
        "user_text", "previous_value", "previous_unit", "pending_suggestion",
        "clarification_attempts", "other_questions",
    )

    def __init__(self, user_text, previous_value, previous_unit, pending_suggestion, clarification_attempts, other_questions):
        self.user_text = user_text
        self.previous_value = previous_value
        self.previous_unit = previous_unit
        self.pending_suggestion = pending_suggestion
        self.clarification_attempts = clarification_attempts
        self.other_questions = other_questions


def _handle_doesnt_know(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer:
    if question.optional:
        return ParsedAnswer(skipped=True)
    return ParsedAnswer(gave_up=True, clarification_question=_give_up_message(question, attempted_twice=False))


def _handle_skip(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer:
    if not question.optional:
        # The model mis-picked 'skip' for a required question - re-run as doesnt_know.
        return _handle_doesnt_know(question, data, ctx)
    return ParsedAnswer(skipped=True)


def _handle_out_of_scope(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer:
    return ParsedAnswer(needs_clarification=True, clarification_question=OUT_OF_SCOPE_MESSAGE)


def _handle_edit_attempt(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer:
    return ParsedAnswer(edit_not_supported=True, clarification_question=EDIT_NOT_SUPPORTED_MESSAGE)


def _handle_ambiguous(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer:
    suggested_value = data.get("suggested_value")
    known_number = data.get("value") if data.get("value") is not None else suggested_value
    reason = "unit_not_valid" if known_number is not None and question.allowed_units else "ambiguous"
    question_text = _generate_clarification_question(
        question, reason, ctx.clarification_attempts, known_number,
        user_text=ctx.user_text, suggested_value=suggested_value,
    )
    return ParsedAnswer(needs_clarification=True, clarification_question=question_text, suggested_value=suggested_value)


def _handle_redirect(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer | None:
    redirect_key = data.get("redirect_key")
    target = next((q for q in ctx.other_questions if q.key == redirect_key), None)
    value = data.get("value")
    if target is None or value is None or not _value_within_bounds(value, target):
        # Not a usable redirect - treat as an ambiguous reply to the current question.
        return _handle_ambiguous(question, {**data, "value": None, "suggested_value": None}, ctx)
    value = _apply_rounding(value, target.key)
    unit = data.get("unit")
    if target.allowed_units and len(target.allowed_units) == 1:
        unit = target.allowed_units[0]
    return ParsedAnswer(
        value=_display_value(value), unit=unit, redirect_key=redirect_key,
        confirmation_message=_confirmation_message(value, unit),
    )


def _handle_additional(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer | None:
    # The primary value still goes through the normal 'answer' path; only
    # the extra entries are specific to this intent.
    result = _handle_answer(question, data, ctx)
    if result is None or result.needs_clarification or result.gave_up:
        return result
    result.additional_answers = _validate_additional_answers(
        data.get("additional_answers") or [], ctx.other_questions, question.key
    )
    return result


def _handle_answer(question: Question, data: dict, ctx: _Ctx) -> ParsedAnswer | None:
    value = data.get("value")
    unit = data.get("unit")

    if not question.allowed_units:
        unit = None
    elif value is not None and unit is None and previous_unit_applies(ctx, value):
        unit = ctx.previous_unit
    elif (
        value is not None
        and unit is not None
        and _unit_was_never_stated(ctx, value)
        and ctx.user_text.strip() not in (question.allowed_units or [])
    ):
        # The number matches a previously seen value/suggestion that never
        # had a confirmed unit - the model attached one anyway (e.g.
        # confirming "yes" to a bare number it earlier guessed, whether that
        # number came from previous_value or an unconfirmed pending_suggestion).
        # That unit was never actually stated, so drop it and ask for it
        # explicitly instead of trusting a guess.
        unit = None

    if value is None and ctx.previous_value is not None:
        value = ctx.previous_value

    missing_unit = question.requires_stated_unit and unit is None
    if value is None or missing_unit:
        # When the number itself is known and only the unit is missing, carry
        # it forward as suggested_value so the caller can send it back as
        # pending_suggestion/previous_value - the user only needs to state
        # the unit next, not repeat the number too.
        ambiguous_data = {**data, "value": None}
        if missing_unit and value is not None:
            ambiguous_data["suggested_value"] = value
        return _handle_ambiguous(question, ambiguous_data, ctx)

    if not _value_within_bounds(value, question):
        reason = "ambiguous"
        question_text = _generate_clarification_question(
            question, reason, ctx.clarification_attempts, value, user_text=ctx.user_text,
        )
        return ParsedAnswer(needs_clarification=True, clarification_question=question_text)

    # Every water_transfer numeric field is logically whole - round per
    # question the same way rules_based.py's fallback does, so the LLM and
    # rule-based paths never disagree on a decimal reply (e.g. "6.5 inch").
    value = _apply_rounding(value, question.key)

    if question.allowed_units and len(question.allowed_units) == 1:
        unit = question.allowed_units[0]

    if question.key == "borewell_size":
        ask_confirmation, message = _validate_borewell_size(value)
        if message and not ask_confirmation:
            return ParsedAnswer(needs_clarification=True, clarification_question=message)
        if message:
            return ParsedAnswer(
                value=_display_value(value), unit=unit, needs_clarification=True, clarification_question=message
            )

    return ParsedAnswer(
        value=_display_value(value), unit=unit, confirmation_message=_confirmation_message(value, unit)
    )


def previous_unit_applies(ctx: _Ctx, value: float) -> bool:
    return ctx.previous_value is not None and value == ctx.previous_value and ctx.previous_unit is not None


def _unit_was_never_stated(ctx: _Ctx, value: float) -> bool:
    """True when this value matches a number the user gave in an earlier
    turn - either a confirmed previous_value or an unconfirmed
    pending_suggestion - for which no unit was ever recorded.
    """
    if ctx.previous_value is not None and value == ctx.previous_value and ctx.previous_unit is None:
        return True
    if ctx.pending_suggestion is not None and value == ctx.pending_suggestion:
        return True
    return False


_INTENT_HANDLERS = {
    "answer": _handle_answer,
    "ambiguous": _handle_ambiguous,
    "redirect": _handle_redirect,
    "additional": _handle_additional,
    "edit_attempt": _handle_edit_attempt,
    "doesnt_know": _handle_doesnt_know,
    "skip": _handle_skip,
    "out_of_scope": _handle_out_of_scope,
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

    Primary: LLM classifies the reply into one intent (see INTENTS) and
    extracts only that intent's fields; a small handler per intent turns it
    into a ParsedAnswer. Fallback: rule-based mode when LLM unavailable.
    """
    other_questions_line = (
        "This use case's OTHER questions - each is (key, prompt): "
        f"{[(q.key, q.prompt) for q in other_questions]!r}\n"
        if other_questions
        else ""
    )
    locked_in_answers_line = (
        "Already-answered questions from earlier in this conversation, "
        "OUTSIDE this use case's question list, that cannot be edited - "
        f"each is (question, chosen answer): {list(locked_in_answers.items())!r}.\n"
        if locked_in_answers
        else ""
    )
    pending_suggestion_line = (
        f"A pending, UNCONFIRMED suggestion from last turn: {pending_suggestion!r}. Treat "
        "the current reply as 'answer' with this value if EITHER: it's a clear "
        "affirmative response (e.g. 'yes', 'correct'), or it states only a unit "
        "with no number (that unit belongs to this pending number - combine "
        "them, don't ask the user to reconfirm the number itself). A bare "
        "repeat of the same unclear word, or a reply that doesn't affirm and "
        "doesn't give a unit, is not confirmation; use 'ambiguous' again "
        "instead, keeping this same value as suggested_value.\n"
        if pending_suggestion is not None
        else ""
    )
    previous_guess_line = (
        f"A previously CONFIRMED value/unit for this question: {previous_value!r} {previous_unit!r}. "
        "See the PREVIOUS VALUE rule above.\n"
        if previous_value is not None
        else ""
    )
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid units: {question.allowed_units!r}\n"
        f"Domain context: {question.domain_context or 'none provided'}\n"
        f"{previous_guess_line}"
        f"{other_questions_line}"
        f"{locked_in_answers_line}"
        f"{pending_suggestion_line}"
        f"User's reply: {user_text!r}"
    )

    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT, user_prompt, json_schema=_parse_answer_schema(other_questions),
        )
        data = json.loads(raw)
        intent = data.get("intent")

        # CONFIDENCE gate: a code-level decision, not left purely to which
        # intent the model happened to pick - a borderline reply should get
        # the same outcome every time, not vary call to call (see
        # CONFIDENCE_THRESHOLD).
        confidence = data.get("confidence")
        if intent in ("answer", "redirect") and confidence is not None and confidence < CONFIDENCE_THRESHOLD:
            data["suggested_value"] = data.get("value")
            intent = "ambiguous"
        elif intent == "ambiguous" and confidence is not None and confidence >= CONFIDENCE_THRESHOLD:
            promoted_value = data.get("suggested_value")
            if promoted_value is not None:
                data["value"] = promoted_value
                intent = "answer"

        handler = _INTENT_HANDLERS.get(intent)
        if handler is None:
            logger.warning("water_transfer parse_answer: unknown intent %r, treating as ambiguous", intent)
            handler = _handle_ambiguous

        ctx = _Ctx(user_text, previous_value, previous_unit, pending_suggestion, clarification_attempts, other_questions)
        result = handler(question, data, ctx)
        if result is None:
            result = _handle_ambiguous(question, data, ctx)

        # Give-up threshold: only once THIS turn's reply has had a real
        # chance to resolve the question (e.g. combining with previous_value)
        # and still failed - never before calling the LLM, or a reply that
        # would have completed the answer never gets the chance to.
        if not question.optional and result.needs_clarification and clarification_attempts >= GIVE_UP_THRESHOLD:
            return ParsedAnswer(gave_up=True, clarification_question=_give_up_message(question, attempted_twice=True))

        return result
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "water_transfer parse_answer: LLM extraction failed for question=%r, "
            "falling back to rule-based: %r",
            question.key, e,
        )
        return rules_based.parse_answer_rule_based(
            question, user_text, clarification_attempts, previous_value
        )


# ===== CATEGORY PARSING =====

# delivery_type is offered to the user as a two-option pick ("ground floor"
# or "overhead tank"); a bare digit is common shorthand for "the first/second
# option" and is resolved deterministically here rather than left to the
# LLM's own judgment call, which was inconsistent between calls with no code
# rule to anchor it (see the "0"/"g"/"G" cases this was built to fix).
_DELIVERY_TYPE_DIGIT_CATEGORIES = ("ground_floor", "overhead_tank")


def _try_numeric_shorthand(question: Question, user_text: str, valid_categories: list[str]) -> str | None:
    """0 -> the first listed category, any other whole number -> the second.

    Only applies to delivery_type's exact two-category shape - returns None
    for anything else so it's a no-op for other categorical questions.
    """
    if question.key != "delivery_type" or set(valid_categories) != set(_DELIVERY_TYPE_DIGIT_CATEGORIES):
        return None
    stripped = user_text.strip()
    if not stripped.lstrip("+-").isdigit():
        return None
    return "ground_floor" if int(stripped) == 0 else "overhead_tank"


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
    "GUESS AND CONFIDENCE: these two fields are independent of category and "
    "of each other's wording - fill BOTH of them on every reply that points "
    "toward any category at all, even a weak or uncertain pointer, "
    "regardless of what you put in category or needs_clarification: "
    "best_guess_category is your single best reading of which category the "
    "reply points to (a bare letter like 'g' still points toward "
    "ground_floor - name it here even though it's too weak to commit to as "
    "the confirmed category). confidence is 0 to 100 for how sure you are "
    "that guess is correct - 100 means completely certain (a full, clear "
    "word or phrase for that option), 0 means pure guesswork; a bare single "
    "letter or initial should score low (below 50), a full clear word or "
    "unambiguous description should score high (90+) regardless of length. "
    "Only leave best_guess_category and confidence both null if the reply "
    "truly gives no hint at all toward any category (pure noise, unrelated "
    "text). "
    "category is SEPARATE from best_guess_category - only set category when "
    "you would also set needs_clarification=false for it (a confirmed "
    "answer); otherwise leave category null even if best_guess_category is "
    "filled. "
    "PENDING SUGGESTION: if a pending, unconfirmed suggestion from last turn is "
    "given to you, only resolve to that category if the current reply is a "
    "clear affirmative response to it (e.g. 'yes', 'correct', 'that's right') - "
    "a bare repeat of the same unclear word is NOT confirmation."
)


def _parse_category_schema(valid_categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": ["string", "null"], "enum": [*valid_categories, None]},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
            "best_guess_category": {"type": ["string", "null"], "enum": [*valid_categories, None]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
        },
        "required": [
            "category", "needs_clarification", "clarification_question", "skipped",
            "best_guess_category", "confidence",
        ],
    }


def parse_category(
    question: Question,
    user_text: str,
    valid_categories: list[str],
    clarification_attempts: int = 0,
    pending_suggestion: str | None = None,
) -> ParsedCategory:
    """Parse water transfer category question answer (delivery_type).

    Primary: LLM mode with natural language understanding.
    Fallback: Rule-based mode when LLM unavailable.

    pending_suggestion, when given, is the prior turn's unconfirmed
    suggested_category for this same question (see suggested_category on
    ParsedCategory) - it only becomes the answer if the current reply is a
    genuine affirmative response to it.
    """
    shorthand = _try_numeric_shorthand(question, user_text, valid_categories)
    if shorthand is not None:
        return ParsedCategory(
            category=shorthand,
            confirmation_message=f"Got it: {rules_based.get_category_label(shorthand)}",
        )

    pending_suggestion_line = (
        f"A pending, UNCONFIRMED suggestion from last turn: {pending_suggestion!r}. "
        "See the PENDING SUGGESTION rule above.\n"
        if pending_suggestion is not None
        else ""
    )
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid categories: {valid_categories!r}\n"
        f"{pending_suggestion_line}"
        f"User's reply: {user_text!r}"
    )

    try:
        raw = llm_client.complete(
            PARSE_CATEGORY_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_category_schema(valid_categories),
        )
        data = json.loads(raw)

        # CONFIDENCE gate: code-level, not left purely to the model's own
        # needs_clarification/category choice - a borderline reply should
        # get the same outcome every time (see CONFIDENCE_THRESHOLD).
        # best_guess_category is a separate field from category specifically
        # so the model always has somewhere to put its guess even when it's
        # too unsure to fill category itself (a bare "g" still points toward
        # ground_floor - see GUESS AND CONFIDENCE in the prompt).
        guess = data.get("best_guess_category") or data.get("category")
        confidence = data.get("confidence")
        if guess and not data.get("skipped"):
            if confidence is not None and confidence < CONFIDENCE_THRESHOLD:
                data["category"] = None
                data["needs_clarification"] = True
                data["suggested_category"] = guess
                if not data.get("clarification_question"):
                    label = rules_based.get_category_label(guess)
                    data["clarification_question"] = f"Did you mean {label.lower()}?"
            else:
                data["category"] = guess
                data["needs_clarification"] = False
                data["confirmation_message"] = f"Got it: {rules_based.get_category_label(guess)}"

        data.pop("confidence", None)
        data.pop("best_guess_category", None)
        return ParsedCategory(**data)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "water_transfer parse_category: LLM extraction failed, "
            "falling back to rule-based: %r",
            e,
        )
        return rules_based.parse_category_rule_based(
            question, user_text, valid_categories, clarification_attempts
        )
