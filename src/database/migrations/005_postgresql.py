"""Migration 005 — PostgreSQL compatibility + user_id columns + indexes.

Idempotent: safe to run against SQLite (existing dev DB) or a fresh
PostgreSQL / Supabase instance.

What this migration does:
  1. Creates any tables that don't yet exist (create_all with checkfirst).
  2. Adds the app-level user_id (TEXT) column to every table that should
     have it, if the column is absent.
  3. Creates covering indexes on user_id and key timestamp/date columns
     where the index is not already present.

Run directly:
    python -m src.database.migrations.005_postgresql
"""

from sqlalchemy import Engine, inspect, text

from src.database.connection import get_engine
from src.database.models import Base

# Tables that should have an app-level user_id (TEXT, nullable).
# WhoopCycle is intentionally excluded — its user_id is Whoop's own integer
# platform user ID, already present from migration 001.
_TABLES_NEEDING_USER_ID = {
    "whoop_recovery",
    "whoop_sleep",
    "whoop_workouts",
    "garmin_activities",
    "garmin_exercise_sets",
    "garmin_daily_summary",
    "garmin_sleep",
    "garmin_hrv",
    "unified_daily",
    "unified_sleep",
    "unified_workouts",
    "sync_log",
    "token_store",
}

# Extra indexes to create (table_name → list of (index_name, [columns])).
# SQLAlchemy models already declare most of these via index=True on Column;
# this list covers any that need to be created explicitly on existing tables.
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_whoop_cycles_start_time", "whoop_cycles", ["start_time"]),
    ("ix_whoop_sleep_end_time", "whoop_sleep", ["end_time"]),
    ("ix_whoop_workouts_start_time", "whoop_workouts", ["start_time"]),
    ("ix_garmin_activities_start_time_gmt", "garmin_activities", ["start_time_gmt"]),
    ("ix_unified_workouts_date", "unified_workouts", ["date"]),
    ("ix_unified_workouts_start_time", "unified_workouts", ["start_time"]),
    # user_id indexes (covered by model index=True on new tables; belt-and-suspenders)
    ("ix_whoop_recovery_user_id", "whoop_recovery", ["user_id"]),
    ("ix_whoop_sleep_user_id", "whoop_sleep", ["user_id"]),
    ("ix_whoop_workouts_user_id", "whoop_workouts", ["user_id"]),
    ("ix_garmin_activities_user_id", "garmin_activities", ["user_id"]),
    ("ix_garmin_exercise_sets_user_id", "garmin_exercise_sets", ["user_id"]),
    ("ix_garmin_daily_summary_user_id", "garmin_daily_summary", ["user_id"]),
    ("ix_garmin_sleep_user_id", "garmin_sleep", ["user_id"]),
    ("ix_garmin_hrv_user_id", "garmin_hrv", ["user_id"]),
    ("ix_unified_daily_user_id", "unified_daily", ["user_id"]),
    ("ix_unified_sleep_user_id", "unified_sleep", ["user_id"]),
    ("ix_unified_workouts_user_id", "unified_workouts", ["user_id"]),
    ("ix_sync_log_user_id", "sync_log", ["user_id"]),
    ("ix_token_store_user_id", "token_store", ["user_id"]),
]


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def _add_column_if_missing(
    engine: Engine,
    inspector,
    table: str,
    column: str,
    col_type: str,
) -> None:
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {col_type}'))
    print(f"  + {table}.{column} added")


def _create_index_if_missing(
    engine: Engine,
    inspector,
    index_name: str,
    table: str,
    columns: list[str],
) -> None:
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
    if index_name in existing_indexes:
        return
    cols = ", ".join(f'"{c}"' for c in columns)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ({cols})'))
    print(f"  + index {index_name} created")


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Run migration 005.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    dialect = engine.dialect.name
    print(f"Migration 005: running on {dialect} — {engine.url!s}")

    # ── Step 1: create any missing tables ────────────────────────────────────
    Base.metadata.create_all(engine, checkfirst=True)
    print("  ✓ All tables present")

    # ── Step 2: add user_id column where missing ──────────────────────────────
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES_NEEDING_USER_ID:
        if table not in existing_tables:
            continue  # table was just created with the column already — skip
        _add_column_if_missing(engine, inspector, table, "user_id", "TEXT")

    # Refresh inspector after column additions
    inspector = inspect(engine)

    # ── Step 3: create indexes ────────────────────────────────────────────────
    for index_name, table, columns in _INDEXES:
        if table not in existing_tables:
            continue
        _create_index_if_missing(engine, inspector, index_name, table, columns)

    print(f"Migration 005: complete on {engine.url!s}")


if __name__ == "__main__":
    run()
