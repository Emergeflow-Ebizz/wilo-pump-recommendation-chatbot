"""Confirms the Postgres-backed catalog loader returns data identical to the
JSON-backed one for every file actually used by production rules.py logic
today. Requires DATABASE_URL to point at an instance already migrated via
scripts/migrate_json_to_postgres.py - skipped otherwise (e.g. local dev with
no database configured).
"""

import os

import pytest

from app.common import catalog_loader

# MHIL.json and Star.json are excluded: they're not consumed by any rules.py
# today and catalog_loader._load_sheet_from_json() itself can't parse them
# correctly (see scripts/migrate_adapters.py for why). WPO-3_Horizontal.json
# is excluded too: it has a model with an empty performance_curves list (a
# pre-existing data-quality issue, also unused by any rules.py today), which
# now fails catalog_schema validation - so there's no JSON-side baseline to
# compare the DB-side adapted data against for any of the three.
_EXCLUDED = {"MHIL.json", "Star.json", "WPO-3_Horizontal.json"}

HEALTHY_FILES = sorted(
    p.name for p in catalog_loader.JSON_NEW_DIR.glob("*.json") if p.name not in _EXCLUDED
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires DATABASE_URL pointing at a migrated Postgres instance",
)


@pytest.mark.parametrize("filename", HEALTHY_FILES)
def test_db_matches_json(filename):
    from app.common.db import load_sheet_from_db

    json_catalog = catalog_loader._load_sheet_from_json(filename)
    db_catalog = load_sheet_from_db(filename)

    assert set(json_catalog) == set(db_catalog), f"model set mismatch for {filename}"

    for model_name, json_model in json_catalog.items():
        db_model = db_catalog[model_name]
        assert db_model["art_no"] == json_model.get("art_no"), model_name
        assert db_model["phase"] == json_model.get("phase"), model_name
        assert db_model["motor_rating"]["hp"] == json_model["motor_rating"].get("hp"), model_name
        assert db_model["motor_rating"]["kw"] == json_model["motor_rating"].get("kw"), model_name
        assert db_model["performance_curves"] == json_model["performance_curves"], model_name
