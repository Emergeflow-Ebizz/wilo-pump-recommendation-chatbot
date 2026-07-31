"""Tests for llm_parser, mocking the LLM client so no real API key is needed."""
import json
from unittest.mock import patch

from app.common.llm_client import LLMUnavailableError
from app.common.llm_parser import AmbiguousConfirmationError, parse_answer, parse_category, parse_yes_no
from app.use_cases.water_transfer.questions import DELIVERY_TYPE_QUESTION
from app.use_cases.water_transfer.questions import QUESTIONS as WATER_TRANSFER_QUESTIONS
from app.use_cases.tank_filling.questions import HORIZONTAL_OR_VERTICAL_QUESTION, INSIDE_OR_OUTSIDE_QUESTION

BOREWELL_SIZE = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "borewell_size")
WELL_DEPTH = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "well_depth")
NUM_FLOORS = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "num_floors")
MOTOR_POWER_HP = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "motor_power_hp")


def _answer_json(**overrides):
    data = {
        "value": None,
        "unit": None,
        "needs_clarification": False,
        "clarification_question": None,
        "skipped": False,
        "redirect_key": None,
        "gave_up": False,
    }
    data.update(overrides)
    return json.dumps(data)


def test_parse_answer_infers_inch_for_bare_borewell_number():
    fake_response = _answer_json(value=4.0, unit="inch")
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response) as mock_complete:
        result = parse_answer(BOREWELL_SIZE, "4")

    assert result.value == 4.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    assert result.confirmation_message == "Got it: 4.0 inch"
    mock_complete.assert_called_once()


def test_parse_answer_llm_signals_needs_clarification():
    extraction = _answer_json(needs_clarification=True)
    clarification_text = "Did you mean 4 inch or 4 mm?"
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ) as mock_complete:
        result = parse_answer(BOREWELL_SIZE, "asdf")

    assert result.needs_clarification is True
    assert result.clarification_question == clarification_text
    assert mock_complete.call_count == 2


def test_parse_answer_llm_unavailable_falls_back_to_clarification():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_answer(BOREWELL_SIZE, "4")

    assert result.needs_clarification is True
    assert result.value is None


def test_parse_answer_ignores_llm_hallucinated_whole_number_requirement():
    """Regression: well_depth (and similarly borewell_size, motor_power_hp,
    tank_capacity) does NOT require an integer. If the LLM extracts a
    complete, valid fractional value+unit but still sets needs_clarification
    on its own initiative (hallucinating a whole-number rule that was never
    told to it - only question.requires_integer=True questions get that
    instruction), the fractional value must still be accepted rather than
    surfacing a spurious clarification asking the user to round."""
    fake_response = _answer_json(
        value=98.42519685,
        unit="ft",
        needs_clarification=True,
        clarification_question="Did you mean 98 feet, or a different whole number?",
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        result = parse_answer(WELL_DEPTH, "feet", previous_value=98.42519685, previous_unit=None)

    assert result.value == 98.42519685
    assert result.unit == "ft"
    assert result.needs_clarification is False
    assert result.clarification_question is None


def test_parse_answer_edit_not_supported_returns_message_no_value():
    """When the user tries to correct an earlier answer that's outside this
    question and not in other_questions (e.g. an already-locked-in
    categorical choice like delivery_type), the LLM signals
    edit_not_supported instead of forcing it into redirect/clarification -
    the response must carry no value/unit and a plain explanatory message."""
    extraction = _answer_json(edit_not_supported=True)
    message = "Sorry, I can't edit that now - please refresh to choose again."
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, message],
    ):
        result = parse_answer(BOREWELL_SIZE, "no terrace not to ground")

    assert result.edit_not_supported is True
    assert result.value is None
    assert result.needs_clarification is False
    assert result.clarification_question == message


def test_parse_answer_rule_based_exact_format():
    result = parse_answer(BOREWELL_SIZE, "5 inch")

    assert result.value == 5.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    assert result.clarification_question is None
    assert result.confirmation_message == "Got it: 5.0 inch"


def test_parse_answer_rule_based_with_spacing():
    result = parse_answer(WELL_DEPTH, "  150   ft  ")

    assert result.value == 150.0
    assert result.unit == "ft"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_case_insensitive():
    result = parse_answer(BOREWELL_SIZE, "6 MM")

    assert result.value == 6.0
    assert result.unit == "mm"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_no_unit_question():
    result = parse_answer(NUM_FLOORS, "5")

    assert result.value == 5.0
    assert result.unit is None
    assert result.needs_clarification is False
    assert result.confirmation_message == "Got it: 5.0"


def test_parse_answer_rule_based_no_unit_with_decimal_rejected():
    extraction = _answer_json(value=5.5)
    clarification_text = "Please give a whole number."
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ):
        result = parse_answer(NUM_FLOORS, "5.5")

    assert result.needs_clarification is True
    assert result.value is None
    assert result.clarification_question == clarification_text


def test_parse_answer_gives_up_after_two_attempts_on_any_required_question():
    """num_floors has no unit at all, but the generic 2-attempt give-up
    mechanic must still apply to it - not just the unit-bearing questions."""
    extraction = _answer_json(needs_clarification=True)
    give_up_message = "We can't recommend a pump without this information."
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, give_up_message],
    ):
        result = parse_answer(NUM_FLOORS, "dunno", clarification_attempts=2)

    assert result.gave_up is True
    assert result.value is None
    assert result.clarification_question == give_up_message


