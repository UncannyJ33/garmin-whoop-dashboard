"""Migration 008: re-key the legacy Whoop token row to the per-user format.

Previous versions stored the Whoop OAuth token under the service key ``"whoop"``
with no user affiliation.  The new scheme uses ``"whoop_{user_id}"`` so each
user has an isolated token row.

This migration finds the first registered user (the owner) and, if a legacy
``"whoop"`` token row exists, renames it to ``"whoop_{owner_id}"`` and sets the
``user_id`` column so the new lookup logic finds it.

Idempotent: if the row has already been migrated (i.e. no ``"whoop"`` row
exists, or the owner-keyed row already exists), nothing is changed.
"""

from sqlalchemy import Engine, text

from src.database.connection import get_engine


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Run migration 008.

    Args:
        database_url: Optional override for the database URL.
        engine: Optional pre-built engine. Takes precedence over database_url.
    """
    if engine is None:
        engine = get_engine(database_url)

    dialect = engine.dialect.name
    print(f"Migration 008: running on {dialect} — {engine.url!s}")

    with engine.begin() as conn:
        # Check if the legacy "whoop" row exists
        legacy_row = conn.execute(
            text("SELECT service FROM token_store WHERE service = 'whoop'")
        ).one_or_none()

        if legacy_row is None:
            print("  ✓ No legacy 'whoop' token row — nothing to migrate")
            return

        # Look up the first registered user
        owner_row = conn.execute(
            text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")
        ).one_or_none()

        if owner_row is None:
            print("  ✓ No users registered yet — skipping token migration")
            return

        owner_id = str(owner_row[0])
        new_key = f"whoop_{owner_id}"

        # Check if new-format row already exists (idempotency guard)
        already_migrated = conn.execute(
            text("SELECT service FROM token_store WHERE service = :key"),
            {"key": new_key},
        ).one_or_none()

        if already_migrated is not None:
            print(f"  ✓ Token row '{new_key}' already exists — removing legacy 'whoop' row if present")
            conn.execute(text("DELETE FROM token_store WHERE service = 'whoop'"))
            return

        # Rename the legacy row to the new key and tag it with the owner's user_id
        conn.execute(
            text(
                "UPDATE token_store SET service = :new_key, user_id = :uid"
                " WHERE service = 'whoop'"
            ),
            {"new_key": new_key, "uid": owner_id},
        )
        print(f"  + Migrated token_store 'whoop' → '{new_key}' (user_id = {owner_id})")

    print(f"Migration 008: complete on {engine.url!s}")


if __name__ == "__main__":
    run()
