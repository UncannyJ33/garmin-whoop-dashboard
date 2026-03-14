"""Background scheduler for periodic Garmin and Whoop data ingestion.

Runs incremental syncs on configurable intervals using APScheduler's
BackgroundScheduler.  The scheduler is a no-op when the TESTING environment
variable is set so it never runs during the test suite.

On Railway (ephemeral filesystem), Garmin OAuth tokens are persisted to and
restored from the ``token_store`` PostgreSQL table so they survive container
restarts.  Catchup syncs are scheduled automatically if either source has
not synced within the last hour.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine, text

from config.settings import settings
from src.clients.garmin_auth import load_garmin_tokens_from_db, save_garmin_tokens_to_db
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.ingestion.garmin_pipeline import GarminPipeline

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# How long before a source is considered stale and a catchup is scheduled.
_STALE_THRESHOLD_HOURS = 1


# ---------------------------------------------------------------------------
# Job targets
# ---------------------------------------------------------------------------


def _run_garmin_sync() -> None:
    """Job target: run an incremental Garmin sync.

    Opens its own DB session so APScheduler can call this from a thread pool
    without sharing state with the main application thread.  Any exception is
    caught, logged, and suppressed so the scheduler keeps running.  Garmin
    tokens are persisted to DB after each successful sync so they survive
    container restarts.
    """
    logger.info("Garmin scheduled sync starting")
    try:
        engine = get_engine()
        run_migrations(engine=engine)
        SessionFactory = get_session_factory(engine)
        with SessionFactory() as db:
            pipeline = GarminPipeline(db)
            log = pipeline.run()
        logger.info(
            "Garmin scheduled sync complete — %d stored (status: %s)",
            log.records_stored,
            log.status,
        )
        # Persist any updated garth tokens back to DB for container restart resilience
        save_garmin_tokens_to_db(engine)
    except Exception:
        logger.exception("Garmin scheduled sync failed — scheduler will retry next interval")


def _run_whoop_sync() -> None:
    """Job target: run an incremental Whoop sync.

    Uses ``asyncio.run()`` to bridge APScheduler's synchronous thread pool into
    an async context for WhoopPipeline.  Any exception is caught, logged, and
    suppressed so the scheduler keeps running.
    """
    logger.info("Whoop scheduled sync starting")
    try:
        engine = get_engine()
        SessionFactory = get_session_factory(engine)
        with SessionFactory() as db:
            from src.ingestion.whoop_pipeline import WhoopPipeline

            log = asyncio.run(WhoopPipeline(db).run())
        logger.info(
            "Whoop scheduled sync complete — %d stored (status: %s)",
            log.records_stored,
            log.status,
        )
    except Exception:
        logger.exception("Whoop scheduled sync failed — scheduler will retry next interval")


# ---------------------------------------------------------------------------
# Scheduler configuration
# ---------------------------------------------------------------------------


def create_scheduler(
    garmin_interval_minutes: int | None = None,
    whoop_interval_minutes: int | None = None,
) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler.

    The scheduler has two recurring jobs:
    - Garmin incremental sync every *garmin_interval_minutes* minutes.
    - Whoop incremental sync every *whoop_interval_minutes* minutes.

    Args:
        garmin_interval_minutes: Garmin poll interval.  Defaults to
            ``settings.garmin_poll_interval_minutes``.
        whoop_interval_minutes: Whoop poll interval.  Defaults to 30.

    Returns:
        Configured (but not yet started) BackgroundScheduler.
    """
    garmin_minutes = (
        garmin_interval_minutes
        if garmin_interval_minutes is not None
        else settings.garmin_poll_interval_minutes
    )
    whoop_minutes = whoop_interval_minutes if whoop_interval_minutes is not None else 30

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_garmin_sync,
        trigger="interval",
        minutes=garmin_minutes,
        id="garmin_incremental_sync",
        name="Garmin incremental sync",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_whoop_sync,
        trigger="interval",
        minutes=whoop_minutes,
        id="whoop_incremental_sync",
        name="Whoop incremental sync",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduler configured — Garmin: %d min, Whoop: %d min",
        garmin_minutes,
        whoop_minutes,
    )
    return scheduler


