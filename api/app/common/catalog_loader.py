import json
import os
import re
from functools import lru_cache
from pathlib import Path

from app.common.catalog_schema import validate_sheet

JSON_NEW_DIR = Path(__file__).resolve().parent.parent.parent / "json_new"

_PHASE_KEY_RE = re.compile(r"^phase_\d+$")


@lru_cache(maxsize=None)
def load_sheet(filename: str) -> dict:
    """Load one model-family file from json_new/, flattened to {model_name: {...}}.

    Some sheets wrap models under one or more top-level phase_1/phase_3 keys
    (single-phase vs three-phase motor variants); this merges them all into
    one flat dict so callers never need to know about the wrapper, tagging
    each model with a "phase" field (e.g. "phase_1") so that information
    isn't lost. Flat sheets get "phase": None since they have no such concept.

    Validated against catalog_schema before being returned - a malformed
    manual edit to the file (e.g. a missing motor_rating.hp or an emptied
    performance_curves list) raises CatalogValidationError here rather than
    silently reaching rules.py and producing a wrong recommendation.
    """
    path = JSON_NEW_DIR / filename
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if data and all(_PHASE_KEY_RE.match(key) for key in data):
        merged = {}
        for phase_name, phase_models in data.items():
            for model_name, model in phase_models.items():
                merged[model_name] = {**model, "phase": phase_name}
        validate_sheet(filename, merged)
        return merged

    flattened = {name: {**model, "phase": None} for name, model in data.items()}
    validate_sheet(filename, flattened)
    return flattened
