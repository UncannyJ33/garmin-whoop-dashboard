"""Migration 007: add app_user_id to whoop_cycles.

The whoop_cycles table previously only had a Whoop-platform integer user_id.
This migration adds ``app_user_id`` (TEXT, nullable) to store the *application*
user UUID for multi-tenancy, matching the pattern used by all other tables.

Idempotent: safe to run multiple times on both SQLite and PostgreSQL.
"""

from sqlalchemy import Engine, inspect, text

from src.database.connection import get_engine


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Run migration 007.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    dialect = engine.dialect.name
    print(f"Migration 007: running on {dialect} — {engine.url!s}")

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # ── Add app_user_id to whoop_cycles ──────────────────────────────────────
    if "whoop_cycles" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("whoop_cycles")}
        if "app_user_id" not in existing_cols:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE "whoop_cycles" ADD COLUMN app_user_id TEXT'))
            print("  + whoop_cycles.app_user_id added")
        else:
            print("  ✓ whoop_cycles.app_user_id already present")

        # Refresh inspector after potential column addition
        inspector = inspect(engine)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("whoop_cycles")}
        if "ix_whoop_cycles_app_user_id" not in existing_indexes:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        'CREATE INDEX IF NOT EXISTS "ix_whoop_cycles_app_user_id"'
                        ' ON "whoop_cycles" (app_user_id)'
                    )
                )
            print("  + index ix_whoop_cycles_app_user_id created")
        else:
            print("  ✓ index ix_whoop_cycles_app_user_id already present")

    print(f"Migration 007: complete on {engine.url!s}")


if __name__ == "__main__":
    run()