# ---------------------------------------------------------------------------
# Catchup logic
# ---------------------------------------------------------------------------


def _schedule_catchup_if_stale(scheduler: BackgroundScheduler, engine: Engine) -> None:
    """Schedule one-shot catchup syncs for sources that haven't synced recently.

    For each source, queries the most recent successful sync.  If no successful
    sync exists or the last sync is older than ``_STALE_THRESHOLD_HOURS`` hours,
    a one-shot "date" trigger job is added to fire ~10 seconds after this call.

    Args:
        scheduler: The running BackgroundScheduler to add catchup jobs to.
        engine: SQLAlchemy engine for DB queries.
    """
    stale_threshold = datetime.now(UTC) - timedelta(hours=_STALE_THRESHOLD_HOURS)
    job_map = {
        "garmin": _run_garmin_sync,
        "whoop": _run_whoop_sync,
    }

    for source, job_fn in job_map.items():
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT completed_at FROM sync_log
                        WHERE source = :source AND status = 'success'
                        ORDER BY id DESC LIMIT 1
                        """
                    ),
                    {"source": source},
                ).one_or_none()

            needs_catchup = True
            if row is not None and row[0] is not None:
                last_sync = row[0]
                # DB may return naive datetimes (UTC) on PostgreSQL — normalise
                if isinstance(last_sync, str):
                    last_sync = datetime.fromisoformat(last_sync)
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=UTC)
                needs_catchup = last_sync < stale_threshold

            if needs_catchup:
                run_time = datetime.now(UTC) + timedelta(seconds=10)
                scheduler.add_job(
                    job_fn,
                    trigger="date",
                    run_date=run_time,
                    id=f"{source}_catchup",
                    name=f"{source.capitalize()} catchup sync",
                    replace_existing=True,
                )
                logger.info("%s: stale — catchup sync scheduled for %s", source, run_time)
            else:
                logger.info("%s: recent sync found — no catchup needed", source)
        except Exception:
            logger.exception("Could not check stale status for %s — skipping catchup", source)


# ---------------------------------------------------------------------------
# Public lifecycle API
# ---------------------------------------------------------------------------


def start_scheduler(engine: Engine | None = None) -> None:
    """Start the background scheduler.

    On startup:
    1. Restores Garmin tokens from DB to filesystem (Railway resilience).
    2. Creates and starts the BackgroundScheduler.
    3. Schedules catchup syncs for any source that hasn't synced in >1 hour.

    No-op when the ``TESTING`` environment variable is set.  Idempotent: does
    nothing if the scheduler is already running.

    Args:
        engine: Optional pre-built SQLAlchemy engine.  Defaults to
            ``get_engine()`` when not provided.
    """
    global _scheduler

    if os.getenv("TESTING"):
        logger.debug("TESTING env set — scheduler will not start")
        return

    if _scheduler is not None and _scheduler.running:
        logger.debug("Scheduler already running — skipping start")
        return

    if engine is None:
        engine = get_engine()

    # Restore Garmin tokens from DB so garth can find them on the filesystem
    try:
        loaded = load_garmin_tokens_from_db(engine)
        if not loaded:
            logger.info("Garmin: no persisted tokens in DB — will authenticate on first sync")
    except Exception:
        logger.exception("Garmin: failed to load tokens from DB — will attempt password auth")

    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("Scheduler started")

    # Schedule one-shot catchup syncs for stale sources (non-blocking)
    _schedule_catchup_if_stale(_scheduler, engine)


def stop_scheduler() -> None:
    """Stop the background scheduler.

    Idempotent: does nothing if the scheduler is not running.
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        logger.debug("Scheduler not running — nothing to stop")
        return

    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return current scheduler state including next run times per source.

    Returns:
        Dict with keys:
        - ``running`` (bool): Whether the scheduler is currently active.
        - ``jobs`` (dict): Map of job_id → {name, next_run_at (ISO str | None)}.
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": {}}

    jobs = {}
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs[job.id] = {
            "name": job.name,
            "next_run_at": next_run.isoformat() if next_run else None,
        }
    return {"running": True, "jobs": jobs}
