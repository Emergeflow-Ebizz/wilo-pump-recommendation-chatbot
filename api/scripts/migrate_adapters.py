"""Per-file parsing/adaptation logic used by migrate_json_to_postgres.py.

Most files in json_new/ share a common shape once flattened: {model_name:
{art_no, motor_rating: {hp, kw}, performance_curves: [{flow, head}], phase}}.
MHIL.json and Star.json don't, so they get bespoke adapters that normalize
them into the same shape before validation. json_new/*.json is only ever
read here, never modified.
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel


class PerfPoint(BaseModel):
    flow: float
    head: float


class MotorRating(BaseModel):
    hp: float | None = None
    kw: float | None = None


class CatalogModelRecord(BaseModel):
    model_name: str
    phase: str | None = None
    art_no: str | None = None
    motor_rating: MotorRating = MotorRating()
    performance_curves: list[PerfPoint] = []
    extra: dict = {}


_PHASE_KEY_RE = re.compile(r"^phase_\d+$")
_KNOWN_KEYS = {"art_no", "motor_rating", "performance_curves", "phase"}


def _to_records(flattened: dict) -> list[CatalogModelRecord]:
    records = []
    for model_name, model in flattened.items():
        extra = {k: v for k, v in model.items() if k not in _KNOWN_KEYS}
        art_no = model.get("art_no")
        records.append(
            CatalogModelRecord(
                model_name=model_name,
                phase=model.get("phase"),
                art_no=str(art_no) if art_no is not None else None,
                motor_rating=MotorRating(**model.get("motor_rating", {})),
                performance_curves=model.get("performance_curves", []),
                extra=extra,
            )
        )
    return records


def load_standard_sheet(path: Path) -> list[CatalogModelRecord]:
    """Flat {model_name: {...}} or phase_1/phase_3-wrapped sheets whose models
    already carry a performance_curves list - i.e. every file except MHIL.json
    and Star.json. Mirrors catalog_loader.load_sheet()'s flatten logic."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if data and all(_PHASE_KEY_RE.match(key) for key in data):
        flattened = {
            name: {**model, "phase": phase}
            for phase, models in data.items()
            for name, model in models.items()
        }
    else:
        flattened = {name: {**model, "phase": None} for name, model in data.items()}

    return _to_records(flattened)


def adapt_mhil(path: Path) -> list[CatalogModelRecord]:
    """MHIL.json is phase_1/phase_3-wrapped like a standard sheet, but each
    model has a discharge_lpm: {"<head>": flow} dict instead of a
    performance_curves list. Convert it to the common shape before validating.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    flattened = {}
    for phase, models in data.items():
        for name, model in models.items():
            discharge_lpm = model["discharge_lpm"]
            performance_curves = [
                {"head": float(head), "flow": float(flow)}
                for head, flow in sorted(discharge_lpm.items(), key=lambda kv: float(kv[0]))
            ]
            rest = {k: v for k, v in model.items() if k != "discharge_lpm"}
            flattened[name] = {**rest, "performance_curves": performance_curves, "phase": phase}

    return _to_records(flattened)


def _numbers(value: str | None) -> list[float]:
    return [float(n) for n in re.findall(r"[\d.]+", value)] if value is not None else []


def _split_variants(value: str | None) -> list[float] | None:
    """Parse a '6/5/4' or '1 max.' style string into a list of numbers."""
    numbers = _numbers(value)
    return numbers or None


def _split_range(value: str | None) -> dict | None:
    """Parse a '40-64' style range string into {"min": 40.0, "max": 64.0}."""
    numbers = _numbers(value)
    if len(numbers) != 2:
        return {"raw": value} if value is not None else None
    return {"min": min(numbers), "max": max(numbers)}


def adapt_star(path: Path) -> list[CatalogModelRecord]:
    """Star.json mixes flat direct-model keys with a nested "pump_models" key
    holding more models under a different field-naming scheme; none of them
    have real flow/head performance data (only summary strings). Split into
    two source groups, parse range/triplet strings into extra, and leave
    performance_curves empty - the DB loader must treat that as a normal
    empty list, not an error.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    records = []

    direct = {k: v for k, v in data.items() if k != "pump_models"}
    for name, model in direct.items():
        extra = dict(model)
        art_no = extra.pop("article_number", None)
        extra["source_group"] = "direct"
        extra["total_head_variants_m"] = _split_variants(extra.pop("total_head_m__high_medium_low", None))
        extra["max_flow_variants_lpm"] = _split_variants(extra.pop("max_flow_lpm__high_medium_low", None))
        records.append(
            CatalogModelRecord(
                model_name=name,
                phase=None,
                art_no=str(art_no) if art_no is not None else None,
                motor_rating=MotorRating(),
                performance_curves=[],
                extra=extra,
            )
        )

    for name, model in data.get("pump_models", {}).items():
        extra = dict(model)
        art_no = extra.pop("article_no", None)
        hp = extra.pop("hp", None)
        kw = extra.pop("kw", None)
        extra["source_group"] = "pump_models"
        extra["duty_range_flow_lpm"] = _split_range(extra.pop("duty_range_flow_lpm", None))
        extra["duty_range_head_m"] = _split_range(extra.pop("duty_range_head_m", None))
        records.append(
            CatalogModelRecord(
                model_name=name,
                phase=None,
                art_no=str(art_no) if art_no is not None else None,
                motor_rating=MotorRating(hp=hp, kw=kw),
                performance_curves=[],
                extra=extra,
            )
        )

    return records


ADAPTERS = {
    "MHIL.json": adapt_mhil,
    "Star.json": adapt_star,
}


def load_sheet_records(path: Path) -> list[CatalogModelRecord]:
    adapter = ADAPTERS.get(path.name)
    if adapter:
        return adapter(path)
    return load_standard_sheet(path)
