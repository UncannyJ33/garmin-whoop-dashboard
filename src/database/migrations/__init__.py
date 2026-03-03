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
    _load("001_initial.py").run(database_url, engine)
