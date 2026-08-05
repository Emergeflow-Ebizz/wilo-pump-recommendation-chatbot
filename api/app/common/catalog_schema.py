"""Validation for the pump catalog data in json_new/, independent of the
Postgres migration (scripts/migrate_adapters.py) - this stays even if that
gets removed.

Used by catalog_loader (fails loudly the moment a malformed file is loaded)
and by tests/test_catalog_validation.py (catches a bad manual edit before
it's merged). Only covers the shape every use case's rules.py actually
depends on - motor_rating.hp/kw and a non-empty performance_curves list -
not the extra informational fields (delivery_mm, rated_current_a, etc.)
that vary by file and are never read by rule logic.
"""

from pydantic import BaseModel, field_validator


class CatalogValidationError(Exception):
    """Raised when a json_new/*.json file doesn't match the shape rules.py
    depends on - e.g. a missing/malformed motor_rating.hp, or an empty or
    malformed performance_curves list. Deliberately left uncaught by
    catalog_loader: a malformed catalog file must fail loudly at load time,
    not silently produce a wrong pump recommendation.
    """


class _PerfPoint(BaseModel):
    flow: float
    head: float


class _MotorRating(BaseModel):
    hp: float
    kw: float | None = None


class _CatalogModel(BaseModel):
    performance_curves: list[_PerfPoint]
    motor_rating: _MotorRating

    @field_validator("performance_curves")
    @classmethod
    def _non_empty(cls, value):
        if not value:
            raise ValueError("performance_curves must not be empty")
        return value


def validate_sheet(filename: str, flattened: dict) -> None:
    """Validate every model in an already-flattened {model_name: {...}} dict
    (as returned by catalog_loader._load_sheet_from_json). Raises
    CatalogValidationError naming the offending model on the first problem
    found.
    """
    for model_name, model in flattened.items():
        try:
            _CatalogModel(
                performance_curves=model.get("performance_curves"),
                motor_rating=model.get("motor_rating"),
            )
        except Exception as e:
            raise CatalogValidationError(
                f"{filename}: model {model_name!r} failed validation: {e}"
            ) from e
