"""Migration 004 — create garmin_exercise_sets table.

Stores individual set-level data for strength training activities fetched
via the Garmin Connect exerciseSets endpoint.
Safe to run on an existing database: table is created only if absent.

Run directly:
    python -m src.database.migrations.004_exercise_sets
"""

from sqlalchemy import Engine

from src.database.connection import get_engine
from src.database.models import GarminExerciseSet


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the garmin_exercise_sets table if it doesn't already exist.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    GarminExerciseSet.__table__.create(engine, checkfirst=True)
    print(f"Migration 004: garmin_exercise_sets created on {engine.url}")


if __name__ == "__main__":
    run()
