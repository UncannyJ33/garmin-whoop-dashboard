"""Database migrations package.

Migration files follow the 001_name.py naming convention. Since filenames
starting with a digit aren't valid Python identifiers, each migration is
loaded dynamically and exposed here for programmatic use.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import Engine


def _load(filename: str):
    """Load a migration module by filename from this package directory."""
    path = Path(__file__).parent / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    """Run all migrations in order.

    Args:
        database_url: Optional database URL override.
        engine: Optional pre-built SQLAlchemy engine (useful for in-memory testing).
    """
    # Guard: if an Engine was accidentally passed as database_url (positional call),
    # recover gracefully instead of crashing with an AttributeError.
    if isinstance(database_url, Engine):
        engine = database_url
        database_url = None

    kwargs = {"database_url": database_url, "engine": engine}
    _load("001_initial.py").run(**kwargs)
    _load("002_garmin_tables.py").run(**kwargs)
    _load("003_unified_tables.py").run(**kwargs)
    _load("004_exercise_sets.py").run(**kwargs)
    _load("005_postgresql.py").run(**kwargs)
    _load("006_users_table.py").run(**kwargs)
    _load("007_user_id_gaps.py").run(**kwargs)
    _load("008_migrate_whoop_token.py").run(**kwargs)
    _load("009_enable_rls.py").run(**kwargs)
    _load("010_garmin_credentials.py").run(**kwargs)
    _load("011_waitlist.py").run(**kwargs)
    _load("012_composite_indexes.py").run(**kwargs)
    _load("013_anomaly_cache.py").run(**kwargs)
