"""Migration 001 — create all Phase 1 tables.

Run this script directly to initialise a fresh database:

    python -m src.database.migrations.001_initial
"""

from sqlalchemy import Engine

from src.database.connection import get_engine
from src.database.models import Base


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create all tables if they don't already exist.

    Args:
        database_url: Optional override for the database URL. Uses the value
            from config/settings.py when not provided.
        engine: Optional pre-built engine to use directly. Takes precedence
            over database_url. Useful for sharing an in-memory engine in tests.
    """
    if engine is None:
        engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    print(f"Migration 001: tables created on {engine.url}")


if __name__ == "__main__":
    run()
