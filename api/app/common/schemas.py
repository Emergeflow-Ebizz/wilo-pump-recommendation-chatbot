import math

from pydantic import BaseModel, Field, field_validator


def _require_finite(v: float | None) -> float | None:
    if v is not None and not math.isfinite(v):
        raise ValueError("must be a finite number")
    return v


def _normalize_unit(v: str | None) -> str | None:
    return v.strip().lower() if v is not None else v


class Question(BaseModel):
    key: str
    prompt: str
    unit: str | None = None
    optional: bool = False
    allowed_units: list[str] | None = None
    requires_stated_unit: bool = False
    requires_integer: bool = False
    min_value: float | None = None
    domain_context: str = ""


class WaterTransferRequest(BaseModel):
    delivery_type: str
    borewell_size: float = Field(gt=0)
    borewell_unit: str
    well_depth: float = Field(gt=0)
    well_depth_unit: str
    motor_power_hp: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    roof_tank_capacity: float | None = Field(default=None, gt=0)
    confirm_oversize: bool = False
    confirm_oversize_text: str | None = None

    _validate_borewell_size_finite = field_validator("borewell_size")(_require_finite)
    _validate_well_depth_finite = field_validator("well_depth")(_require_finite)
    _validate_motor_power_hp_finite = field_validator("motor_power_hp")(_require_finite)
    _validate_roof_tank_capacity_finite = field_validator("roof_tank_capacity")(_require_finite)
    _normalize_borewell_unit = field_validator("borewell_unit")(_normalize_unit)
    _normalize_well_depth_unit = field_validator("well_depth_unit")(_normalize_unit)
    _normalize_delivery_type = field_validator("delivery_type")(_normalize_unit)

    @field_validator("delivery_type")
    @classmethod
    def validate_delivery_type(cls, v):
        if v not in ("ground_floor", "elevated_tank"):
            raise ValueError('delivery_type must be "ground_floor" or "elevated_tank"')
        return v

    @field_validator("num_floors")
    @classmethod
    def validate_num_floors(cls, v, info):
        if info.data.get("delivery_type") == "elevated_tank" and v < 1:
            raise ValueError("num_floors must be at least 1 for elevated_tank delivery")
        return v


class TankFillingRequest(BaseModel):
    inside_or_outside: str
    horizontal_or_vertical: str | None = None
    tank_capacity: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    motor_power_hp: float | None = Field(default=None, gt=0)

    _validate_tank_capacity_finite = field_validator("tank_capacity")(_require_finite)
    _validate_motor_power_hp_finite = field_validator("motor_power_hp")(_require_finite)
    _normalize_inside_or_outside = field_validator("inside_or_outside")(_normalize_unit)
    _normalize_horizontal_or_vertical = field_validator("horizontal_or_vertical")(_normalize_unit)

    @field_validator("inside_or_outside")
    @classmethod
    def validate_inside_or_outside(cls, v):
        if v not in ("inside", "outside"):
            raise ValueError('inside_or_outside must be "inside" or "outside"')
        return v

    @field_validator("horizontal_or_vertical")
    @classmethod
    def validate_horizontal_or_vertical(cls, v):
        if v is not None and v not in ("horizontal", "vertical"):
            raise ValueError('horizontal_or_vertical must be "horizontal" or "vertical"')
        return v


class PressureBoostingRequest(BaseModel):
    num_floors: int = Field(ge=1)
    bathrooms_per_floor: int = Field(ge=1)


class DewateringRequest(BaseModel):
    depth_of_pit: float = Field(gt=0)
    depth_of_pit_unit: str
    motor_power_hp: float | None = Field(default=None, gt=0)

    _validate_depth_of_pit_finite = field_validator("depth_of_pit")(_require_finite)
    _validate_motor_power_hp_finite = field_validator("motor_power_hp")(_require_finite)
    _normalize_depth_of_pit_unit = field_validator("depth_of_pit_unit")(_normalize_unit)


class PumpRecommendation(BaseModel):
    model_name: str
    art_no: int | None = None
    details: dict = {}
    features: list[str] | None = None
    tied_alternatives: list["PumpRecommendation"] = []


class AdditionalAnswer(BaseModel):
    """A value the user volunteered for a DIFFERENT question than the one
    they were just asked, extracted from the same reply as the primary
    answer (e.g. "value unit borewell, value unit deep, number floors" answers
    borewell_size AND well_depth AND num_floors in one message).

    Unlike redirect_key (which fires when the reply does NOT answer the
    current question at all), additional_answers coexist with a normal
    primary value/unit - the current question's own answer is unaffected.
    """

    key: str
    value: float
    unit: str | None = None


class ParsedAnswer(BaseModel):
    value: float | None = None
    unit: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    redirect_key: str | None = None
    gave_up: bool = False
    confirmation_message: str | None = None
    additional_answers: list[AdditionalAnswer] = []
    edit_not_supported: bool = False


class ParsedCategory(BaseModel):
    category: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    confirmation_message: str | None = None
    gave_up: bool = False


class PumpDataUserDetails(BaseModel):
    pincode: str
    name: str
    contactNumber: str
    email: str


class PumpDataSearchDetails(BaseModel):
    application: str
    RequiredHead: str
    RequiredPower: str


class PumpDataSelectedPump(BaseModel):
    pumpModel: str
    articleNo: str
    motorRating: str
    selectedHead: str
    selectedFlow: str
    features: str


class PumpDataPayload(BaseModel):
    userDetails: PumpDataUserDetails
    searchDetails: PumpDataSearchDetails
    selectedPump: PumpDataSelectedPump


class SendPumpDataRequest(BaseModel):
    data: PumpDataPayload
