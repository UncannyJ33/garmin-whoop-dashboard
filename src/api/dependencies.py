from collections.abc import Generator

from sqlalchemy.orm import Session

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations

_engine = get_engine()
run_migrations(engine=_engine)
_SessionLocal = get_session_factory(_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
