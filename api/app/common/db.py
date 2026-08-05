"""Postgres-backed catalog reads, used by catalog_loader.load_sheet() once
DATABASE_URL is configured. See scripts/migrate_json_to_postgres.py for how
json_new/*.json gets into these tables in the first place.
"""

import os
from functools import lru_cache

import psycopg


def _connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def _as_art_no(value: str | None) -> int | str | None:
    """art_no is stored as TEXT (a couple of source files use non-numeric IDs),
    but every existing rules.py caller expects the int it originally read
    from JSON, so convert back whenever the value is purely numeric."""
    if value is not None and value.lstrip("-").isdigit():
        return int(value)
    return value


@lru_cache(maxsize=None)
def load_sheet_from_db(filename: str) -> dict:
    """DB-backed equivalent of catalog_loader._load_sheet_from_json(): returns
    the same {model_name: {art_no, motor_rating: {hp, kw}, phase,
    performance_curves, **extra}} shape, reassembled from pump_models and
    pump_performance_points.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.model_name, m.phase, m.art_no, m.hp, m.kw, m.extra
            FROM pump_models m
            JOIN pump_sheets s ON s.id = m.sheet_id
            WHERE s.filename = %s
            """,
            (filename,),
        )
        rows = cur.fetchall()

        model_ids = [row[0] for row in rows]
        points_by_model: dict[int, list[dict]] = {model_id: [] for model_id in model_ids}
        if model_ids:
            cur.execute(
                """
                SELECT model_id, flow, head
                FROM pump_performance_points
                WHERE model_id = ANY(%s)
                ORDER BY model_id, seq
                """,
                (model_ids,),
            )
            for model_id, flow, head in cur.fetchall():
                points_by_model[model_id].append({"flow": float(flow), "head": float(head)})

        result = {}
        for model_id, model_name, phase, art_no, hp, kw, extra in rows:
            result[model_name] = {
                **extra,
                "art_no": _as_art_no(art_no),
                "motor_rating": {
                    "hp": float(hp) if hp is not None else None,
                    "kw": float(kw) if kw is not None else None,
                },
                "phase": phase,
                "performance_curves": points_by_model[model_id],
            }
        return result
