"""Background scheduler for periodic Garmin and Whoop data ingestion.

Runs incremental syncs on configurable intervals using APScheduler's
BackgroundScheduler.  The scheduler is a no-op when the TESTING environment
variable is set so it never runs during the test suite.

Single-owner design
-------------------
The deployment has exactly one user (see ``get_owner_user_id``).  Both jobs
sync only that owner.  Garmin data comes from the Personal API via an env
key; the Whoop job runs only when the owner has a Whoop token.  Catchup syncs
are scheduled on startup for any source not synced within the last
``_STALE_THRESHOLD_HOURS`` hours.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine, text

from config.settings import settings
from src.database.connection import get_session_factory
from src.database.owner import get_owner_user_id

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# How long before a source is considered stale and a catchup is scheduled.
_STALE_THRESHOLD_HOURS = 1

# How long to delay Garmin catchup sync after container start (seconds).
# Gives Garmin's rate limit window time to clear between deploys.
_GARMIN_CATCHUP_DELAY_SECONDS = 180  # 3 minutes

# Log the "no key configured" notice only once per process.
_garmin_no_key_logged = False


def _resolve_owner(engine: Engine, label: str) -> str | None:
    """Return the owner id, or None (after logging) when the job should skip."""
    try:
        owner = get_owner_user_id(engine)
    except RuntimeError:
        logger.error("%s sync: more than one user exists — skipping run", label)
        return None
    except Exception:
        logger.exception("%s sync: could not look up owner — skipping run", label)
        return None
    if owner is None:
        logger.warning("%s sync: no owner user exists yet — skipping run", label)
    return owner


# ---------------------------------------------------------------------------
# Job targets
# ---------------------------------------------------------------------------


def _run_garmin_sync() -> None:
    """Job target: run an incremental Garmin sync for the owner.

    No-op without ``GARMIN_PERSONAL_API_KEY``.  The pipeline computes its own
    window and never raises for Garmin API errors; its returned ``SyncLog``
    status is logged.  ``None`` means another Garmin sync holds the run lock.
    """
    global _garmin_no_key_logged
    from src.api.dependencies import _engine as app_engine
    from src.ingestion.garmin_pipeline import GarminPipeline

    if not settings.garmin_personal_api_key:
        if not _garmin_no_key_logged:
            logger.info("Garmin sync: GARMIN_PERSONAL_API_KEY not set — skipping")
            _garmin_no_key_logged = True
        return

    owner = _resolve_owner(app_engine, "Garmin")
    if owner is None:
        return

    logger.info("Garmin sync: starting")
    try:
        SessionFactory = get_session_factory(app_engine)
        with SessionFactory() as db:
            log = GarminPipeline(db, user_id=owner).run()
    except Exception:
        logger.exception("Garmin sync: unexpected error")
        return

    if log is None:
        logger.info("Garmin sync: skipped — another Garmin sync is already running")
    elif log.status == "success":
        logger.info(
            "Garmin sync: success (fetched %s, stored %s)", log.records_fetched, log.records_stored
        )
    else:
        logger.warning(
            "Garmin sync: %s — %s (fetched %s, stored %s)",
            log.status,
            log.error_message,
            log.records_fetched,
            log.records_stored,
        )


def _run_whoop_sync() -> None:
    """Job target: run an incremental Whoop sync for the owner.

    Skipped (INFO) when the owner has no ``whoop_{owner}`` row in ``token_store``.
    On a 401 / missing-refresh-token failure the stale token row is removed so
    the owner is prompted to reconnect.
    """
    from src.api.dependencies import _engine as app_engine
    from src.ingestion.whoop_pipeline import WhoopPipeline

    owner = _resolve_owner(app_engine, "Whoop")
    if owner is None:
        return

    try:
        with app_engine.connect() as conn:
            has_token = (
                conn.execute(
                    text("SELECT 1 FROM token_store WHERE service = :key"),
                    {"key": f"whoop_{owner}"},
                ).first()
                is not None
            )
    except Exception:
        logger.exception("Whoop sync: could not check token — skipping run")
        return
    if not has_token:
        logger.info("Whoop sync: owner has no Whoop token — skipping")
        return

    logger.info("Whoop sync: starting")
    SessionFactory = get_session_factory(app_engine)
    try:
        with SessionFactory() as db:
            log = asyncio.run(WhoopPipeline(db, user_id=owner).run())
        logger.info("Whoop sync: %d stored (status: %s)", log.records_stored, log.status)
    except Exception as exc:
        err_msg = str(exc).lower()
        # Only delete the token on actual auth failures (401 = token rejected
        # by Whoop).  "token" and "refresh" are too broad — they match
        # transient errors like "Token refresh failed: 503" and would delete
        # a perfectly valid token just because Whoop had a blip.
        is_token_invalid = any(
            kw in err_msg for kw in ("401", "not authenticated", "no refresh token")
        )
        if is_token_invalid:
            logger.warning("Whoop sync: token rejected (401) — removing token for re-auth: %s", exc)
            try:
                with app_engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM token_store WHERE service = :key"),
                        {"key": f"whoop_{owner}"},
                    )
            except Exception:
                logger.exception("Could not remove Whoop token")
        else:
            logger.exception("Whoop sync: unexpected error")


# ---------------------------------------------------------------------------
# Scheduler configuration
# ---------------------------------------------------------------------------


def create_scheduler(
    garmin_interval_minutes: int | None = None,
    whoop_interval_minutes: int | None = None,
) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler.

    The scheduler has two recurring jobs:
    - Garmin sync every *garmin_interval_minutes* minutes.
    - Whoop sync every *whoop_interval_minutes* minutes.

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
        name="Garmin sync",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_whoop_sync,
        trigger="interval",
        minutes=whoop_minutes,
        id="whoop_incremental_sync",
        name="Whoop sync",
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
    """Schedule one-shot catchup syncs for sources with no recent successful sync.

    Checks whether the owner has had a successful sync within the last
    ``_STALE_THRESHOLD_HOURS`` hours.  If not, a one-shot catchup job fires
    ~10 seconds after this call so the single-owner sync job runs.

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
                        SELECT MAX(completed_at) FROM sync_log
                        WHERE source = :source AND status = 'success'
                        """
                    ),
                    {"source": source},
                ).one_or_none()

            needs_catchup = True
            if row is not None and row[0] is not None:
                last_sync = row[0]
                if isinstance(last_sync, str):
                    last_sync = datetime.fromisoformat(last_sync)
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=UTC)
                needs_catchup = last_sync < stale_threshold

            if needs_catchup:
                # Garmin gets a longer delay to let rate limit windows clear
                # between deploys.  Whoop keeps the short 10-second delay.
                delay_seconds = _GARMIN_CATCHUP_DELAY_SECONDS if source == "garmin" else 10
                run_time = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                scheduler.add_job(
                    job_fn,
                    trigger="date",
                    run_date=run_time,
                    id=f"{source}_catchup",
                    name=f"{source.capitalize()} catchup sync",
                    replace_existing=True,
                )
                logger.info(
                    "%s: stale — catchup sync scheduled for %s (%ds delay)",
                    source,
                    run_time,
                    delay_seconds,
                )
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
    1. Creates and starts the BackgroundScheduler.
    2. Schedules catchup syncs for any source with no recent successful sync.

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
        from src.api.dependencies import _engine as app_engine

        engine = app_engine

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
