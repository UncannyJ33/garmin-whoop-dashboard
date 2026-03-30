"""Background scheduler for periodic Garmin and Whoop data ingestion.

Runs incremental syncs on configurable intervals using APScheduler's
BackgroundScheduler.  The scheduler is a no-op when the TESTING environment
variable is set so it never runs during the test suite.

Multi-user design
-----------------
``get_users_to_sync()`` queries the database for every user that has a live
Whoop token *or* enabled Garmin auto-sync credentials, returning a registry
list consumed by the two scheduled jobs.  One user's failure never blocks
other users from syncing — each user is wrapped in its own try/except.

On Railway (ephemeral filesystem), Garmin OAuth tokens are persisted to and
restored from the ``token_store`` PostgreSQL table so they survive container
restarts.  Catchup syncs are scheduled automatically on startup for any user
not synced within the last ``_STALE_THRESHOLD_HOURS`` hours.
"""

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine, text

from config.settings import settings
from src.clients.garmin_auth import load_garmin_tokens_from_db, save_garmin_tokens_to_db
from src.database.connection import get_session_factory

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# How long before a source is considered stale and a catchup is scheduled.
_STALE_THRESHOLD_HOURS = 1

# How long to delay Garmin catchup sync after container start (seconds).
# Gives Garmin's rate limit window time to clear between deploys.
_GARMIN_CATCHUP_DELAY_SECONDS = 180  # 3 minutes

# ---------------------------------------------------------------------------
# Per-user Garmin 429 backoff tracker
# ---------------------------------------------------------------------------

# Maps user_id → (next_eligible_time, consecutive_429_count)
_garmin_backoff: dict[str, tuple[datetime, int]] = {}

# Backoff schedule: 30 min, 1 hr, 2 hr, 4 hr, 8 hr, 24 hr cap
_BACKOFF_MINUTES = [30, 60, 120, 240, 480, 1440]

# After this many consecutive 429s, disable the user's auto_sync_enabled so
# we stop hammering Garmin's SSO and give the account time to recover.
_MAX_CONSECUTIVE_429_BEFORE_DISABLE = 5


def _garmin_user_is_cooling_down(user_id: str) -> bool:
    """Return True if this user is still in a 429 backoff window."""
    if user_id not in _garmin_backoff:
        return False
    next_eligible, _ = _garmin_backoff[user_id]
    return datetime.now(UTC) < next_eligible


def _garmin_record_rate_limit(user_id: str) -> None:
    """Record a 429 for this user and set the next eligible retry time."""
    _, count = _garmin_backoff.get(user_id, (datetime.now(UTC), 0))
    count += 1
    idx = min(count - 1, len(_BACKOFF_MINUTES) - 1)
    wait_minutes = _BACKOFF_MINUTES[idx]
    next_eligible = datetime.now(UTC) + timedelta(minutes=wait_minutes)
    _garmin_backoff[user_id] = (next_eligible, count)
    logger.info(
        "Garmin 429 backoff: user %s — attempt #%d, next retry after %s (%d min)",
        user_id,
        count,
        next_eligible.isoformat(),
        wait_minutes,
    )


def _garmin_clear_backoff(user_id: str) -> None:
    """Clear backoff state for a user after a successful sync."""
    if user_id in _garmin_backoff:
        logger.info("Garmin 429 backoff: cleared for user %s after successful sync", user_id)
        del _garmin_backoff[user_id]


# ---------------------------------------------------------------------------
# Sync registry
# ---------------------------------------------------------------------------


