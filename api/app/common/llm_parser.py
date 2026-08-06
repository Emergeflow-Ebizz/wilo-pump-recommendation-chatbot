"""Free-text answer parsing.

These functions only extract structured values (a number + unit, or a yes/no)
from what the user typed. They never validate, normalize, or decide
accept/reject/fallback - that logic lives entirely in each use case's
rules.py and is untouched by anything here.
"""
import json
import logging
import re

from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import ParsedAnswer, ParsedCategory, Question

logger = logging.getLogger(__name__)

def _parse_answer_schema(
    allowed_units: list[str] | None, other_questions: list[Question]
) -> dict:
    """Build the structured-output schema for one question.

    Constraining unit to the exact canonical strings this use case's
    normalize_*() functions accept (e.g. "ft"/"m", not "feet"/"meter")
    means the LLM can only ever return a unit rules.py already understands -
    it cannot produce a synonym that would fail normalization downstream.
    The enum covers this question's own units plus every other question's
    units, since a redirected answer's unit belongs to whichever question
    redirect_key names, not necessarily this one.

    redirect_key is constrained the same way, to the exact keys of the
    other questions in this use case's sequence - the LLM can only name a
    question that actually exists, never invent one.
    """
    other_question_keys = [q.key for q in other_questions]
    combined_units: list[str] = list(allowed_units or [])
    for other in other_questions:
        for unit in other.allowed_units or []:
            if unit not in combined_units:
                combined_units.append(unit)

    # No enum here on purpose: constraining a tool-use call to an enum makes
    # the provider reject the whole response when the model's raw unit text
    # doesn't map cleanly - safer to accept any string and let
    # _normalize_unit() below reconcile it against the allowed list.
    unit_schema = {"type": ["string", "null"]}

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
            "unit": unit_schema,
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
            "redirect_key": redirect_schema,
            "gave_up": {"type": "boolean"},
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
            "skipped", "redirect_key", "gave_up", "additional_answers",
            "edit_not_supported",
        ],
    }


REASON_FALLBACKS: dict[str, str] = {
    "missing_unit": "Please provide {subject} along with its unit.",
    "missing_value": "Please provide {subject}.",
    "non_integer": "{subject} must be a whole number - could you give a whole number?",
    "non_positive": "{subject} must be greater than zero - could you give a valid value?",
    "generic": "Could you clarify your answer for {subject}?",
}


def _generate_clarification_question(
    question: Question,
    reason: str,
    attempts: int,
    extracted_value: float | None = None,
    extracted_unit: str | None = None,
    user_text: str | None = None,
) -> str:
    """Generate a natural clarification question for pump selection.

    reason is one of REASON_FALLBACKS's keys, describing what's still
    missing or invalid. Falls back to a plain templated sentence only if
    the LLM itself is unreachable - this is never the first choice.

    user_text, when given, is the user's actual reply that triggered this
    clarification. Without it, the generator can only reword the same
    question - it can't tell "idk" (mild reluctance) apart from "idk how
    would I know this" (a genuine request for help figuring out the
    answer), so it ends up repeating a near-identical question every
    attempt instead of actually helping. With it, the model can recognize
    when the user is asking HOW to determine the value (not just refusing
    to answer) and reason about how to help them - e.g. suggest checking
    paperwork or measuring directly - using its own general judgment for
    HOW to phrase that help.

    What it may NOT do is state any specific number, range, or threshold
    that isn't explicitly written in question.domain_context - domain_context
    is the single source of truth for facts about this system (what pump
    sheets cover, what's required, why a question matters); the model must
    not invent a "typical value" to nudge the user toward, since that risks
    the user parroting a guessed number back instead of their real one.
    Generic how-to-find-it advice, by contrast, doesn't need to be spelled
    out here - that's ordinary reasoning the model already has.
    """
    subject = question.key.replace("_", " ")
    units_str = ", ".join(question.allowed_units) if question.allowed_units else "the available units"
    user_reply_line = f"The user's actual reply just now: {user_text!r}. " if user_text else ""

    prompt = (
        f"User is being asked about: {subject}. Question as shown to the user: "
        f"{question.prompt!r}. "
        f"Domain context - facts about THIS system, e.g. constraints, ranges, "
        f"why the question matters: {question.domain_context or 'none provided.'} "
        f"Valid units: {units_str}. "
        f"Reason clarification is needed: {reason}. "
        f"What was extracted so far: value={extracted_value!r}, unit={extracted_unit!r}. "
        f"{user_reply_line}"
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
            "message - a guessed number risks the user parroting it back instead "
            "of their real answer. (3) At most one practical pointer folded into "
            "that same single sentence - never a list of options.",
            prompt,
            temperature=1.0,  # High temp for natural variety
        ).strip()
        # Clean up markdown
        response = "\n".join(line.strip() for line in response.split("\n") if line.strip() and not line.startswith("#"))
        return response.strip() if response else REASON_FALLBACKS[reason].format(subject=subject)
    except LLMUnavailableError:
        return REASON_FALLBACKS[reason].format(subject=subject)


