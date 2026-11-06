"""Sync status and trigger API routes."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from config.settings import settings
from src.api.dependencies import get_db, get_engine_dep
from src.api.models import DataStatsResponse, SyncStatusItem, SyncTriggerResponse
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.clients.whoop_auth import WhoopAuth
from src.database.connection import get_session_factory as _get_session_factory
from src.ingestion.scheduler import get_scheduler_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

_KNOWN_SOURCES = ("whoop", "garmin")

# Maps source name → APScheduler job ID for next-run-time lookup
_SCHEDULER_JOB_IDS = {
    "garmin": "garmin_incremental_sync",
    "whoop": "whoop_incremental_sync",
}

# Per-user running state for manually triggered syncs.
# Keyed by "{source}:{user_id}" so concurrent syncs for different users
# don't block each other.
_running_syncs: dict[str, bool] = {}

# Per-user snapshot of the last DB-fetched sync rows — served directly while a sync
# is running so the status endpoint never waits on a busy DB connection pool.
# Keyed by user_id → source → row dict.  Cleared on sync completion so the next
# poll always fetches fresh data from the DB.
_status_cache: dict[str, dict[str, dict]] = {}


# Strong references to in-flight sync tasks: the event loop only keeps weak ones,
# so an unreferenced task can be garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


def _sync_key(source: str, user_id: str) -> str:
    """Return the per-user key used in ``_running_syncs``."""
    return f"{source}:{user_id}"


def _serialise_sync_rows(
    rows_by_source: dict[str, dict], uid: str, scheduler_status: dict
) -> list[SyncStatusItem]:
    """Build one ``SyncStatusItem`` per known source, enriched with scheduler metadata."""
    result = []
    for src in _KNOWN_SOURCES:
        row = rows_by_source.get(src)
        item = SyncStatusItem(**row) if row else SyncStatusItem(source=src, status="never_synced")
        job_info = scheduler_status["jobs"].get(_SCHEDULER_JOB_IDS[src], {})
        item.next_sync_at = job_info.get("next_run_at")
        item.scheduler_running = scheduler_status["running"]
        item.is_running = _running_syncs.get(_sync_key(src, uid), False)
        result.append(item)
    return result


@router.get(
    "/status",
    response_model=list[SyncStatusItem],
    summary="Last sync status for each data source",
)
async def sync_status(
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[SyncStatusItem]:
    """Return the most recent completed sync record for Whoop and Garmin."""
    uid = current_user.id
    scheduler_status = get_scheduler_status()

    # Fast path: while this user's sync is in flight serve the cached row
    # snapshot so we never wait on a busy DB connection pool.
    user_has_running = any(_running_syncs.get(_sync_key(src, uid), False) for src in _KNOWN_SOURCES)
    if user_has_running and uid in _status_cache:
        return _serialise_sync_rows(_status_cache[uid], uid, scheduler_status)

    # Normal path: query DB, populate cache for next in-flight poll.
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT s.source, s.completed_at AS last_sync_at,
                       s.status, s.records_stored, s.error_message
                FROM sync_log s
                INNER JOIN (
                    SELECT source, MAX(id) AS max_id
                    FROM sync_log
                    WHERE status != 'running'
                      AND user_id = :uid
                    GROUP BY source
                ) latest ON s.source = latest.source AND s.id = latest.max_id
                WHERE s.user_id = :uid
                ORDER BY s.source
                """
                ),
                {"uid": uid},
            )
            .mappings()
            .all()
        )

    _status_cache[uid] = {r["source"]: dict(r) for r in rows}
    return _serialise_sync_rows(_status_cache[uid], uid, scheduler_status)