def get_users_to_sync(engine: Engine) -> list[dict]:
    """Return all users eligible for background sync.

    Queries ``token_store`` and ``garmin_credentials`` to build the complete
    set of users that should be included in each scheduled sync job.

    Args:
        engine: SQLAlchemy engine for DB queries.

    Returns:
        List of dicts, each with keys:
        - ``user_id`` (str)
        - ``whoop_connected`` (bool) — has an active Whoop token in token_store
        - ``garmin_auto_sync`` (bool) — has auto_sync_enabled=1 credentials
        - ``garmin_has_token`` (bool) — has a garth session token (legacy/owner)
    """
    try:
        with engine.connect() as conn:
            # Single query: fetch all sync-relevant user info in one round-trip
            rows = conn.execute(
                text(
                    "SELECT 'whoop' AS src, service AS id FROM token_store WHERE service LIKE 'whoop_%'"
                    " UNION ALL "
                    "SELECT 'garmin_cred' AS src, user_id AS id FROM garmin_credentials WHERE auto_sync_enabled = true"
                    " UNION ALL "
                    "SELECT 'garmin_token' AS src, service AS id FROM token_store WHERE service LIKE 'garmin_%'"
                )
            ).fetchall()
    except Exception:
        logger.exception("get_users_to_sync: DB error — returning empty registry")
        return []

    whoop_user_ids: set[str] = set()
    garmin_cred_user_ids: set[str] = set()
    garmin_token_user_ids: set[str] = set()
    for src, raw_id in rows:
        if src == "whoop":
            whoop_user_ids.add(raw_id.removeprefix("whoop_"))
        elif src == "garmin_cred":
            garmin_cred_user_ids.add(raw_id)
        elif src == "garmin_token":
            garmin_token_user_ids.add(raw_id.removeprefix("garmin_"))

    all_user_ids = whoop_user_ids | garmin_cred_user_ids | garmin_token_user_ids

    return [
        {
            "user_id": uid,
            "whoop_connected": uid in whoop_user_ids,
            "garmin_auto_sync": uid in garmin_cred_user_ids,
            "garmin_has_token": uid in garmin_token_user_ids,
        }
        for uid in all_user_ids
    ]


# ---------------------------------------------------------------------------
# Job targets
# ---------------------------------------------------------------------------


