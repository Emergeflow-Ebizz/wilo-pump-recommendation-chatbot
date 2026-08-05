"""One-shot migration: load api/json_new/*.json into Postgres.

Run manually whenever json_new/ changes - never at app boot, since the
deployment's filesystem is read-only at runtime. json_new/*.json is only
ever read, never modified.

Usage (from the api/ directory):
    DATABASE_URL=postgresql://... python scripts/migrate_json_to_postgres.py

This is a full truncate-and-reload every run: json_new/ is the single source
of truth for this reference data, so the three catalog tables are wiped and
rebuilt inside one transaction rather than diffed/upserted. Any validation
failure rolls the whole transaction back, so the database is never left
half-migrated.
"""

import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from migrate_adapters import load_sheet_records

JSON_NEW_DIR = Path(__file__).resolve().parent.parent / "json_new"
SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    filenames = sorted(p.name for p in JSON_NEW_DIR.glob("*.json"))

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
            cur.execute("TRUNCATE pump_sheets CASCADE")

            for filename in filenames:
                records = load_sheet_records(JSON_NEW_DIR / filename)

                cur.execute(
                    "INSERT INTO pump_sheets (filename) VALUES (%s) RETURNING id",
                    (filename,),
                )
                sheet_id = cur.fetchone()[0]

                for record in records:
                    cur.execute(
                        """
                        INSERT INTO pump_models (sheet_id, model_name, phase, art_no, hp, kw, extra)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            sheet_id,
                            record.model_name,
                            record.phase,
                            record.art_no,
                            record.motor_rating.hp,
                            record.motor_rating.kw,
                            Jsonb(record.extra),
                        ),
                    )
                    model_id = cur.fetchone()[0]

                    for seq, point in enumerate(record.performance_curves):
                        cur.execute(
                            """
                            INSERT INTO pump_performance_points (model_id, flow, head, seq)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (model_id, point.flow, point.head, seq),
                        )

                print(f"{filename}: {len(records)} model(s) migrated")

        conn.commit()

    print(f"Done. Migrated {len(filenames)} sheet(s).")


if __name__ == "__main__":
    main()
