"""Background scheduler for periodic Garmin data ingestion.

Runs an incremental Garmin sync on a configurable interval using APScheduler's
BackgroundScheduler.  The scheduler is a no-op when the TESTING environment
variable is set so it never runs during the test suite.
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from config.settings import settings
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.ingestion.garmin_pipeline import GarminPipeline

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_garmin_sync() -> None:
    """Job target: run an incremental Garmin sync.

    Opens its own DB session so APScheduler can call this from a thread pool
    without sharing state with the main application thread.  Any exception is
    caught, logged, and suppressed so the scheduler keeps running.
    """
    logger.info("Garmin scheduled sync starting")
    try:
        engine = get_engine()
        run_migrations(engine)
        SessionFactory = get_session_factory(engine)
        with SessionFactory() as db:
            pipeline = GarminPipeline(db)
            log = pipeline.run()
        logger.info(
            "Garmin scheduled sync complete — %d stored (status: %s)",
            log.records_stored,
            log.status,
        )
    except Exception:
        logger.exception("Garmin scheduled sync failed — scheduler will retry next interval")


def create_scheduler(interval_minutes: int | None = None) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler.

    The scheduler has a single job: run an incremental Garmin sync every
    *interval_minutes* minutes.

    Args:
        interval_minutes: Poll interval in minutes.  Defaults to
            ``settings.garmin_poll_interval_minutes``.

    Returns:
        Configured (but not yet started) BackgroundScheduler.
    """
    minutes = interval_minutes if interval_minutes is not None else settings.garmin_poll_interval_minutes
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_garmin_sync,
        trigger="interval",
        minutes=minutes,
        id="garmin_incremental_sync",
        name="Garmin incremental sync",
        replace_existing=True,
        max_instances=1,  # prevent overlapping runs
    )
    logger.info("Garmin sync scheduler configured — interval: %d min", minutes)
    return scheduler


def start_scheduler() -> None:
    """Start the background scheduler.

    No-op when the ``TESTING`` environment variable is set.  Idempotent: does
    nothing if the scheduler is already running.
    """
    global _scheduler

    if os.getenv("TESTING"):
        logger.debug("TESTING env set — Garmin scheduler will not start")
        return

    if _scheduler is not None and _scheduler.running:
        logger.debug("Garmin scheduler already running — skipping start")
        return

    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("Garmin scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler.

    Idempotent: does nothing if the scheduler is not running.
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        logger.debug("Garmin scheduler not running — nothing to stop")
        return

    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Garmin scheduler stopped")
