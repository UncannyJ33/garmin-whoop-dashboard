from collections.abc import Generator
from datetime import date

from fastapi import HTTPException, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config.settings import settings
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations

_engine = get_engine()
# For SQLite (local dev without start.sh), run migrations at import time.
# For PostgreSQL (production), scripts/start.sh already ran migrations before
# uvicorn started — running them again adds ~8 extra connections at startup.
if settings.database_url.startswith("sqlite"):
    run_migrations(engine=_engine)
_SessionLocal = get_session_factory(_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine_dep() -> Engine:
    """FastAPI dependency returning the shared SQLAlchemy engine.

    Analytics modules take Engine directly; this avoids creating a new
    engine per request.
    """
    return _engine


class DateRangeParams:
    """Required ``start``/``end`` query params (YYYY-MM-DD) shared by range routes.

    Ordering is checked by :meth:`validated` inside the route body (not at
    dependency resolution) so 401/422 responses keep their original precedence.
    """

    def __init__(
        self,
        start: date = Query(..., description="Start date (YYYY-MM-DD)"),
        end: date = Query(..., description="End date (YYYY-MM-DD)"),
    ) -> None:
        self.start = start
        self.end = end

    def validated(self) -> tuple[date, date]:
        """Return ``(start, end)``, raising 400 when ``start`` is after ``end``."""
        if self.start > self.end:
            raise HTTPException(status_code=400, detail="start must be ≤ end")
        return self.start, self.end