def _normalize_unit(raw_unit: str | None, allowed_units: list[str] | None) -> str | None:
    """Normalize unit text to match allowed units using fuzzy matching.

    Handles typos and variations by checking substring containment. Returns
    the matching canonical unit, or None if no match found.
    """
    if not raw_unit or not allowed_units:
        return raw_unit
    cleaned = raw_unit.strip().lower()
    if cleaned in allowed_units:
        return cleaned
    for candidate in allowed_units:
        if candidate in cleaned or cleaned in candidate:
            return candidate
    return raw_unit


def _validate_additional_answers(
    raw_entries: list[dict], other_questions: list[Question], current_question_key: str
) -> list[dict]:
    """Apply the same defensive checks used for the primary answer to each
    additional_answers entry, dropping anything that doesn't hold up.

    additional_answers lets the model report answers to OTHER questions
    volunteered in the same reply (see the ADDITIONAL ANSWERS rule in
    PARSE_ANSWER_SYSTEM_PROMPT) - since those values skip the caller's own
    per-question validation entirely if passed through blindly, each entry
    gets the same never-guess/never-accept-invalid treatment as the primary
    question's value/unit: unit normalization, unit-required check,
    whole-number check, and positive-value check. An entry that fails any
    of these is dropped silently - the caller will simply ask that question
    normally later, which is always safe, rather than accepting a shaky value.
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
        unit = _normalize_unit(entry.get("unit"), target_question.allowed_units)
        if target_question.allowed_units and len(target_question.allowed_units) == 1:
            unit = target_question.allowed_units[0]
        if target_question.requires_stated_unit and unit is None:
            continue
        if target_question.requires_integer:
            if value != int(value):
                continue
            if target_question.min_value is not None and value < target_question.min_value:
                continue
        elif value <= 0:
            continue
        validated.append({"key": key, "value": value, "unit": unit})
    return validated


PARSE_ANSWER_SYSTEM_PROMPT = (
    "You extract a numeric value and its unit from a user's free-text reply "
    "to a specific question. Return only what the user actually said - do not "
    "validate, do not decide whether to ask follow-up questions, just extract. "
    "For unit words: normalize the user's word to the exact matching string "
    "from the valid units list given to you. Only ask for clarification if "
    "it's genuinely ambiguous which valid unit (if any) they meant. NEVER "
    "perform unit conversion "
    "yourself - if the user's stated unit is a real, different unit that "
    "isn't a typo/spelling match for one of the exact valid unit strings, "
    "do not compute the equivalent value in a valid unit on their "
    "behalf. Treat that exactly like any other unmatched unit: set "
    "needs_clarification=true, value and unit null, and ask them to restate "
    "it in one of the valid units. This rule holds regardless of anything "
    "else in this prompt, including any note below about earlier locked-in "
    "answers - that note only concerns whether an earlier answer can be "
    "edited, it never grants permission to convert or resolve the current "
    "question's unit yourself. If the user said a number with no unit, return "
    "the number in value and leave unit null - the caller will decide what to "
    "ask next. "
    "WHOLE NUMBER: If the question requires a whole number, reject "
    "any non-whole reply - set needs_clarification=true, value null, "
    "ask for a whole number. "
    "MINIMUM VALUE: Some questions have a stated minimum value (e.g. 'num_floors' "
    "may require >= 1 to mean at least one floor, or >= 0 to allow ground floor). "
    "If a minimum is stated in the question details, reject any value below it - "
    "set needs_clarification=true, value/unit null. If no minimum is stated, zero "
    "is allowed for integer questions. For non-integer questions (borewell size, "
    "well depth, motor power, tank capacity), zero and negative numbers are always "
    "rejected - these are physical quantities that must be strictly positive. "
    "SKIP: If optional and the user says skip/no/idk/don't know/etc, set "
    "skipped=true, leave value/unit/needs_clarification/clarification_question null. "
    "If NOT optional, never skip - ask for clarification instead. "
    "REDIRECT: If the user's reply does NOT answer the current question at all, "
    "and instead clearly corrects a DIFFERENT question (e.g. current question is "
    "motor power but user says 'well depth is 50 meters'), set redirect_key to "
    "that question's key, put the corrected value/unit in value/unit, set "
    "needs_clarification=false, skipped=false. Only if you can determine both a "
    "concrete value AND its unit for the other question. Otherwise treat it as a "
    "clarification for the current question. "
    "ADDITIONAL ANSWERS: Different from REDIRECT - if the user's reply DOES answer "
    "the current question (value/unit filled normally) AND ALSO clearly states a "
    "concrete value (and unit, if that other question needs one) for one or more "
    "OTHER questions in this sequence - whether already asked or not yet asked - "
    "add an entry per extra question to additional_answers: {key, value, unit}. "
    "Example: current question is borewell diameter, user replies '4 inch "
    "borewell, 300 ft deep, 2 floors' - value=4, unit='inch' for the current "
    "question, PLUS additional_answers=[{key: 'well_depth', value: 300, unit: "
    "'ft'}, {key: 'num_floors', value: 2, unit: null}]. Only add an entry when you "
    "have a genuinely concrete, unambiguous value (and required unit) for that "
    "specific other question - never guess, infer, or split up a value that "
    "wasn't clearly and separately stated for that question. When in doubt, leave "
    "it out of additional_answers rather than including a shaky guess - the "
    "caller will simply ask that question normally later. Leave additional_answers "
    "as an empty array if nothing else was volunteered. "
    "PREVIOUS VALUE: If a previous value/unit was recorded for this same question, "
    "treat it as still valid unless the user's current reply gives a new, different "
    "number - keep carrying it forward turn after turn. If the current reply doesn't "
    "state a new number, still return the previously recorded value in value - do not "
    "null it out just because this particular reply didn't repeat the number. Only "
    "replace it if the user gives an actual new number this turn. The user's stated "
    "unit always wins over any previously recorded unit. "
    "AMBIGUOUS: If genuinely unclear, set needs_clarification=true, value/unit null, "
    "and ask a short clarification_question. "
    "EDIT NOT SUPPORTED: If the user's reply clearly tries to change or correct an "
    "answer to a question that is NEITHER the current question NOR listed in the "
    "other questions given to you - most often one of the already-answered "
    "questions listed separately below (if any) that are outside this use case's "
    "own question list - this system has no way to go back and edit an answer "
    "once the conversation has moved past it. Set edit_not_supported=true, "
    "value/unit null, needs_clarification=false, skipped=false, redirect_key null. "
    "Do not use REDIRECT for this case - REDIRECT is only for questions in the "
    "given other-questions list. If the reply references something that matches "
    "neither the current question, the other-questions list, NOR any "
    "already-answered question given to you, it is not an edit attempt - treat it "
    "as AMBIGUOUS instead. "
    "Never ask about anything other than THIS question's value/unit. "
    "redirect_key, skipped, needs_clarification, and edit_not_supported are mutually "
    "exclusive."
)


def _try_rule_based_parse(user_text: str, allowed_units: list[str] | None, question: Question, previous_value: float | None = None) -> dict | None:
	"""Attempt to extract value + unit using regex/pattern matching.

	Returns a dict matching the LLM response schema if a clear match is found,
	otherwise None to fall back to LLM parsing.
	"""
	user_text = user_text.strip()
	if not user_text:
		return None

	if allowed_units is None:
		match = re.match(r'^\s*([+-]?\d+(?:\.\d+)?)\s*$', user_text)
		if not match:
			return None
		value_str = match.group(1)
		value = float(value_str)
		if question.requires_integer and value != int(value):
			return None
		return {
			"value": value,
			"unit": None,
			"needs_clarification": False,
			"clarification_question": None,
			"skipped": False,
			"redirect_key": None,
			"gave_up": False,
		}

	unit_pattern = "|".join(re.escape(unit) for unit in allowed_units)
	pattern = rf'^\s*([+-]?\d+(?:\.\d+)?)\s*({unit_pattern})\s*$'
	match = re.match(pattern, user_text, re.IGNORECASE)

	if not match:
		# Check if it's just a unit correction (no number, but a valid unit)
		cleaned = user_text.lower()
		for unit in allowed_units:
			if cleaned == unit or cleaned in unit or unit in cleaned:
				if previous_value is not None:
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

	if unit not in allowed_units:
		return None

	if question.requires_integer and value != int(value):
		return None

	return {
		"value": value,
		"unit": unit,
		"needs_clarification": False,
		"clarification_question": None,
		"skipped": False,
		"redirect_key": None,
		"gave_up": False,
	}


def parse_answer(
    question: Question,
    user_text: str,
    *,
    previous_value: float | None = None,
    previous_unit: str | None = None,
    other_questions: list[Question] = (),
    clarification_attempts: int = 0,
    locked_in_answers: dict[str, str] | None = None,
) -> ParsedAnswer:
    """Parse a free-text answer into a numeric value + unit for `question`.

    When question.requires_stated_unit is set, the LLM never infers the
    unit from magnitude - the user must state it explicitly. The resulting
    (value, unit) still flows through this use case's own
    normalize_*/rules.py logic unchanged.

    previous_value/previous_unit, when given, are the value/unit this
    function previously parsed for this same question - they let a bare
    unit correction from the user (e.g. "no it's meters") reuse the
    previously stated number instead of being treated as a fresh,
    number-less reply.

    clarification_attempts tracks how far along this question's
    clarification sequence the caller already is: 0 = never asked, 1 = a
    clarification was already asked once, 2 = a second clarification was
    already given once. This applies to every non-optional (required)
    question, not just unit-bearing ones - any required question whose
    value (and, if requires_stated_unit, unit) is still missing gets up to
    two LLM-generated clarification attempts. At 2, a further non-answer
    sets gave_up=true instead of asking again - the caller should end the
    conversation for this question in that case rather than call
    parse_answer for it again. Optional questions never enter this flow -
    an unclear reply to an optional question is skipped, not clarified.

    other_questions, when given, lets the LLM recognize a reply that's
    actually correcting an earlier answer rather than answering the current
    question - the caller is responsible for updating its own answers state
    and re-asking the current question when redirect_key comes back set.

    locked_in_answers, when given, is a {question_key: display_value} map of
    categorical/earlier answers already collected for this conversation that
    are OUTSIDE this use case's own question list (e.g. delivery_type,
    inside_or_outside) - these can never be redirected to (see EDIT NOT
    SUPPORTED in the system prompt), but the LLM still needs to know they
    exist and what was chosen, or it has no way to recognize a reply like
    "terrace" as referring back to one of them rather than being nonsense.
    """
    allowed_units = question.allowed_units
    allowed_units_line = (
        f"Valid unit values for this question - unit must be exactly one of these "
        f"strings (or null): {allowed_units!r}\n"
        if allowed_units
        else ""
    )
    unit_required_line = (
        f"This question REQUIRES A STATED UNIT (see the unit-required rule "
        f"above) - never infer the unit from magnitude. Prior clarification "
        f"attempts so far for this question: {clarification_attempts!r}.\n"
        if question.requires_stated_unit
        else ""
    )
    integer_required_line = (
        "This question REQUIRES A WHOLE NUMBER (see the whole-number rule "
        "above) and has no unit.\n"
        if question.requires_integer
        else ""
    )
    min_value_line = (
        f"This question has a minimum value of {question.min_value} "
        f"(see the MINIMUM VALUE rule above).\n"
        if question.min_value is not None
        else ""
    )
    previous_guess = (
        f"Your previous guess for this question: {previous_value!r} {previous_unit!r}\n"
        if previous_value is not None
        else ""
    )
    other_questions_line = (
        "This use case's OTHER questions, in case the reply corrects one of "
        "these instead of answering the current question - each is "
        f"(key, prompt): {[(q.key, q.prompt) for q in other_questions]!r}\n"
        if other_questions
        else ""
    )
    locked_in_answers_line = (
        "Already-answered questions from earlier in this conversation that "
        "are OUTSIDE this use case's question list and CANNOT be edited or "
        "redirected to (see EDIT NOT SUPPORTED) - each is (question, chosen "
        f"answer): {list(locked_in_answers.items())!r}. This is ONLY for "
        "recognizing an edit attempt - it does not change how you extract "
        "the CURRENT question's value/unit, and it is not permission to "
        "convert units yourself (see the NEVER perform unit conversion "
        "rule above).\n"
        if locked_in_answers
        else ""
    )
    domain_context_line = f"Domain context: {question.domain_context}\n" if question.domain_context else ""
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"{allowed_units_line}"
        f"{unit_required_line}"
        f"{integer_required_line}"
        f"{min_value_line}"
        f"{domain_context_line}"
        f"{previous_guess}"
        f"{other_questions_line}"
        f"{locked_in_answers_line}"
        f"User's reply: {user_text!r}\n"
        f"Track what's NEW: compare user's current reply against previous answer. "
        f"If they previously said a number but no unit, and now they say a unit keyword, "
        f"extract that unit. If they say both, extract both."
    )

    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_answer_schema(allowed_units, other_questions),
        )
        data = json.loads(raw)
        data["unit"] = _normalize_unit(data.get("unit"), allowed_units)

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
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "parse_answer: LLM extraction failed for question=%r, falling back "
            "to rule-based parsing: %r",
            question.key, e,
        )
        rule_based = _try_rule_based_parse(user_text, allowed_units, question, previous_value)
        if rule_based is not None:
            data = rule_based
        else:
            if question.optional:
                return ParsedAnswer(skipped=True)
            return ParsedAnswer(
                needs_clarification=True,
                clarification_question=(
                    f"I couldn't understand that answer for \"{question.prompt}\". "
                    "Could you rephrase it, including the unit if there is one?"
                ),
            )

    # Defensive: don't let an already-recorded value get silently dropped just
    # because this turn's reply didn't repeat it (e.g. "idk", "how would I
    # know?", a bare unit correction). The prompt asks the model to carry
    # previous_value forward on its own, but that's not reliable enough to
    # trust alone - if the model came back with value=None while we were
    # given a previous_value, and this isn't a redirect/skip, restore it.
    if (
        not data.get("redirect_key")
        and not data.get("skipped")
        and data.get("value") is None
        and previous_value is not None
    ):
        data["value"] = previous_value

    # Defensive: a question with exactly one valid unit (e.g. hp-only motor
    # power, litres-only tank capacity) never needs a unit-ask - that unit is
    # implicit. Don't rely solely on the model following the per-question
    # hint above: if it extracted a number but asked for the unit anyway (or
    # left unit null), force the single valid unit instead of surfacing a
    # spurious clarification. Skipped when this is a redirect - the parsed
    # value/unit then belong to whichever question redirect_key names, which
    # may have a different (or multi-option) unit set than this question.
    if (
        not data.get("redirect_key")
        and allowed_units
        and len(allowed_units) == 1
        and not question.requires_stated_unit
    ):
        if data.get("value") is not None:
            data["unit"] = allowed_units[0]
            data["needs_clarification"] = False
            data["clarification_question"] = None

    # Whether required info is still missing for this question: either the
    # value itself, or - for questions that require it - the unit. Optional
    # questions are never subject to the clarification/give-up flow below.
    missing_required_info = not question.optional and (
        data.get("value") is None or (question.requires_stated_unit and data.get("unit") is None)
    )
    not_redirect_or_skip = not data.get("redirect_key") and not data.get("skipped")

    # Give-up threshold: if we're at attempt 2+ and still missing required
    # info, stop and give up instead of asking again. Generate the "cannot
    # recommend" message via LLM - applies to any required question, not
    # just unit-bearing ones.
    if not_redirect_or_skip and missing_required_info and clarification_attempts >= 2:
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
                "plainly so the user understands what would have worked. Output "
                "only that one sentence, nothing else.",
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
    elif not_redirect_or_skip and missing_required_info and data.get("needs_clarification"):
        # Clarification question: generate it with high temperature so the
        # wording varies and it's grounded in this question's domain
        # context, rather than reusing whatever (possibly generic) wording
        # the main extraction call produced.
        reason = "missing_unit" if data.get("value") is not None else "missing_value"
        data["clarification_question"] = _generate_clarification_question(
            question,
            reason,
            clarification_attempts,
            data.get("value"),
            data.get("unit"),
            user_text=user_text,
        )

    # Defensive: a question requiring a whole number (e.g. num_floors) must
    # never accept a fractional value - don't rely solely on the model
    # following the whole-number instruction above. Skipped when this is a
    # redirect, since the parsed value then belongs to whichever question
    # redirect_key names, which may be a different, fractional-allowed one.
    if (
        not data.get("redirect_key")
        and question.requires_integer
        and data.get("value") is not None
        and data["value"] != int(data["value"])
    ):
        data["unit"] = None
        data["skipped"] = False
        data["needs_clarification"] = True
        data["clarification_question"] = _generate_clarification_question(
            question, "non_integer", clarification_attempts, data["value"], data.get("unit"), user_text=user_text
        )
        data["value"] = None

    # Defensive: for a question that does NOT require a whole number (e.g.
    # well_depth, borewell_size, motor_power_hp, tank_capacity - all take any
    # positive float), the model must never invent a whole-number requirement
    # on its own initiative and ask for clarification anyway. If a complete,
    # positive value (and unit, when one is required) was already extracted,
    # override any spurious needs_clarification and accept the value as-is -
    # this only applies to the current question, not a redirect (whichever
    # question redirect_key names has its own requires_integer to honor).
    if (
        not data.get("redirect_key")
        and not question.requires_integer
        and data.get("value") is not None
        and data["value"] > 0
        and (not question.requires_stated_unit or data.get("unit") is not None)
    ):
        data["needs_clarification"] = False
        data["clarification_question"] = None
        data["skipped"] = False

    # Defensive normalization: redirect_key/skipped/needs_clarification are
    # meant to be mutually exclusive (see the system prompt), and a redirect
    # is only usable if it carries a concrete value. If the model ever
    # returns an inconsistent combination anyway, don't let a malformed
    # redirect (or a redirect tangled up with skip/clarification) reach the
    # caller - fall back to asking for clarification on the current
    # question instead of silently corrupting either question's answer.
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

    # Defensive: check minimum value constraints and positive-value constraints.
    # Integer questions with a min_value must meet that floor. Non-integer
    # questions (physical quantities like borewell diameter, depth, power, capacity)
    # must always be strictly positive (>0). Don't rely solely on the model
    # following the rules above - enforce it here as a safety net.
    rejected_value = data.get("value")
    target_key = data.get("redirect_key") or question.key
    target_question = next((q for q in other_questions if q.key == target_key), question)

    if rejected_value is not None:
        min_floor = target_question.min_value if target_question.min_value is not None else (0 if target_question.requires_integer else 0)
        should_reject = False

        if target_question.requires_integer and target_question.min_value is not None:
            should_reject = rejected_value < target_question.min_value
        elif not target_question.requires_integer:
            should_reject = rejected_value <= 0

        if should_reject:
            data["value"] = None
            data["unit"] = None
            data["redirect_key"] = None
            data["skipped"] = False
            data["needs_clarification"] = True
            data["clarification_question"] = _generate_clarification_question(
                target_question, "non_positive", clarification_attempts, rejected_value, user_text=user_text
            )
            data["gave_up"] = False

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


def _parse_category_schema(valid_categories: list[str]) -> dict:
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


PARSE_CATEGORY_SYSTEM_PROMPT = (
    "You determine which one of a fixed set of categories the user's "
    "free-text reply means, for a specific question. The valid categories "
    "are given to you exactly - you must return one of those exact strings "
    "(or null), never a synonym, paraphrase, or a category not in the list. "
    "Use natural-language understanding, not just literal keyword matching "
    "- e.g. if the categories are 'inside'/'outside' and the user replies "
    "'it's kept outdoors' or 'in the yard', that means 'outside'; if they "
    "reply 'in the pump room' or 'indoor', that means 'inside'. "
    "If the question is marked optional and the user's reply indicates they "
    "don't have or don't want to choose - 'skip', 'not sure', 'no', 'don't "
    "know', or similar - set skipped to true and leave category/"
    "needs_clarification/clarification_question at their default. Never do "
    "this for a non-optional question - ask for clarification instead. "
    "If the reply genuinely doesn't map to any valid category, set "
    "needs_clarification to true, leave category null, and ask a short "
    "clarification_question naming the valid options - do not guess a "
    "category just to fill the field."
)


# Keyword synonyms for each known category value, used only when the LLM is
# unavailable. Keyed by the exact category string rules.py expects; only
# categories actually present in valid_categories are checked, so this can
# safely list synonyms for categories from every use case in one place.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "ground_floor": ["ground floor", "ground-floor", "ground level", "groundfloor", "ground"],
    "elevated_tank": ["elevated tank", "elevated roof", "roof tank", "terrace tank", "overhead tank", "elevated", "roof", "terrace", "tank"],
    "inside": ["inside", "indoor", "indoors"],
    "outside": ["outside", "outdoor", "outdoors"],
    "horizontal": ["horizontal"],
    "vertical": ["vertical"],
}

# Plain, human-readable label for each category value, shown to the user
# instead of the internal literal (e.g. "ground_floor") when clarification
# is needed.
_CATEGORY_LABELS: dict[str, str] = {
    "ground_floor": "ground floor",
    "elevated_tank": "elevated tank",
    "inside": "inside",
    "outside": "outside",
    "horizontal": "horizontal",
    "vertical": "vertical",
}


def _category_label(category: str) -> str:
    """Human-readable label for a category value.

    Falls back to underscore-to-space rather than the raw literal, so a new
    category added to CATEGORY_QUESTIONS_BY_SLUG without a matching
    _CATEGORY_LABELS entry can never surface a raw snake_case string to the
    user - it just logs so the gap gets noticed and filled in.
    """
    label = _CATEGORY_LABELS.get(category)
    if label is None:
        logger.warning("parse_category: no _CATEGORY_LABELS entry for %r", category)
        return category.replace("_", " ")
    return label


def _try_rule_based_category_parse(user_text: str, valid_categories: list[str]) -> str | None:
    """Attempt to match free text to exactly one of valid_categories via
    exact match or keyword synonym, without any LLM call.

    Returns the matched category, or None if there's no match or more than
    one candidate matches (ambiguous - let the caller ask for clarification
    rather than guessing).
    """
    cleaned = user_text.strip().lower()
    if not cleaned:
        return None

    if cleaned in valid_categories:
        return cleaned

    matches = set()
    for category in valid_categories:
        for keyword in _CATEGORY_KEYWORDS.get(category, [category]):
            if keyword in cleaned:
                matches.add(category)
                break

    if len(matches) == 1:
        return next(iter(matches))
    return None


def parse_category(
    question: Question,
    user_text: str,
    valid_categories: list[str],
    clarification_attempts: int = 0,
) -> ParsedCategory:
    """Parse a free-text answer into one of `valid_categories` for `question`.

    Used for fixed-choice questions (e.g. inside/outside,
    horizontal/vertical) so natural phrasing ("it's kept outdoors") maps to
    the exact category string rules.py expects, instead of requiring the
    user to type one of the literal option words.

    clarification_attempts mirrors parse_answer's give-up mechanism: every
    non-optional question caps at 2 failed clarification attempts, with no
    exceptions - at attempt 2+, a reply that still doesn't resolve to a
    category sets gave_up=true instead of asking again, so the user can
    never get stuck in an infinite re-ask loop.
    """
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid categories: {valid_categories!r}\n"
        f"User's reply: {user_text!r}"
    )

    try:
        raw = llm_client.complete(
            PARSE_CATEGORY_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_category_schema(valid_categories),
        )
        data = json.loads(raw)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "parse_category: LLM extraction failed for question=%r: %r", question.key, e,
        )
        rule_based_category = _try_rule_based_category_parse(user_text, valid_categories)
        if rule_based_category is not None:
            return ParsedCategory(
                category=rule_based_category,
                confirmation_message=f"Got it: {_category_label(rule_based_category)}",
            )
        if question.optional:
            return ParsedCategory(skipped=True)
        if clarification_attempts >= 2:
            return ParsedCategory(
                gave_up=True,
                clarification_question="We cannot recommend you a model because of missing information.",
            )
        labels = [_category_label(c) for c in valid_categories]
        return ParsedCategory(
            needs_clarification=True,
            clarification_question=f"Sorry, I didn't get that. Please choose: {' or '.join(labels)}.",
        )

    if not data.get("needs_clarification") and not data.get("skipped") and data.get("category"):
        data["confirmation_message"] = f"Got it: {_category_label(data['category'])}"
    elif data.get("needs_clarification") and not question.optional and clarification_attempts >= 2:
        # Give-up threshold: same rule as parse_answer - every non-optional
        # question caps at 2 failed clarification attempts, no exceptions.
        data["category"] = None
        data["needs_clarification"] = False
        data["gave_up"] = True
        try:
            data["clarification_question"] = llm_client.complete(
                "Generate ONE short, friendly chat-message sentence, 15 words "
                "maximum, no preamble. Never state a specific number or 'typical' "
                "value from general knowledge - only use facts given in the user "
                "message. Output only that one sentence, nothing else.",
                f"The user couldn't provide the {question.key.replace('_', ' ')} information after "
                f"being asked twice. Domain context: {question.domain_context or 'none provided.'} "
                "Generate a brief, friendly message saying we cannot recommend a pump model without "
                "this information.",
                temperature=1.0,
            ).strip()
        except LLMUnavailableError:
            data["clarification_question"] = "We cannot recommend you a model because of missing information."

    return ParsedCategory(**data)


PARSE_YES_NO_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": ["boolean", "null"]},
        "needs_clarification": {"type": "boolean"},
    },
    "required": ["confirmed", "needs_clarification"],
}

PARSE_YES_NO_SYSTEM_PROMPT = (
    "You determine whether a user's free-text reply is an affirmative "
    "confirmation (yes) or a negative one (no) to the previous question. "
    "If the reply is genuinely ambiguous, set needs_clarification to true "
    "and leave confirmed null - do not guess."
)


class AmbiguousConfirmationError(Exception):
    """Raised when a yes/no reply can't be confidently interpreted."""


def parse_yes_no(user_text: str) -> bool:
    """Parse a free-text confirmation reply into a boolean.

    Raises AmbiguousConfirmationError instead of guessing when the LLM
    can't confidently tell yes from no.
    """
    try:
        raw = llm_client.complete(
            PARSE_YES_NO_SYSTEM_PROMPT, f"User's reply: {user_text!r}", json_schema=PARSE_YES_NO_SCHEMA
        )
        data = json.loads(raw)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        logger.warning("parse_yes_no: LLM extraction failed: %r", e)
        raise AmbiguousConfirmationError(
            f"Could not confidently interpret {user_text!r} as yes or no."
        ) from e

    if data.get("needs_clarification") or data.get("confirmed") is None:
        raise AmbiguousConfirmationError(
            f"Could not confidently interpret {user_text!r} as yes or no."
        )
    return bool(data["confirmed"])
