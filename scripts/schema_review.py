"""Run the Whoop/Garmin schema comparison and print results to the terminal.

Usage (from project root, venv active):
    python scripts/schema_review.py                  # last 14 days
    python scripts/schema_review.py --days 30        # last 30 days
    python scripts/schema_review.py --start 2026-02-01 --end 2026-03-01
    python scripts/schema_review.py --no-csv         # skip CSV output
    python scripts/schema_review.py --fmt grid       # table style: simple|grid|pipe|github
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# noqa: E402
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.normalization.comparison_tool import run_comparison

logging.basicConfig(
    level=logging.WARNING,  # suppress INFO noise from pipeline during review
    format="%(levelname)s %(name)s — %(message)s",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare Whoop and Garmin data side by side.")
    p.add_argument("--days", type=int, default=14, help="Number of days to review (default: 14)")
    p.add_argument("--start", type=date.fromisoformat, default=None, help="Start date YYYY-MM-DD")
    p.add_argument(
        "--end", type=date.fromisoformat, default=None, help="End date YYYY-MM-DD (inclusive)"
    )
    p.add_argument("--no-csv", dest="csv", action="store_false", help="Skip saving CSV files")
    p.add_argument(
        "--fmt",
        default="simple",
        choices=["simple", "grid", "pipe", "github", "rounded_grid"],
        help="Table format (default: simple)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    start = args.start
    end = args.end

    if start is None and end is None:
        from datetime import UTC, datetime, timedelta

        end = datetime.now(tz=UTC).date()
        start = end - timedelta(days=args.days)
    elif start is None or end is None:
        print("Error: provide both --start and --end, or neither (use --days instead).")
        sys.exit(1)

    engine = get_engine()
    run_migrations(engine=engine)

    run_comparison(engine, start=start, end=end, tablefmt=args.fmt, save_csv=args.csv)


if __name__ == "__main__":
    main()
