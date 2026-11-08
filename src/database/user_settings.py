"""Per-user settings stored on the ``users`` row (currently the sleep target)."""

from sqlalchemy import Engine, text


def get_sleep_target_minutes(engine: Engine, user_id: str) -> int:
    """Return the user's nightly sleep target in minutes.

    Raises:
        LookupError: If there is no users row for ``user_id``.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT sleep_target_minutes FROM users WHERE id = :uid"), {"uid": user_id}
        ).fetchone()
    if row is None:
        raise LookupError(f"No user {user_id!r}")
    return int(row[0])


def set_sleep_target_minutes(engine: Engine, user_id: str, minutes: int) -> None:
    """Set the user's nightly sleep target in minutes.

    Raises:
        LookupError: If there is no users row for ``user_id``.
    """
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET sleep_target_minutes = :m WHERE id = :uid"),
            {"m": minutes, "uid": user_id},
        )
    if result.rowcount == 0:
        raise LookupError(f"No user {user_id!r}")
