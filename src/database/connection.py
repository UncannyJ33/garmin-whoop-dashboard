import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text

from config.settings import settings

logger = logging.getLogger(__name__)


def _ensure_data_dir(database_url: str) -> None:
    """Create the data/ directory if the URL points to a file-based SQLite DB."""
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def get_engine(database_url: str | None = None) -> Engine:
    """Create and return a SQLAlchemy engine for the configured database.

    Supports both SQLite (local dev) and PostgreSQL (production).
    SQLite engines get WAL mode enabled and check_same_thread disabled.
    PostgreSQL engines get a connection pool suitable for a web app.

    Args:
        database_url: Override the default DATABASE_URL from settings.

    Returns:
        Configured SQLAlchemy Engine instance.
    """
    url = database_url or settings.database_url
    _ensure_data_dir(url)

    if _is_sqlite(url):
        logger.info("Database: SQLite (%s)", url)
        engine = create_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # WAL mode: better concurrent read/write — SQLite only
        @event.listens_for(engine, "connect")
        def _set_wal_mode(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    else:
        logger.info("Database: PostgreSQL (%s)", url.split("@")[-1])  # hide credentials
        engine = create_engine(
            url,
            echo=False,
            # pool_size=5: keeps 5 warm connections ready.  The Trends page
            # fires ~7 parallel metric requests; each needs one connection for
            # the data query (auth no longer uses a separate session).
            # max_overflow=10 absorbs further bursts; pool_pre_ping replaces
            # dead connections (handles transient PgBouncer drops).
            # pool_recycle=1800 refreshes before Supabase's server_lifetime.
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_timeout=30,
            # sslmode=require: Supabase's explicit recommendation for psycopg2 +
            # Transaction mode pooler (port 6543).
            connect_args={"sslmode": "require"},
        )

    return engine


def get_session_factory(engine: Engine) -> type:
    """Return a sessionmaker bound to the given engine.

    Args:
        engine: SQLAlchemy Engine to bind sessions to.

    Returns:
        sessionmaker class for creating DB sessions.
    """
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def check_connection(engine: Engine) -> bool:
    """Verify the database is reachable. Returns True on success, False on failure."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return False