def _run_garmin_multi_user() -> None:
    """Job target: run an incremental Garmin sync for every eligible user.

    Eligible users are those with ``auto_sync_enabled=1`` credentials *or* an
    existing garth session token (legacy owner account).  For credential users
    the session is refreshed via ``authenticate_user_garmin`` before each sync.

    On authentication failure the user's ``auto_sync_enabled`` is set to 0 so
    bad credentials don't keep hammering Garmin.  Each user's sync is wrapped
    in its own try/except so one failure never blocks others.  A 2-second delay
    between users avoids triggering Garmin's rate limiter.
    """
    from src.api.dependencies import _engine as app_engine
    from src.auth.encryption import decrypt_credential
    from src.clients.garmin_auth import GarminAuthError, authenticate_user_garmin
    from src.ingestion.garmin_pipeline import GarminPipeline

    logger.info("Garmin multi-user sync: starting")

    try:
        users = get_users_to_sync(app_engine)
    except Exception:
        logger.exception("Garmin multi-user sync: failed to load user registry — aborting")
        return

    garmin_users = [u for u in users if u["garmin_auto_sync"] or u["garmin_has_token"]]

    if not garmin_users:
        logger.debug("Garmin multi-user sync: no eligible users — skipping")
        return

    logger.info("Garmin multi-user sync: %d user(s) to sync", len(garmin_users))

    # Pre-load credentials for users who have them (avoid repeated DB round-trips)
    try:
        with app_engine.connect() as conn:
            cred_rows = conn.execute(
                text(
                    "SELECT user_id, encrypted_email, encrypted_password "
                    "FROM garmin_credentials WHERE auto_sync_enabled = true"
                )
            ).fetchall()
        creds_by_user: dict[str, tuple[str, str]] = {
            r[0]: (r[1], r[2]) for r in cred_rows
        }
    except Exception:
        logger.exception("Garmin multi-user sync: could not load credentials")
        creds_by_user = {}

    SessionFactory = get_session_factory(app_engine)

    for i, user in enumerate(garmin_users):
        user_id = user["user_id"]

        if i > 0:
            time.sleep(2)

        # Decrypt credentials if this user has them
        email: str | None = None
        password: str | None = None
        if user_id in creds_by_user:
            try:
                enc_email, enc_password = creds_by_user[user_id]
                email = decrypt_credential(enc_email)
                password = decrypt_credential(enc_password)
            except ValueError:
                logger.error(
                    "Garmin multi-user sync: could not decrypt credentials for user %s "
                    "(key mismatch?) — skipping",
                    user_id,
                )
                continue

        # Skip users still in 429 backoff cooldown
        if _garmin_user_is_cooling_down(user_id):
            next_eligible, count = _garmin_backoff[user_id]
            logger.info(
                "Garmin multi-user sync: user %s in 429 cooldown (attempt #%d, eligible at %s) — skipping",
                user_id,
                count,
                next_eligible.isoformat(),
            )
            continue

        logger.info("Garmin multi-user sync: syncing user %s", user_id)
        try:
            with SessionFactory() as db:
                if email and password:
                    # Only do a full password login when no session tokens exist.
                    # Reusing existing tokens avoids hammering Garmin's auth
                    # endpoint every 15 minutes and triggering rate limits.
                    from src.clients.garmin_auth import has_garmin_token
                    if not has_garmin_token(user_id, db):
                        logger.info(
                            "Garmin multi-user sync: no tokens for user %s — authenticating",
                            user_id,
                        )
                        authenticate_user_garmin(user_id, email, password, db)
                    else:
                        logger.debug(
                            "Garmin multi-user sync: reusing existing tokens for user %s",
                            user_id,
                        )
                pipeline = GarminPipeline(db, user_id=user_id)
                log = pipeline.run()
            logger.info(
                "Garmin multi-user sync: user %s — %d stored (status: %s)",
                user_id,
                log.records_stored,
                log.status,
            )
            # Successful sync — clear any backoff state
            _garmin_clear_backoff(user_id)
            # Persist any updated garth tokens for container restart resilience
            save_garmin_tokens_to_db(app_engine)
        except GarminAuthError as exc:
            err_msg = str(exc)
            is_rate_limit = "429" in err_msg or "rate limit" in err_msg.lower()
            if is_rate_limit:
                _garmin_record_rate_limit(user_id)
                _, count = _garmin_backoff[user_id]
                if count >= _MAX_CONSECUTIVE_429_BEFORE_DISABLE and user_id in creds_by_user:
                    # Too many consecutive 429s — disable auto_sync so we stop
                    # hammering Garmin's SSO.  The user must re-enable manually
                    # in Settings after the account-level rate limit clears (~24h).
                    logger.error(
                        "Garmin multi-user sync: %d consecutive 429s for user %s — "
                        "disabling auto_sync to protect the account. Re-enable in "
                        "Settings after waiting 24h.",
                        count,
                        user_id,
                    )
                    try:
                        with app_engine.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE garmin_credentials SET auto_sync_enabled = false "
                                    "WHERE user_id = :uid"
                                ),
                                {"uid": user_id},
                            )
                    except Exception:
                        logger.exception(
                            "Could not disable auto_sync for user %s after repeated 429s",
                            user_id,
                        )
                else:
                    logger.warning(
                        "Garmin multi-user sync: rate limit for user %s (attempt #%d) — skipping this run",
                        user_id,
                        count,
                    )
            else:
                # 401/403 = bad credentials — disable auto-sync so we stop retrying.
                logger.warning(
                    "Garmin multi-user sync: auth failure for user %s — disabling auto-sync: %s",
                    user_id,
                    exc,
                )
                if user_id in creds_by_user:
                    try:
                        with app_engine.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE garmin_credentials SET auto_sync_enabled = false "
                                    "WHERE user_id = :uid"
                                ),
                                {"uid": user_id},
                            )
                    except Exception:
                        logger.exception(
                            "Could not disable auto_sync for user %s after auth failure",
                            user_id,
                        )
        except Exception:
            logger.exception(
                "Garmin multi-user sync: unexpected error for user %s — continuing",
                user_id,
            )


