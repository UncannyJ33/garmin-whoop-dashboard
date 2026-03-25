"""Migration 011: waitlist table for pre-launch email collection."""

import logging

from sqlalchemy import Engine, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the waitlist table if it doesn't exist."""
    if engine is None:
        engine = get_engine(database_url)

    is_postgresql = engine.dialect.name == "postgresql"

    with engine.begin() as conn:
        if is_postgresql:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS waitlist (
                        id SERIAL PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        signed_up_at TEXT NOT NULL,
                        notified BOOLEAN NOT NULL DEFAULT FALSE
                    )
                    """
                )
            )
            already_enabled = conn.execute(
                text(
                    "SELECT 1 FROM pg_class "
                    "WHERE relname = 'waitlist' "
                    "AND relnamespace = 'public'::regnamespace "
                    "AND relrowsecurity = true"
                )
            ).fetchone()
            if not already_enabled:
                conn.execute(text('ALTER TABLE "waitlist" ENABLE ROW LEVEL SECURITY'))
                logger.info("Migration 011: RLS enabled on waitlist")
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS waitlist (
                        id INTEGER PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        signed_up_at TEXT NOT NULL,
                        notified INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            )

    logger.info("Migration 011: waitlist table ready")
