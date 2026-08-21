import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("wilo_pump_chatbot")

from app.common import llm_client, llm_explainer, llm_parser, sheets_logger

# Optional: persists WARNING+ logs (warnings, errors, plus every per-LLM-call
# cost row, see llm_client.py - those are logged at WARNING specifically so
# they always get through this filter) to a Google Sheet, since Vercel's
# free tier only retains function logs for ~1hr. Routine INFO-level request
# summaries stay console-only. Rows are buffered in memory per-request and
# written in a background task after the response is sent, so this never
# blocks a request - see sheets_logger.py. Stays off if the two env vars
# below aren't set.
_sheets_handler = sheets_logger.build_handler()
if _sheets_handler is not None:
    _sheets_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(_sheets_handler)
from app.common.schemas import (
    DewateringRequest,
    DomesticHotWaterRequest,
    HeatCirculationRequest,
    ParsedAnswer,
    ParsedCategory,
    PressureBoostingRequest,
    PumpRecommendation,
    Question,
    SendPumpDataRequest,
    TankFillingRequest,
    WaterTransferRequest,
)
from app.use_cases.dewatering.questions import QUESTIONS as DEWATERING_QUESTIONS
from app.use_cases.dewatering.questions import next_question as dewatering_next_question
from app.use_cases.dewatering.rules import (
    DewateringUseCase,
    NoDewateringMatchError,
    calculate_head as dewatering_calculate_head,
    normalize_depth_of_pit,
)
from app.use_cases.domestic_hot_water.questions import QUESTIONS as DOMESTIC_HOT_WATER_QUESTIONS
from app.use_cases.domestic_hot_water.questions import next_question as domestic_hot_water_next_question
from app.use_cases.domestic_hot_water.rules import DomesticHotWaterUseCase
from app.use_cases.heat_circulation.questions import HEATING_SYSTEM_QUESTION
from app.use_cases.heat_circulation.questions import QUESTIONS as HEAT_CIRCULATION_QUESTIONS
from app.use_cases.heat_circulation.questions import next_question as heat_circulation_next_question
from app.use_cases.heat_circulation.rules import HeatCirculationUseCase, build_recommendations as heat_circulation_build_recommendations, normalize_area as heat_circulation_normalize_area
from app.use_cases.pressure_boosting.questions import QUESTIONS as PRESSURE_BOOSTING_QUESTIONS
from app.use_cases.pressure_boosting.questions import next_question as pressure_boosting_next_question
from app.use_cases.pressure_boosting.rules import (
    NoPressureBoostingMatchError,
    PressureBoostingUseCase,
    calculate_head as pressure_boosting_calculate_head,
)
from app.use_cases.tank_filling.questions import HORIZONTAL_OR_VERTICAL_QUESTION
from app.use_cases.tank_filling.questions import INSIDE_OR_OUTSIDE_QUESTION
from app.use_cases.tank_filling.questions import QUESTIONS as TANK_FILLING_QUESTIONS
from app.use_cases.tank_filling.questions import next_question as tank_filling_next_question
from app.use_cases.water_transfer.questions import DELIVERY_TYPE_QUESTION
from app.use_cases.tank_filling.rules import NoTankFillingMatchError, TankFillingUseCase
from app.use_cases.water_transfer.questions import QUESTIONS as WATER_TRANSFER_QUESTIONS
from app.use_cases.water_transfer.questions import next_question as water_transfer_next_question
from app.use_cases.water_transfer.rules import (
    BorewellOversizeConfirmationRequired,
    BorewellTooSmallError,
    MAX_BOREWELL_SIZE,
    MIN_BOREWELL_SIZE,
    NoModelAvailableError,
    OVERSIZE_DECLINE_MESSAGE,
    WaterTransferUseCase,
    calculate_head as water_transfer_calculate_head,
    normalize_well_depth,
)
from app.common.units import m_to_ft, sqm_to_sqft
from app.use_cases.tank_filling.rules import calculate_head as tank_filling_calculate_head

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LLM_API_KEY missing degrades every user-facing conversation (stricter
# regex-only answer parsing, canned rejection/explanation text instead of
# natural language - see llm_client.py/llm_parser.py/llm_explainer.py
# fallbacks) without ever raising an error, so it would otherwise go
# unnoticed until a user complains. Logged at ERROR on every cold start, and
# surfaced via /health below, so monitoring can catch a missing/expired key
# immediately instead of only from degraded UX reports.
if not os.environ.get("LLM_API_KEY"):
    logger.error(
        "LLM_API_KEY is not configured - chatbot is running in degraded mode "
        "(rule-based answer parsing only, canned explanation/rejection text, "
        "no free-form follow-up answers)."
    )

# In-process per-client sliding-window rate limit. This deployment runs on
# Vercel serverless, where each function instance is stateless and
# short-lived - this dict does NOT share state across concurrent instances or
# survive cold starts, so it cannot enforce a hard global limit. It still
# blocks single-instance hammering (repeated requests hitting the same warm
# instance) for free, with no new dependency or infra change. A true
# cross-instance limit would need an edge/infra-level solution (Vercel's own
# rate limiting, or a shared store like Redis) - tracked as a follow-up, not
# implemented here.
RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60
_request_log: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_and_log(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"

    # Reset per-request state used by sheets_logger (buffered rows) and
    # llm_client (which endpoint triggered each LLM call) before anything
    # in this request can log, so nothing leaks across requests sharing a
    # warm instance and rate-limit warnings get buffered too.
    sheets_rows_token = sheets_logger._pending_rows.set({})
    endpoint_token = llm_client.current_endpoint.set(f"{request.method} {request.url.path}")
    client_ip_token = llm_client.current_client_ip.set(client_ip)

    def _finish(response):
        buffered_rows = sheets_logger._pending_rows.get()
        sheets_logger._pending_rows.reset(sheets_rows_token)
        llm_client.current_endpoint.reset(endpoint_token)
        llm_client.current_client_ip.reset(client_ip_token)
        if buffered_rows:
            response.background = BackgroundTask(sheets_logger.flush_buffered_rows, buffered_rows)
        return response

    now = time.monotonic()
    window = _request_log[client_ip]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()

    if len(window) >= RATE_LIMIT_MAX_REQUESTS:
        logger.warning("rate limit exceeded: client=%s path=%s", client_ip, request.url.path)
        return _finish(JSONResponse(status_code=429, content={"detail": "Too many requests, please slow down."}))

    window.append(now)

    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error: client=%s method=%s path=%s", client_ip, request.method, request.url.path)
        buffered_rows = sheets_logger._pending_rows.get()
        sheets_logger._pending_rows.reset(sheets_rows_token)
        llm_client.current_endpoint.reset(endpoint_token)
        llm_client.current_client_ip.reset(client_ip_token)
        # No response object exists on this path to attach a background
        # task to, and the request has already failed, so flushing inline
        # here doesn't cost a successful response any latency.
        if buffered_rows:
            sheets_logger.flush_buffered_rows(buffered_rows)
        raise
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "client=%s method=%s path=%s status=%s duration_ms=%.1f",
        client_ip, request.method, request.url.path, response.status_code, duration_ms,
    )
    return _finish(response)


@app.exception_handler(ValueError)
def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    """Any ValueError reaching this point is malformed input (e.g. an
    unrecognized unit string) that slipped past Pydantic's own field
    validation into rules.py - a client error, not a server bug, so it must
    surface as a 422 rather than an unhandled 500."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health() -> JSONResponse:
    """Reports which optional dependencies are configured, so monitoring can
    detect a misconfigured deployment (e.g. a missing/expired LLM_API_KEY)
    instead of it only surfacing as silently degraded chatbot responses.

    Only "llm" affects `status`: it degrades every conversation (see the
    startup check above).
    """
    llm_configured = bool(os.environ.get("LLM_API_KEY"))
    checks = {
        "llm": {
            "configured": llm_configured,
            "provider": os.environ.get("LLM_PROVIDER", "anthropic"),
        },
        "send_pump_data": {
            "configured": bool(os.environ.get("SEND_PUMP_DATA_API_KEY")),
        },
        "sheets_logging": {
            "configured": _sheets_handler is not None,
        },
    }
    status = "ok" if llm_configured else "degraded"
    return JSONResponse(status_code=200, content={"status": status, "checks": checks})

USE_CASES = {
    uc.slug: uc
    for uc in (
        WaterTransferUseCase(),
        TankFillingUseCase(),
        PressureBoostingUseCase(),
        DewateringUseCase(),
        HeatCirculationUseCase(),
        DomesticHotWaterUseCase(),
    )
}

NEXT_QUESTION_FNS = {
    "water_transfer": water_transfer_next_question,
    "tank_filling": tank_filling_next_question,
    "pressure_boosting": pressure_boosting_next_question,
    "dewatering": dewatering_next_question,
    "heat_circulation": heat_circulation_next_question,
    "domestic_hot_water": domestic_hot_water_next_question,
}

QUESTIONS_BY_SLUG = {
    "water_transfer": {q.key: q for q in WATER_TRANSFER_QUESTIONS},
    "tank_filling": {q.key: q for q in TANK_FILLING_QUESTIONS},
    "pressure_boosting": {q.key: q for q in PRESSURE_BOOSTING_QUESTIONS},
    "dewatering": {q.key: q for q in DEWATERING_QUESTIONS},
    "heat_circulation": {q.key: q for q in HEAT_CIRCULATION_QUESTIONS},
    "domestic_hot_water": {q.key: q for q in DOMESTIC_HOT_WATER_QUESTIONS},
}

# Fixed-choice questions whose answer must be one of a small, exact set of
# strings that rules.py compares against literally - not free numeric input.
# Maps question_key -> (Question, valid category strings).
CATEGORY_QUESTIONS_BY_SLUG: dict[str, dict[str, tuple[Question, list[str]]]] = {
    "water_transfer": {
        "delivery_type": (DELIVERY_TYPE_QUESTION, ["ground_floor", "elevated_tank"]),
    },
    "tank_filling": {
        "inside_or_outside": (INSIDE_OR_OUTSIDE_QUESTION, ["inside", "outside"]),
        "horizontal_or_vertical": (HORIZONTAL_OR_VERTICAL_QUESTION, ["horizontal", "vertical"]),
    },
    "heat_circulation": {
        "heating_system": (HEATING_SYSTEM_QUESTION, ["ufh", "radiators"]),
    },
}


def _explain(reason_message: str, facts: dict) -> str:
    """Reword a rejection/fallback message; falls back to the raw message on any error."""
    try:
        return llm_explainer.explain_rejection(reason_message, facts)
    except Exception:
        logger.warning("explain_rejection failed, falling back to raw message: %r", reason_message)
        return reason_message


class AnswerRequest(BaseModel):
    question_key: str
    user_text: str
    previous_value: float | None = None
    previous_unit: str | None = None
    # The prior turn's suggested_value (see ParsedAnswer) for this same
    # question, when the prior reply was genuinely ambiguous - kept separate
    # from previous_value since it's unconfirmed and must not be silently
    # carried forward as if the user had already answered (see
    # pending_suggestion in llm_parser.parse_answer).
    pending_suggestion: float | None = None
    clarification_attempts: int = 0
    # TODO(frontend): drop once static/app.js sends clarification_attempts
    # instead of the old unit_ask_attempts name. Until then this silently
    # falling back to 0 on every request would mean the give-up mechanic in
    # llm_parser.parse_answer could never fire in production.
    unit_ask_attempts: int | None = None
    # Answers already collected so far this conversation (question_key ->
    # value), including categorical ones (delivery_type, inside_or_outside,
    # horizontal_or_vertical) that live outside this use case's own
    # QUESTIONS list. Optional/additive - omitting it just means the LLM
    # can't recognize a reply as referring back to one of those (see
    # locked_in_answers in llm_parser.parse_answer).
    answers_so_far: dict = {}


@app.post("/{use_case_slug}/answer", response_model=ParsedAnswer)
def parse_free_text_answer(use_case_slug: str, request: AnswerRequest) -> ParsedAnswer:
    questions = QUESTIONS_BY_SLUG.get(use_case_slug)
    if questions is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {use_case_slug}")
    question = questions.get(request.question_key)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Unknown question: {request.question_key}")
    other_questions = [q for key, q in questions.items() if key != request.question_key]
    clarification_attempts = (
        request.unit_ask_attempts if request.unit_ask_attempts is not None else request.clarification_attempts
    )
    # Only categorical answers outside this use case's own question list are
    # "locked in and uneditable" from parse_answer's point of view - answers
    # to questions IN the list are already covered by other_questions/redirect.
    category_questions = CATEGORY_QUESTIONS_BY_SLUG.get(use_case_slug, {})
    locked_in_answers = {
        key: value
        for key, value in request.answers_so_far.items()
        if key in category_questions and key != request.question_key
    }
    return llm_parser.parse_answer(
        question,
        request.user_text,
        previous_value=request.previous_value,
        previous_unit=request.previous_unit,
        pending_suggestion=request.pending_suggestion,
        other_questions=other_questions,
        clarification_attempts=clarification_attempts,
        locked_in_answers=locked_in_answers or None,
    )


class CategoryAnswerRequest(BaseModel):
    question_key: str
    user_text: str
    clarification_attempts: int = 0


@app.post("/{use_case_slug}/answer_category", response_model=ParsedCategory)
def parse_category_answer(use_case_slug: str, request: CategoryAnswerRequest) -> ParsedCategory:
    category_questions = CATEGORY_QUESTIONS_BY_SLUG.get(use_case_slug, {})
    entry = category_questions.get(request.question_key)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown categorical question for {use_case_slug}: {request.question_key}",
        )
    question, valid_categories = entry
    return llm_parser.parse_category(
        question, request.user_text, valid_categories, request.clarification_attempts
    )


class ExplainModelRequest(BaseModel):
    recommendation: PumpRecommendation
    user_question: str


class ExplainModelResponse(BaseModel):
    answer: str


@app.post("/explain_model", response_model=ExplainModelResponse)
def explain_model(request: ExplainModelRequest) -> ExplainModelResponse:
    return ExplainModelResponse(
        answer=llm_explainer.explain_model(request.recommendation, request.user_question)
    )


class NextQuestionRequest(BaseModel):
    answers: dict = {}


class NextQuestionResponse(BaseModel):
    question: Question | None = None


@app.post("/{use_case_slug}/next_question", response_model=NextQuestionResponse)
def get_next_question(use_case_slug: str, request: NextQuestionRequest) -> NextQuestionResponse:
    next_question_fn = NEXT_QUESTION_FNS.get(use_case_slug)
    if next_question_fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {use_case_slug}")
    return NextQuestionResponse(question=next_question_fn(request.answers))


class WaterTransferResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/water_transfer/recommend", response_model=WaterTransferResponse)
def water_transfer_recommend(request: WaterTransferRequest) -> WaterTransferResponse:
    resolved_num_floors = 0 if request.delivery_type == "ground_floor" else request.num_floors

    answers = {
        "delivery_type": request.delivery_type,
        "borewell_size": (request.borewell_size, request.borewell_unit),
        "well_depth": (request.well_depth, request.well_depth_unit),
        "motor_power_hp": request.motor_power_hp,
        "num_floors": resolved_num_floors,
        "roof_tank_capacity": request.roof_tank_capacity if resolved_num_floors > 0 else None,
    }

    uc = USE_CASES["water_transfer"]
    facts = {
        "delivery_type": request.delivery_type,
        "borewell_size": request.borewell_size,
        "borewell_unit": request.borewell_unit,
        "min_borewell_size_inch": MIN_BOREWELL_SIZE,
        "max_borewell_size_inch": MAX_BOREWELL_SIZE,
        "well_depth": request.well_depth,
        "well_depth_unit": request.well_depth_unit,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    well_depth_ft = normalize_well_depth(request.well_depth, request.well_depth_unit)
    target_head_m = water_transfer_calculate_head(well_depth_ft, resolved_num_floors)

    target_head = target_head_m if request.well_depth_unit == "m" else m_to_ft(target_head_m)
    head_unit = request.well_depth_unit

    confirm_oversize = request.confirm_oversize
    explicitly_declined = False
    if request.confirm_oversize_text is not None:
        try:
            confirm_oversize = llm_parser.parse_yes_no(request.confirm_oversize_text)
            explicitly_declined = not confirm_oversize
        except llm_parser.AmbiguousConfirmationError:
            # Text didn't resolve to a clear yes/no (guaranteed whenever no
            # LLM key is configured) - fall back to whatever confirm_oversize
            # was explicitly passed as, instead of forcing it to False and
            # silently discarding an explicit confirm_oversize=true.
            pass

    try:
        recommendation = uc.select_pump(answers)
    except BorewellTooSmallError as e:
        return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)
    except BorewellOversizeConfirmationRequired as e:
        if explicitly_declined:
            return WaterTransferResponse(
                status="rejected", message=_explain(OVERSIZE_DECLINE_MESSAGE, facts), target_head=target_head
            )
        if not confirm_oversize:
            return WaterTransferResponse(status="confirmation_required", message=_explain(str(e), facts))
        answers["borewell_size"] = (MAX_BOREWELL_SIZE, "inch")
        try:
            recommendation = uc.select_pump(answers)
        except NoModelAvailableError as e:
            return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)
    except NoModelAvailableError as e:
        return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    if request.well_depth_unit == "ft":
        recommendation.details["target_head"] = m_to_ft(recommendation.details["target_head"])
        recommendation.details["matched_head"] = m_to_ft(recommendation.details["matched_head"])
        recommendation.details["head_unit"] = "ft"
    else:
        recommendation.details["head_unit"] = "m"

    for alt in recommendation.tied_alternatives:
        if request.well_depth_unit == "ft":
            alt.details["target_head"] = m_to_ft(alt.details["target_head"])
            alt.details["matched_head"] = m_to_ft(alt.details["matched_head"])
            alt.details["head_unit"] = "ft"
        else:
            alt.details["head_unit"] = "m"

    return WaterTransferResponse(status="ok", recommendation=recommendation)


class TankFillingResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/tank_filling/recommend", response_model=TankFillingResponse)
def tank_filling_recommend(request: TankFillingRequest) -> TankFillingResponse:
    answers = {
        "inside_or_outside": request.inside_or_outside,
        "horizontal_or_vertical": request.horizontal_or_vertical,
        "tank_capacity": request.tank_capacity,
        "num_floors": request.num_floors,
        "motor_power_hp": request.motor_power_hp,
    }

    uc = USE_CASES["tank_filling"]
    facts = {
        "inside_or_outside": request.inside_or_outside,
        "tank_capacity": request.tank_capacity,
        "num_floors": request.num_floors,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    if request.inside_or_outside == "inside":
        facts["horizontal_or_vertical"] = request.horizontal_or_vertical
    target_head = tank_filling_calculate_head(request.num_floors)

    try:
        recommendation = uc.select_pump(answers)
    except NoTankFillingMatchError as e:
        return TankFillingResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    return TankFillingResponse(status="ok", recommendation=recommendation)


class PressureBoostingResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/pressure_boosting/recommend", response_model=PressureBoostingResponse)
def pressure_boosting_recommend(request: PressureBoostingRequest) -> PressureBoostingResponse:
    answers = {
        "num_floors": request.num_floors,
        "bathrooms_per_floor": request.bathrooms_per_floor,
    }

    uc = USE_CASES["pressure_boosting"]
    facts = {
        "num_floors": request.num_floors,
        "bathrooms_per_floor": request.bathrooms_per_floor,
    }
    target_head = pressure_boosting_calculate_head(request.num_floors)

    try:
        recommendation = uc.select_pump(answers)
    except NoPressureBoostingMatchError as e:
        return PressureBoostingResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    return PressureBoostingResponse(status="ok", recommendation=recommendation)


class DewateringResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/dewatering/recommend", response_model=DewateringResponse)
def dewatering_recommend(request: DewateringRequest) -> DewateringResponse:
    answers = {
        "depth_of_pit": (request.depth_of_pit, request.depth_of_pit_unit),
        "motor_power_hp": request.motor_power_hp,
    }

    uc = USE_CASES["dewatering"]
    facts = {
        "depth_of_pit": request.depth_of_pit,
        "depth_of_pit_unit": request.depth_of_pit_unit,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    depth_of_pit_ft = normalize_depth_of_pit(request.depth_of_pit, request.depth_of_pit_unit)
    target_head_m = dewatering_calculate_head(depth_of_pit_ft)
    target_head = target_head_m if request.depth_of_pit_unit == "m" else m_to_ft(target_head_m)

    try:
        recommendation = uc.select_pump(answers)
    except NoDewateringMatchError as e:
        return DewateringResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    if request.depth_of_pit_unit == "ft":
        recommendation.details["target_head"] = m_to_ft(recommendation.details["target_head"])
        recommendation.details["matched_head"] = m_to_ft(recommendation.details["matched_head"])
        recommendation.details["head_unit"] = "ft"
    else:
        recommendation.details["head_unit"] = "m"

    for alt in recommendation.tied_alternatives:
        if request.depth_of_pit_unit == "ft":
            alt.details["target_head"] = m_to_ft(alt.details["target_head"])
            alt.details["matched_head"] = m_to_ft(alt.details["matched_head"])
            alt.details["head_unit"] = "ft"
        else:
            alt.details["head_unit"] = "m"

    return DewateringResponse(status="ok", recommendation=recommendation)


class HeatCirculationResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    premium_recommendation: PumpRecommendation | None = None
    area_unit: str | None = None


@app.post("/heat_circulation/recommend", response_model=HeatCirculationResponse)
def heat_circulation_recommend(request: HeatCirculationRequest) -> HeatCirculationResponse:
    area_sqm = heat_circulation_normalize_area(request.total_area, request.area_unit)
    standard, premium = heat_circulation_build_recommendations(area_sqm, request.heating_system)

    for recommendation in (standard, premium):
        if recommendation is None:
            continue
        if request.area_unit == "sqft":
            recommendation.details["area"] = sqm_to_sqft(recommendation.details.pop("area_sqm"))
        else:
            recommendation.details["area"] = recommendation.details.pop("area_sqm")
        recommendation.details["area_unit"] = request.area_unit

    return HeatCirculationResponse(
        status="ok",
        recommendation=standard,
        premium_recommendation=premium,
        area_unit=request.area_unit,
    )


class DomesticHotWaterResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None


@app.post("/domestic_hot_water/recommend", response_model=DomesticHotWaterResponse)
def domestic_hot_water_recommend(request: DomesticHotWaterRequest) -> DomesticHotWaterResponse:
    uc = USE_CASES["domestic_hot_water"]
    answers = {"num_usage_points": request.num_usage_points}
    recommendation = uc.select_pump(answers)
    return DomesticHotWaterResponse(status="ok", recommendation=recommendation)


SEND_PUMP_DATA_URL = "https://wiloscan.pumpsearch.com/PumpManagement_V4/api/chatbot/send-selected-pump-mail"


@app.post("/send-pump-data")
async def send_pump_data(request: SendPumpDataRequest) -> dict:
    """Proxy pump/user data to the external pump-search API, avoiding browser CORS."""
    api_key = os.environ.get("SEND_PUMP_DATA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="SEND_PUMP_DATA_API_KEY is not configured")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SEND_PUMP_DATA_URL,
                json=request.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "X-API-KEY": api_key,
                },
                timeout=30,
            )
    except httpx.RequestError as e:
        logger.warning("send-pump-data: failed to reach external API: %r", e)
        raise HTTPException(status_code=502, detail=f"Failed to reach external API: {e}") from e

    try:
        body = response.json()
    except ValueError:
        body = response.text

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=body)

    return body


_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
