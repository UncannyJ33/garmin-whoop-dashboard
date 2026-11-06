"""Migration 014: Create garmin_exercise_summaries table.

The Garmin Personal API has no per-set endpoint; strength activities carry
``summarizedExerciseSets`` (one row per exercise).  Old garmin_exercise_sets
rows are left in place.

Idempotent: checks if the table exists before creating.
"""

import logging

from sqlalchemy import Engine, inspect, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)

_TABLE = "garmin_exercise_summaries"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS garmin_exercise_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL REFERENCES garmin_activities(activity_id),
    exercise_category TEXT,
    exercise_name TEXT,
    set_count INTEGER,
    repetition_count INTEGER,
    volume_kg REAL,
    max_weight_kg REAL,
    duration_seconds REAL,
    fetched_at TEXT NOT NULL,
    user_id TEXT
)
"""

_CREATE_SQL_PG = """
CREATE TABLE IF NOT EXISTS garmin_exercise_summaries (
    id SERIAL PRIMARY KEY,
    activity_id TEXT NOT NULL REFERENCES garmin_activities(activity_id),
    exercise_category TEXT,
    exercise_name TEXT,
    set_count INTEGER,
    repetition_count INTEGER,
    volume_kg DOUBLE PRECISION,
    max_weight_kg DOUBLE PRECISION,
    duration_seconds DOUBLE PRECISION,
    fetched_at TEXT NOT NULL,
    user_id TEXT
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_garmin_exercise_summaries_activity_id "
    "ON garmin_exercise_summaries(activity_id)",
    "CREATE INDEX IF NOT EXISTS ix_garmin_exercise_summaries_user_id "
    "ON garmin_exercise_summaries(user_id)",
]


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    eng = engine or get_engine(database_url)
    is_pg = "postgresql" in str(eng.url)

    if _TABLE in inspect(eng).get_table_names():
        logger.info("Migration 014: %s already exists - skipping", _TABLE)
        return

    with eng.begin() as conn:
        conn.execute(text(_CREATE_SQL_PG if is_pg else _CREATE_SQL))
        for idx_sql in _INDEX_SQL:
            conn.execute(text(idx_sql))

    logger.info("Migration 014: %s table created", _TABLE)
