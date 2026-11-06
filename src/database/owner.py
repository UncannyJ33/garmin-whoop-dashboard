"""Single-owner helper: this deployment has exactly one ``users`` row."""

import time

from sqlalchemy import Engine, text

_OWNER_CACHE_TTL_SECONDS = 60.0
_owner_cache: tuple[str, float] | None = None


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


def get_owner_user_id_cached(engine: Engine) -> str | None:
    """Return the owner id, cached for 60 s; only a non-``None`` result is cached.

    ``None`` (no users yet) is re-queried on every call so an owner created by a
    separate process is picked up without a restart.

    Raises:
        RuntimeError: if more than one user exists.
    """
    global _owner_cache
    now = time.monotonic()
    cached = _owner_cache
    if cached is not None and now < cached[1]:
        return cached[0]
    owner_id = get_owner_user_id(engine)
    if owner_id is not None:
        _owner_cache = (owner_id, now + _OWNER_CACHE_TTL_SECONDS)
    return owner_id


def clear_owner_cache() -> None:
    """Drop the cached owner id (tests, and after creating the owner in-process)."""
    global _owner_cache
    _owner_cache = None
