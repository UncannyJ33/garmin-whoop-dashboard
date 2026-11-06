"""Single-owner helper: this deployment has exactly one ``users`` row."""

from sqlalchemy import Engine, text


def get_owner_user_id(engine: Engine) -> str | None:
    """Return the id of the single user, or ``None`` when no user exists.

    Raises:
        RuntimeError: if more than one user exists (misconfiguration; the
            deployment is single-owner).
    """
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 2")).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise RuntimeError("Expected exactly one owner user but found more than one")
    return str(rows[0][0])
