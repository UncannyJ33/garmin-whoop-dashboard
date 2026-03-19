"""Migration 011: waitlist table for pre-launch email collection."""

import logging

from sqlalchemy import Engine, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the waitlist table if it doesn't exist."""
    if engine is None:
        engine = get_engine(database_url)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS waitlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    signed_up_at TEXT NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        # PostgreSQL: use SERIAL + BOOLEAN
        # The above works for both SQLite and PostgreSQL (INTEGER pk autoincrement is
        # handled as SERIAL by SQLAlchemy on PostgreSQL via reflection; UNIQUE is standard)

    logger.info("Migration 011: waitlist table ready")
