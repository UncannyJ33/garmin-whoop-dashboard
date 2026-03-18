"""Migration 009 — Enable Row Level Security on all public tables.

Why: Supabase exposes a PostgREST REST API on every table by default.
Without RLS, anyone with the Supabase anon key can query raw tables directly,
bypassing the FastAPI auth layer.  Enabling RLS with no permissive policies
blocks all PostgREST access while leaving the FastAPI backend unaffected —
SQLAlchemy connects as the postgres / service role, which bypasses RLS.

PostgreSQL only — SQLite does not support RLS and is skipped.
Idempotent: ENABLE ROW LEVEL SECURITY is a no-op if already enabled.
"""

from sqlalchemy import Engine, text

from src.database.connection import get_engine

_TABLES = [
    "garmin_activities",
    "garmin_daily_summary",
    "garmin_exercise_sets",
    "garmin_hrv",
    "garmin_sleep",
    "sync_log",
    "token_store",
    "unified_daily",
    "unified_sleep",
    "unified_workouts",
    "users",
    "whoop_cycles",
    "whoop_recovery",
    "whoop_sleep",
    "whoop_workouts",
]


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    if engine is None:
        engine = get_engine(database_url)

    if engine.dialect.name == "sqlite":
        print("Migration 009: SQLite detected — RLS not supported, skipping")
        return

    print(f"Migration 009: enabling RLS on {len(_TABLES)} tables — {engine.url!s}")
    with engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            print(f"  ✓ RLS enabled on {table}")

    print(f"Migration 009: complete on {engine.url!s}")


if __name__ == "__main__":
    run()
