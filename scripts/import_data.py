"""CLI entry point for importing Garmin data from bulk export or CSV files.

Accepts a ZIP archive, extracted directory, or CSV/JSON file and auto-detects
the format.  After import the unified tables are updated automatically.

Usage (from project root, venv active):
    python scripts/import_data.py export.zip
    python scripts/import_data.py ~/Downloads/garmin_export/
    python scripts/import_data.py data/manual/garmin_activities.csv
    python scripts/import_data.py export.zip --no-normalize
    python scripts/import_data.py export.zip --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.ingestion.csv_import import GarminImporter, _detect_format

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Suppress noisy sub-module loggers
logging.getLogger("src.normalization").setLevel(logging.WARNING)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import Garmin data from bulk export ZIP/JSON or manual CSV files."
    )
    p.add_argument("path", type=Path, help="ZIP archive, directory, or CSV/JSON file to import")
    p.add_argument(
        "--no-normalize",
        dest="normalize",
        action="store_false",
        help="Skip normalization after import (faster, unified tables not updated)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect format and show what would be imported without writing to the database",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    path: Path = args.path

    if not path.exists():
        print(f"Error: path does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        fmt = _detect_format(path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Detected format: {fmt}")
    print(f"Source:          {path}")

    if args.dry_run:
        print("\n[dry-run] No data written.")
        return

    engine = get_engine()
    run_migrations(engine=engine)
    Session = get_session_factory(engine)

    with Session() as db:
        importer = GarminImporter(db, normalize=args.normalize)
        summary = importer.import_from(path)

    print("\nImport complete")
    print("─" * 40)
    print(summary)

    if summary.errors:
        print(f"\n⚠  {len(summary.errors)} warning(s):")
        for msg in summary.errors[:20]:
            print(f"   {msg}")
        if len(summary.errors) > 20:
            print(f"   … and {len(summary.errors) - 20} more")


if __name__ == "__main__":
    main()
