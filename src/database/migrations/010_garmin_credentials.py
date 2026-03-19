"""Migration 010: garmin_credentials table.

Stores encrypted Garmin credentials for users who opt into auto-sync.
Credentials are encrypted at rest using Fernet (see src/auth/encryption.py).
The raw email and password are NEVER stored.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Create the garmin_credentials table if it does not already exist."""
    if engine is None:
        from src.database.connection import get_engine

        engine = get_engine(database_url)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS garmin_credentials (
                    user_id          TEXT PRIMARY KEY,
                    encrypted_email  TEXT NOT NULL,
                    encrypted_password TEXT NOT NULL,
                    auto_sync_enabled INTEGER NOT NULL DEFAULT 1,
                    consent_given_at TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                )
                """
            )
        )

    logger.info("Migration 010: garmin_credentials table ready")
