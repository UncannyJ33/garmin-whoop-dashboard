"""Sync status and trigger API routes."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine, text

from src.api.dependencies import get_engine_dep
from src.api.models import DataStatsResponse, SyncStatusItem, SyncTriggerResponse
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.database.connection import get_session_factory as _get_session_factory
from src.ingestion.scheduler import get_scheduler_status

router = APIRouter(prefix="/api/sync", tags=["sync"])

_KNOWN_SOURCES = ("whoop", "garmin")

# Maps source name → APScheduler job ID for next-run-time lookup
_SCHEDULER_JOB_IDS = {
    "garmin": "garmin_incremental_sync",
    "whoop": "whoop_incremental_sync",
}


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
                {"uid": current_user.id},
            )
            .mappings()
            .all()
        )

    by_source = {r["source"]: SyncStatusItem(**dict(r)) for r in rows}

    # Enrich with scheduler metadata (next run time + running state)
    scheduler_status = get_scheduler_status()
    result = []
    for src in _KNOWN_SOURCES:
        item = by_source.get(src, SyncStatusItem(source=src, status="never_synced"))
        job_info = scheduler_status["jobs"].get(_SCHEDULER_JOB_IDS[src], {})
        item.next_sync_at = job_info.get("next_run_at")
        item.scheduler_running = scheduler_status["running"]
        result.append(item)
    return result


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
            text(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM unified_daily"
                " WHERE user_id = :uid"
            ),
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


@router.post(
    "/trigger/{source}",
    response_model=SyncTriggerResponse,
    summary="Manually trigger a data sync",
)
async def trigger_sync(
    source: str,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> SyncTriggerResponse:
    """Trigger a 30-day incremental sync for the specified source.

    ``source`` must be ``whoop`` or ``garmin``.  Runs synchronously and
    returns the sync log when complete.  Garmin syncs typically take
    several minutes due to per-day API calls.
    """
    if source not in _KNOWN_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid values: {list(_KNOWN_SOURCES)}",
        )

    now = datetime.now(tz=UTC)
    start = now - timedelta(days=30)
    SessionFactory = _get_session_factory(engine)
    db = SessionFactory()

    try:
        if source == "whoop":
            from src.ingestion.whoop_pipeline import WhoopPipeline

            log = await WhoopPipeline(db, user_id=current_user.id).run(start=start, end=now)
        else:
            from src.ingestion.garmin_pipeline import GarminPipeline

            log = await asyncio.to_thread(
                lambda: GarminPipeline(db, user_id=current_user.id).run(
                    start=start.date(), end=now.date()
                )
            )
        # Read all log fields while session is still open to avoid DetachedInstanceError
        response = SyncTriggerResponse(
            source=source,
            status=log.status,
            records_fetched=log.records_fetched,
            records_stored=log.records_stored,
            started_at=str(log.started_at),
            completed_at=str(log.completed_at) if log.completed_at else None,
            error_message=log.error_message,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        db.close()

    return response