def _run_whoop_multi_user() -> None:
    """Job target: run an incremental Whoop sync for every user with a live token.

    Iterates all users returned by the sync registry who have a Whoop token.
    On token expiry / refresh failure the stale token is removed from
    ``token_store`` so the user is prompted to reconnect on their next visit.
    Each user's sync is wrapped in its own try/except so one failure never
    blocks others.  A 1-second delay between users avoids rate-limit issues.
    """
    from src.api.dependencies import _engine as app_engine
    from src.ingestion.whoop_pipeline import WhoopPipeline

    logger.info("Whoop multi-user sync: starting")

    try:
        users = get_users_to_sync(app_engine)
    except Exception:
        logger.exception("Whoop multi-user sync: failed to load user registry — aborting")
        return

    whoop_users = [u for u in users if u["whoop_connected"]]

    if not whoop_users:
        logger.debug("Whoop multi-user sync: no users with Whoop tokens — skipping")
        return

    logger.info("Whoop multi-user sync: %d user(s) to sync", len(whoop_users))
    SessionFactory = get_session_factory(app_engine)

    for i, user in enumerate(whoop_users):
        user_id = user["user_id"]

        if i > 0:
            time.sleep(1)

        logger.info("Whoop multi-user sync: syncing user %s", user_id)
        try:
            with SessionFactory() as db:
                log = asyncio.run(WhoopPipeline(db, user_id=user_id).run())
            logger.info(
                "Whoop multi-user sync: user %s — %d stored (status: %s)",
                user_id,
                log.records_stored,
                log.status,
            )
        except Exception as exc:
            err_msg = str(exc).lower()
            is_token_failure = any(
                kw in err_msg
                for kw in ("token", "401", "refresh", "not authenticated", "expired")
            )
            if is_token_failure:
                # Remove the stale token so the user gets prompted to reconnect
                logger.warning(
                    "Whoop multi-user sync: token failure for user %s — removing token "
                    "for re-auth: %s",
                    user_id,
                    exc,
                )
                try:
                    with app_engine.begin() as conn:
                        conn.execute(
                            text("DELETE FROM token_store WHERE service = :key"),
                            {"key": f"whoop_{user_id}"},
                        )
                except Exception:
                    logger.exception(
                        "Could not remove Whoop token for user %s", user_id
                    )
            else:
                logger.exception(
                    "Whoop multi-user sync: unexpected error for user %s — continuing",
                    user_id,
                )


# ---------------------------------------------------------------------------
# Scheduler configuration
# ---------------------------------------------------------------------------


def create_scheduler(
    garmin_interval_minutes: int | None = None,
    whoop_interval_minutes: int | None = None,
) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler.

    The scheduler has two recurring jobs:
    - Garmin multi-user sync every *garmin_interval_minutes* minutes.
    - Whoop multi-user sync every *whoop_interval_minutes* minutes.

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
        _run_garmin_multi_user,
        trigger="interval",
        minutes=garmin_minutes,
        id="garmin_incremental_sync",
        name="Garmin multi-user sync",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_whoop_multi_user,
        trigger="interval",
        minutes=whoop_minutes,
        id="whoop_incremental_sync",
        name="Whoop multi-user sync",
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


def _schedule_catchup_if_stale(
    scheduler: BackgroundScheduler, engine: Engine
) -> None:
    """Schedule one-shot catchup syncs for sources with no recent successful sync.

    Checks whether *any* user has had a successful sync within the last
    ``_STALE_THRESHOLD_HOURS`` hours.  If not, a one-shot catchup job fires
    ~10 seconds after this call so the multi-user sync job picks up all users.

    Args:
        scheduler: The running BackgroundScheduler to add catchup jobs to.
        engine: SQLAlchemy engine for DB queries.
    """
    stale_threshold = datetime.now(UTC) - timedelta(hours=_STALE_THRESHOLD_HOURS)
    job_map = {
        "garmin": _run_garmin_multi_user,
        "whoop": _run_whoop_multi_user,
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
                delay_seconds = (
                    _GARMIN_CATCHUP_DELAY_SECONDS if source == "garmin" else 10
                )
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
            logger.exception(
                "Could not check stale status for %s — skipping catchup", source
            )


# ---------------------------------------------------------------------------
# Public lifecycle API
# ---------------------------------------------------------------------------


def start_scheduler(engine: Engine | None = None) -> None:
    """Start the background scheduler.

    On startup:
    1. Restores Garmin tokens from DB to filesystem (Railway resilience).
    2. Creates and starts the BackgroundScheduler.
    3. Schedules catchup syncs for any source with no recent successful sync.

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
