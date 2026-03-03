"""Live integration test for WhoopClient against the real Whoop API.

Run from the project root with the venv active:
    python scripts/test_whoop_client_live.py
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from src.clients.whoop_client import WhoopClient
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("live_test")


async def main() -> None:
    engine = get_engine()
    run_migrations(engine=engine)
    Session = get_session_factory(engine)
    db = Session()

    client = WhoopClient(db)

    now = datetime.now(tz=UTC)
    end = now
    start_7d = now - timedelta(days=7)
    start_60d = now - timedelta(days=60)

    try:
        # --- Profile and body (single-object, no pagination) ---
        logger.info("Fetching profile...")
        profile = await client.get_profile()
        logger.info("  user_id=%s  email=%s", profile.get("user_id"), profile.get("email"))
        assert isinstance(profile, dict), "get_profile must return a dict"

        logger.info("Fetching body measurements...")
        body = await client.get_body_measurements()
        logger.info(
            "  height=%.2fm  weight=%.1fkg  max_hr=%s",
            body.get("height_meter", 0),
            body.get("weight_kilogram", 0),
            body.get("max_heart_rate"),
        )
        assert isinstance(body, dict), "get_body_measurements must return a dict"

        # --- Collection endpoints — last 7 days ---
        logger.info("Fetching cycles (last 7 days)...")
        cycles = await client.get_cycles(start_7d, end)
        logger.info("  %d cycle(s) returned", len(cycles))
        assert isinstance(cycles, list), "get_cycles must return a list"

        logger.info("Fetching recovery (last 7 days)...")
        recovery = await client.get_recovery(start_7d, end)
        logger.info("  %d recovery record(s) returned", len(recovery))
        assert isinstance(recovery, list), "get_recovery must return a list"

        logger.info("Fetching sleep (last 7 days)...")
        sleep = await client.get_sleep(start_7d, end)
        logger.info("  %d sleep record(s) returned", len(sleep))
        assert isinstance(sleep, list), "get_sleep must return a list"

        logger.info("Fetching workouts (last 7 days)...")
        workouts = await client.get_workouts(start_7d, end)
        logger.info("  %d workout(s) returned", len(workouts))
        assert isinstance(workouts, list), "get_workouts must return a list"

        # --- Pagination test — 60 days should exceed 25-record page limit ---
        logger.info("Fetching cycles (last 60 days) — pagination test...")
        cycles_60d = await client.get_cycles(start_60d, end)
        logger.info("  %d cycle(s) over 60 days", len(cycles_60d))
        if len(cycles_60d) > 25:
            logger.info("  Pagination exercised — more than one page fetched")
        else:
            logger.info(
                "  Fewer than 25 cycles in 60 days — pagination not needed, but client handled it"
            )
        assert isinstance(cycles_60d, list)

        logger.info("Fetching sleep (last 60 days) — pagination test...")
        sleep_60d = await client.get_sleep(start_60d, end)
        logger.info("  %d sleep record(s) over 60 days", len(sleep_60d))

        logger.info("All checks passed.")

    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
