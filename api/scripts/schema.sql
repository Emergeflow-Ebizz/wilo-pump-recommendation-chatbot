-- Pump catalog schema. Run once against a fresh database (or re-run safely,
-- all statements are idempotent) before running migrate_json_to_postgres.py.

CREATE TABLE IF NOT EXISTS pump_sheets (
    id          SERIAL PRIMARY KEY,
    filename    TEXT UNIQUE NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pump_models (
    id         SERIAL PRIMARY KEY,
    sheet_id   INTEGER NOT NULL REFERENCES pump_sheets(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    phase      TEXT,
    art_no     TEXT,
    hp         NUMERIC,
    kw         NUMERIC,
    extra      JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (sheet_id, model_name, phase)
);
CREATE INDEX IF NOT EXISTS idx_pump_models_sheet ON pump_models(sheet_id);
CREATE INDEX IF NOT EXISTS idx_pump_models_extra ON pump_models USING GIN (extra);

CREATE TABLE IF NOT EXISTS pump_performance_points (
    id       SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES pump_models(id) ON DELETE CASCADE,
    flow     NUMERIC NOT NULL,
    head     NUMERIC NOT NULL,
    seq      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_perf_model ON pump_performance_points(model_id);
