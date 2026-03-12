"""Migration 006 — create users table for JWT-based authentication.

Safe to run on an existing database: table is created only if absent.

Run directly:
    python -m src.database.migrations.006_users_table
"""

from sqlalchemy import Engine

from src.auth.models import User
from src.database.connection import get_engine


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the users table if it doesn't already exist.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    User.__table__.create(engine, checkfirst=True)
    print(f"Migration 006: users table created on {engine.url}")


if __name__ == "__main__":
    run()
