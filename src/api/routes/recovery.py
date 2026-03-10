"""Recovery Activities API routes."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, text

from src.api.dependencies import get_engine_dep
from src.api.models import RecoveryActivityItem, WithWithoutResponse

router = APIRouter(prefix="/api/recovery", tags=["recovery"])

_ACTIVITY_QUERY = """
SELECT
    DATE(ww.start_time)                                                   AS date,
    COALESCE(ww.sport_name, 'Unknown')                                    AS activity,
    ROUND(
        (strftime('%s', ww.end_time) - strftime('%s', ww.start_time))
        / 60.0, 1)                                                        AS dur_min,
    ud.whoop_recovery_score                                               AS same_day_recovery,
    ud_next.whoop_recovery_score                                          AS next_day_recovery,
    ud_next.whoop_hrv_rmssd                                               AS next_day_hrv,
    us.whoop_performance                                                  AS next_day_sleep_perf,
    us.total_sleep_minutes                                                AS next_day_sleep_min
FROM whoop_workouts ww
LEFT JOIN unified_daily ud
       ON ud.date = DATE(ww.start_time)
LEFT JOIN unified_daily ud_next
       ON ud_next.date = DATE(ww.start_time, '+1 day')
LEFT JOIN unified_sleep us
       ON us.date = DATE(ww.start_time, '+1 day')
WHERE ww.strain IS NULL
  AND ww.end_time IS NOT NULL
  AND ww.start_time >= :start
  AND ww.start_time <  :end
ORDER BY ww.start_time DESC
"""

_ALL_RECOVERY_DATES_QUERY = """
SELECT DISTINCT DATE(start_time) AS date
FROM whoop_workouts
WHERE strain IS NULL AND end_time IS NOT NULL
"""

_DAILY_RECOVERY_QUERY = """
SELECT date, whoop_recovery_score AS next_day_recovery
FROM unified_daily
WHERE date >= :start AND date <= :end
  AND whoop_recovery_score IS NOT NULL
"""


@router.get(
    "",
    response_model=list[RecoveryActivityItem],
    summary="List recovery activities",
)
async def list_recovery(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
) -> list[RecoveryActivityItem]:
    """Return Whoop recovery activities (strain IS NULL) for the date range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    end_exclusive = (end + timedelta(days=1)).isoformat()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(_ACTIVITY_QUERY),
                {"start": str(start), "end": end_exclusive},
            )
            .mappings()
            .all()
        )

    return [
        RecoveryActivityItem(
            date=r["date"],
            activity=(r["activity"] or "Unknown").replace("-", " ").replace("_", " ").title(),
            dur_min=r["dur_min"],
            same_day_recovery=r["same_day_recovery"],
            next_day_recovery=r["next_day_recovery"],
            next_day_hrv=r["next_day_hrv"],
            next_day_sleep_perf=r["next_day_sleep_perf"],
            next_day_sleep_min=r["next_day_sleep_min"],
        )
        for r in rows
    ]


@router.get(
    "/with-without",
    response_model=WithWithoutResponse,
    summary="Next-day recovery: with vs without prior recovery activity",
)
async def with_without(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
) -> WithWithoutResponse:
    """Compare avg next-day recovery on days where previous day had a recovery activity vs not."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    with engine.connect() as conn:
        # All historical recovery dates (not date-filtered)
        rec_dates = {r[0] for r in conn.execute(text(_ALL_RECOVERY_DATES_QUERY)).fetchall()}
        # Daily rows in the requested range with recovery scores
        daily_rows = (
            conn.execute(
                text(_DAILY_RECOVERY_QUERY),
                {"start": str(start), "end": str(end)},
            )
            .mappings()
            .all()
        )

    with_vals: list[float] = []
    without_vals: list[float] = []
    for row in daily_rows:
        d = row["date"]  # YYYY-MM-DD
        # Check if PREVIOUS day had a recovery activity
        from datetime import date as _date

        prev = (_date.fromisoformat(d) - timedelta(days=1)).isoformat()
        if prev in rec_dates:
            with_vals.append(row["next_day_recovery"])
        else:
            without_vals.append(row["next_day_recovery"])

    def _avg(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    return WithWithoutResponse(
        with_avg=_avg(with_vals),
        without_avg=_avg(without_vals),
        with_count=len(with_vals),
        without_count=len(without_vals),
    )
