from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from config.settings import settings


def _ensure_data_dir(database_url: str) -> None:
    """Create the data/ directory if the URL points to a file-based SQLite DB."""
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@event.listens_for(Engine, "connect")
def _set_wal_mode(dbapi_connection, connection_record) -> None:
    """Enable WAL mode for better concurrent read/write performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_engine(database_url: str | None = None) -> Engine:
    """Create and return a SQLAlchemy engine for the configured database.

    Args:
        database_url: Override the default DATABASE_URL from settings.

    Returns:
        Configured SQLAlchemy Engine instance.
    """
    url = database_url or settings.database_url
    _ensure_data_dir(url)
    return create_engine(url, echo=False)


def get_session_factory(engine: Engine) -> type:
    """Return a sessionmaker bound to the given engine.

    Args:
        engine: SQLAlchemy Engine to bind sessions to.

    Returns:
        sessionmaker class for creating DB sessions.
    """
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
