"""Migration 012 — Add composite indexes for user_id + date/start_time queries.

Why: Nearly every analytics query filters by both user_id AND a date column.
With only single-column indexes, PostgreSQL must use one index and filter
in-memory for the second column. Composite indexes let both conditions be
satisfied in a single index scan.

PostgreSQL only — SQLite does not benefit meaningfully from composite indexes
at our data volumes and is skipped.

Idempotent: checks pg_indexes before CREATE INDEX to avoid errors on re-run.
Uses CREATE INDEX (not CONCURRENTLY) since migrations run during deploy
startup when no traffic is hitting the tables.
"""

import logging

from sqlalchemy import Engine, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)

_INDEXES = [
    ("idx_unified_daily_user_date", "unified_daily", "user_id, date"),
    ("idx_unified_sleep_user_date", "unified_sleep", "user_id, date"),
    ("idx_unified_workouts_user_date", "unified_workouts", "user_id, date"),
    ("idx_unified_workouts_user_start", "unified_workouts", "user_id, start_time"),
    ("idx_whoop_cycles_user_start", "whoop_cycles", "user_id, start_time"),
    ("idx_whoop_workouts_user_start", "whoop_workouts", "user_id, start_time"),
    ("idx_whoop_sleep_user_end", "whoop_sleep", "user_id, end_time"),
    ("idx_garmin_activities_user_start", "garmin_activities", "user_id, start_time_gmt"),
    ("idx_garmin_daily_user_date", "garmin_daily_summary", "user_id, date"),
    ("idx_garmin_sleep_user_date", "garmin_sleep", "user_id, date"),
]


def _index_exists(conn, index_name: str, dialect: str) -> bool:
    """Check whether an index already exists."""
    if dialect == "postgresql":
        row = conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
            {"name": index_name},
        ).one_or_none()
        return row is not None
    # SQLite
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='index' AND name = :name"),
        {"name": index_name},
    ).one_or_none()
    return row is not None


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    if engine is None:
        engine = get_engine(database_url)

    if engine.dialect.name == "sqlite":
        logger.info("012_composite_indexes: skipping — SQLite (not needed at current scale)")
        return

    created = 0
    skipped = 0

    with engine.begin() as conn:
        for idx_name, table, columns in _INDEXES:
            if _index_exists(conn, idx_name, engine.dialect.name):
                skipped += 1
                continue
            sql = f"CREATE INDEX {idx_name} ON {table} ({columns})"
            conn.execute(text(sql))
            created += 1
            logger.info("012: created index %s on %s(%s)", idx_name, table, columns)

    logger.info("012_composite_indexes: %d created, %d already existed", created, skipped)
