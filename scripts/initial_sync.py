"""Run an initial 30-day Whoop sync and print a summary.

Usage (from project root, venv active):
    python scripts/initial_sync.py
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.ingestion.whoop_pipeline import WhoopPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


async def main() -> None:
    engine = get_engine()
    run_migrations(engine=engine)
    db = get_session_factory(engine)()

    try:
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=30)

        print(f"\nStarting Whoop sync: {start.date()} → {now.date()}\n")

        pipeline = WhoopPipeline(db)
        log = await pipeline.run(start=start, end=now)

        print("\n── Sync Summary ──────────────────────────")
        print(f"  Status         : {log.status}")
        print(f"  Records fetched: {log.records_fetched}")
        print(f"  Records stored : {log.records_stored}")
        print(f"  Started        : {log.started_at}")
        print(f"  Completed      : {log.completed_at}")
        if log.error_message:
            print(f"  Error          : {log.error_message}")
        print("──────────────────────────────────────────\n")

    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