@router.get(
    "/stats",
    response_model=DataStatsResponse,
    summary="Aggregate data overview stats",
)
async def data_stats(
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> DataStatsResponse:
    """Return total days, workouts, matched workouts, and date range from unified tables."""
    with engine.connect() as conn:
        daily = conn.execute(
            text("SELECT COUNT(*), MIN(date), MAX(date) FROM unified_daily WHERE user_id = :uid"),
            {"uid": current_user.id},
        ).one()
        workouts = conn.execute(
            text(
                "SELECT COUNT(*), SUM(CASE WHEN matched THEN 1 ELSE 0 END)"
                " FROM unified_workouts WHERE user_id = :uid"
            ),
            {"uid": current_user.id},
        ).one()
    return DataStatsResponse(
        total_days=daily[0] or 0,
        date_start=daily[1],
        date_end=daily[2],
        total_workouts=workouts[0] or 0,
        matched_workouts=int(workouts[1] or 0),
    )


async def _run_sync_task(source: str, engine: Engine, user_id: str) -> None:
    """Background coroutine: run a full 30-day incremental sync and clear the running flag.

    Errors are logged and suppressed so the caller is never blocked.
    """
    key = _sync_key(source, user_id)
    SessionFactory = _get_session_factory(engine)
    db = SessionFactory()
    try:
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=30)
        if source == "whoop":
            from src.ingestion.whoop_pipeline import WhoopPipeline

            await WhoopPipeline(db, user_id=user_id).run(start=start, end=now)
        else:
            from src.ingestion.garmin_pipeline import GarminPipeline

            log = await asyncio.to_thread(
                lambda: GarminPipeline(db, user_id=user_id).run(start=start.date(), end=now.date())
            )
            if log is None:
                logger.info(
                    "Manual sync skipped (another Garmin sync running) — source=%s user=%s",
                    source,
                    user_id,
                )
                return
            logger.info(
                "Manual sync finished — source=%s user=%s status=%s",
                source,
                user_id,
                log.status,
            )
            return
        logger.info("Manual sync complete — source=%s user=%s", source, user_id)
    except Exception:
        logger.exception("Manual sync failed — source=%s user=%s", source, user_id)
    finally:
        db.close()
        _running_syncs.pop(key, None)
        # Invalidate cache so the next status poll fetches fresh data from DB
        _status_cache.pop(user_id, None)


@router.post(
    "/trigger/{source}",
    response_model=SyncTriggerResponse,
    summary="Manually trigger a data sync",
)
async def trigger_sync(
    source: str,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
    db_check: Session = Depends(get_db),
) -> SyncTriggerResponse:
    """Trigger a 30-day incremental sync for the specified source.

    ``source`` must be ``whoop`` or ``garmin``.  Returns immediately with
    ``status="running"``; the sync runs as a background task.  Poll
    ``GET /api/sync/status`` — the ``is_running`` field transitions to
    ``false`` when the job finishes.

    Authorization:
    - Garmin: ``GARMIN_PERSONAL_API_KEY`` must be set on the server.
    - Whoop: the calling user must have connected their Whoop account first.
    """
    if source not in _KNOWN_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid values: {list(_KNOWN_SOURCES)}",
        )

    key = _sync_key(source, current_user.id)
    if _running_syncs.get(key):
        raise HTTPException(
            status_code=409,
            detail=f"A {source} sync is already in progress.",
        )

    # ── Per-source authorization checks ──────────────────────────────────────
    if source == "garmin":
        if not settings.garmin_personal_api_key:
            raise HTTPException(
                status_code=403,
                detail="Garmin not configured. Set GARMIN_PERSONAL_API_KEY on the server.",
            )

    if source == "whoop":
        if not WhoopAuth.has_token(current_user.id, db_check):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Whoop not connected. Go to Settings → Connect Whoop to authorize your account."
                ),
            )

    now = datetime.now(tz=UTC)
    _running_syncs[key] = True
    task = asyncio.create_task(_run_sync_task(source, engine, current_user.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return SyncTriggerResponse(
        source=source,
        status="running",
        records_fetched=0,
        records_stored=0,
        started_at=str(now),
    )
