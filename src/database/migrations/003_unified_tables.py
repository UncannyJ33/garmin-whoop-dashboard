"""Migration 003 — create unified tables.

Adds unified_daily, unified_sleep, and unified_workouts.
Safe to run on an existing database: each table is created only if absent.

Run directly:
    python -m src.database.migrations.003_unified_tables
"""

from sqlalchemy import Engine

from src.database.connection import get_engine
from src.database.models import (
    UnifiedDaily,
    UnifiedSleep,
    UnifiedWorkout,
)

_UNIFIED_TABLES = [
    UnifiedDaily.__table__,
    UnifiedSleep.__table__,
    UnifiedWorkout.__table__,
]


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the three unified tables if they don't already exist.

    Args:
        database_url: Optional override for the database URL. Uses the value
            from config/settings.py when not provided.
        engine: Optional pre-built engine to use directly. Takes precedence
            over database_url. Useful for sharing an in-memory engine in tests.
    """
    if engine is None:
        engine = get_engine(database_url)

    for table in _UNIFIED_TABLES:
        table.create(engine, checkfirst=True)

    print(f"Migration 003: Unified tables created on {engine.url}")


if __name__ == "__main__":
    run()
