"""Migration 015 — add users.sleep_target_minutes (server-side sleep target).

On a fresh database migration 006 creates ``users`` from the ``User`` model, which
already has the column, so this is a no-op. ``create_all`` never adds columns to an
existing table, so a database created before 015 needs the ALTER. Same SQL on SQLite
and PostgreSQL; idempotent.

Run directly:
    python -m src.database.migrations.015_user_sleep_target
"""

import logging

from sqlalchemy import Engine, inspect, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)

_COLUMN = "sleep_target_minutes"


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Add ``users.sleep_target_minutes INTEGER NOT NULL DEFAULT 480`` if missing.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        logger.info("Migration 015: users table absent; skipping")
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns("users")}:
        logger.info("Migration 015: users.%s already present", _COLUMN)
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE users ADD COLUMN {_COLUMN} INTEGER NOT NULL DEFAULT 480"))
    print(f"Migration 015: users.{_COLUMN} added")


if __name__ == "__main__":
    run()
