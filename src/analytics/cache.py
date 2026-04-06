"""In-memory TTL cache for expensive analytics computations.

Readiness scores and weekly summaries are computed from multiple DB queries +
statistical computation, but the underlying data only changes on sync
(every 15–30 min).  This cache eliminates redundant computation when users
refresh the page, navigate back, or open multiple tabs.

The cache is per-process (not shared across workers), keyed by
``(user_id, function_name, *args)``, and entries expire after ``DEFAULT_TTL``
seconds.  It is explicitly invalidated when a sync completes.

Usage in route handlers::

    from src.analytics.cache import analytics_cache

    cached = analytics_cache.get(user_id, "readiness", date_str)
    if cached is not None:
        return cached
    result = compute_readiness(...)
    analytics_cache.set(user_id, "readiness", date_str, value=result)
"""

from __future__ import annotations

import logging
import time
import threading

logger = logging.getLogger(__name__)

DEFAULT_TTL = 300  # 5 minutes — matches sync interval


class AnalyticsCache:
    """Thread-safe in-memory TTL cache for analytics results."""

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._store: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _key(self, user_id: str, fn: str, *args: str) -> tuple:
        return (user_id, fn, *args)

    def get(self, user_id: str, fn: str, *args: str) -> object | None:
        """Return cached value if present and not expired, else None."""
        key = self._key(user_id, fn, *args)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, user_id: str, fn: str, *args: str, value: object) -> None:
        """Store a value with the current timestamp."""
        key = self._key(user_id, fn, *args)
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def invalidate_user(self, user_id: str) -> int:
        """Remove all cached entries for a user.  Returns count removed."""
        with self._lock:
            keys = [k for k in self._store if k[0] == user_id]
            for k in keys:
                del self._store[k]
        if keys:
            logger.debug("analytics_cache: invalidated %d entries for user %s", len(keys), user_id)
        return len(keys)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()


# Module-level singleton — shared across the FastAPI process
analytics_cache = AnalyticsCache()
