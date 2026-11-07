"""Run an initial 30-day sync for both Whoop and Garmin, then print a summary.

Usage (from project root, venv active):
    python scripts/initial_sync.py
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.owner import get_owner_user_id
from src.ingestion.garmin_pipeline import GarminPipeline
from src.ingestion.whoop_pipeline import WhoopPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _print_summary(label: str, log) -> None:
    print(f"\n── {label} Sync Summary {'─' * (38 - len(label))}")
    print(f"  Status         : {log.status}")
    print(f"  Records fetched: {log.records_fetched}")
    print(f"  Records stored : {log.records_stored}")
    print(f"  Started        : {log.started_at}")
    print(f"  Completed      : {log.completed_at}")
    if log.error_message:
        print(f"  Error          : {log.error_message}")
    print("──────────────────────────────────────────")


async def main() -> None:
    engine = get_engine()
    run_migrations(engine=engine)
    db = get_session_factory(engine)()
    owner = get_owner_user_id(engine)

    try:
        if owner is None:
            print("No owner account. Run `make owner EMAIL=...` first.")
            sys.exit(1)

        now = datetime.now(tz=UTC)
        start = now - timedelta(days=30)

        failed: list[str] = []

        # ── Whoop ──────────────────────────────────────────────────────
        print(f"\nStarting Whoop sync: {start.date()} → {now.date()}\n")
        try:
            whoop_log = await WhoopPipeline(db, user_id=owner).run(start=start, end=now)
        except Exception as e:
            logger.exception("Whoop sync failed")
            print(f"  Whoop sync FAILED: {type(e).__name__}: {e}")
            failed.append("Whoop")
        else:
            if whoop_log is None:
                print("  Whoop sync skipped: another Whoop sync is running")
            else:
                _print_summary("Whoop", whoop_log)

        # ── Garmin ─────────────────────────────────────────────────────
        print(f"\nStarting Garmin sync: {start.date()} → {now.date()}\n")
        try:
            garmin_log = GarminPipeline(db, user_id=owner).run(start=start.date(), end=now.date())
        except Exception as e:
            logger.exception("Garmin sync failed")
            print(f"  Garmin sync FAILED: {type(e).__name__}: {e}")
            failed.append("Garmin")
        else:
            if garmin_log is None:
                print("  Garmin sync skipped: another Garmin sync is running")
            else:
                _print_summary("Garmin", garmin_log)

        if failed:
            print(f"\nFailed sources: {', '.join(failed)}")
            sys.exit(1)

    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