def test_parse_answer_non_integer_rejection_uses_llm_generated_message():
    extraction = _answer_json(value=5.5)
    clarification_text = "Whole floors only, please - could you round to the nearest floor?"
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ):
        result = parse_answer(NUM_FLOORS, "5.5 floors")

    assert result.needs_clarification is True
    assert result.value is None
    assert result.clarification_question == clarification_text


def test_parse_answer_non_positive_rejection_falls_back_when_llm_unreachable():
    extraction = _answer_json(value=-2.0, unit="inch")
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, LLMUnavailableError("no key")],
    ):
        result = parse_answer(BOREWELL_SIZE, "-2 inch")

    assert result.needs_clarification is True
    assert result.value is None
    assert "greater than zero" in result.clarification_question


def test_parse_answer_confirmation_message_absent_on_skip():
    fake_response = _answer_json(skipped=True)
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        result = parse_answer(MOTOR_POWER_HP, "skip")

    assert result.skipped is True
    assert result.confirmation_message is None


def test_parse_answer_extracts_additional_answers_for_other_questions():
    """One reply answering multiple questions at once (e.g. "4 inch borewell,
    300 ft deep, 2 floors") should surface the extra answers via
    additional_answers, not just the current question's own value."""
    extraction = _answer_json(
        value=4.0,
        unit="inch",
        additional_answers=[
            {"key": "well_depth", "value": 300.0, "unit": "ft"},
            {"key": "num_floors", "value": 2.0, "unit": None},
        ],
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=extraction):
        result = parse_answer(
            BOREWELL_SIZE,
            "I have a 4-inch borewell, depth 300 ft, 2 floors.",
            other_questions=[WELL_DEPTH, NUM_FLOORS, MOTOR_POWER_HP],
        )

    assert result.value == 4.0
    assert result.unit == "inch"
    additional_by_key = {a.key: a for a in result.additional_answers}
    assert additional_by_key["well_depth"].value == 300.0
    assert additional_by_key["well_depth"].unit == "ft"
    assert additional_by_key["num_floors"].value == 2.0


def test_parse_answer_drops_additional_answer_missing_required_unit():
    """well_depth requires a stated unit - an additional_answers entry for it
    with no unit can't be trusted, so it should be dropped rather than passed
    through with a missing unit."""
    extraction = _answer_json(
        value=4.0,
        unit="inch",
        additional_answers=[{"key": "well_depth", "value": 300.0, "unit": None}],
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=extraction):
        result = parse_answer(
            BOREWELL_SIZE, "4 inch borewell, 300 deep",
            other_questions=[WELL_DEPTH, NUM_FLOORS],
        )

    assert result.additional_answers == []


def test_parse_answer_drops_additional_answer_for_unknown_key():
    """A key the model invents that isn't in other_questions must never be
    passed through - only questions that actually exist in this sequence."""
    extraction = _answer_json(
        value=4.0,
        unit="inch",
        additional_answers=[{"key": "not_a_real_question", "value": 5.0, "unit": None}],
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=extraction):
        result = parse_answer(
            BOREWELL_SIZE, "4 inch, and something else too",
            other_questions=[WELL_DEPTH, NUM_FLOORS],
        )

    assert result.additional_answers == []


def test_parse_yes_no_confirmed():
    fake_response = json.dumps({"confirmed": True, "needs_clarification": False})
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        assert parse_yes_no("yes please") is True


def test_parse_yes_no_ambiguous_raises():
    fake_response = json.dumps({"confirmed": None, "needs_clarification": True})
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        try:
            parse_yes_no("maybe")
            assert False, "expected AmbiguousConfirmationError"
        except AmbiguousConfirmationError:
            pass


def test_parse_category_llm_unavailable_falls_back_to_literal_match():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(DELIVERY_TYPE_QUESTION, "ground_floor", ["ground_floor", "elevated_tank"])

    assert result.category == "ground_floor"
    assert result.needs_clarification is False


def test_parse_category_llm_unavailable_falls_back_to_keyword_ground_floor():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(DELIVERY_TYPE_QUESTION, "ground floor", ["ground_floor", "elevated_tank"])

    assert result.category == "ground_floor"
    assert result.needs_clarification is False


def test_parse_category_llm_unavailable_falls_back_to_keyword_case_insensitive():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(DELIVERY_TYPE_QUESTION, "Ground Floor", ["ground_floor", "elevated_tank"])

    assert result.category == "ground_floor"


def test_parse_category_llm_unavailable_falls_back_to_keyword_elevated_tank():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(DELIVERY_TYPE_QUESTION, "it goes to the roof tank", ["ground_floor", "elevated_tank"])

    assert result.category == "elevated_tank"


def test_parse_category_llm_unavailable_falls_back_to_keyword_inside_outside():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(INSIDE_OR_OUTSIDE_QUESTION, "it's kept outdoors", ["inside", "outside"])

    assert result.category == "outside"


def test_parse_category_llm_unavailable_falls_back_to_keyword_horizontal_vertical():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(HORIZONTAL_OR_VERTICAL_QUESTION, "vertical", ["horizontal", "vertical"])

    assert result.category == "vertical"


def test_parse_category_llm_unavailable_and_unmatched_needs_clarification():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_category(DELIVERY_TYPE_QUESTION, "blah blah unrelated", ["ground_floor", "elevated_tank"])

    assert result.needs_clarification is True
    assert result.category is None
