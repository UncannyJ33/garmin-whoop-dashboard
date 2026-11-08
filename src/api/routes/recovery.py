"""Recovery Activities API routes.

SQL uses only portable constructs so it runs on both SQLite and PostgreSQL.
Whoop timestamps are UTC, so activity dates are derived in Python from each
row's ``timezone_offset`` (local dates); duration and next-day date arithmetic
is also done in Python to avoid dialect-specific functions (strftime, interval).
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, text

from src.api.dependencies import DateRangeParams, get_engine_dep
from src.api.models import RecoveryActivityItem, WithWithoutResponse
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.normalization.whoop_mapper import local_date

router = APIRouter(prefix="/api/recovery", tags=["recovery"])

# Fetch raw activity rows — portable SQL; local dates are computed in Python
_ACTIVITY_QUERY = """
SELECT
    ww.start_time,
    ww.end_time,
    ww.timezone_offset,
    COALESCE(ww.sport_name, 'Unknown') AS activity
FROM whoop_workouts ww
WHERE ww.strain IS NULL
  AND ww.end_time IS NOT NULL
  AND ww.start_time >= :start
  AND ww.start_time <  :end
  AND ww.user_id = :uid
ORDER BY ww.start_time DESC
"""

_UNIFIED_DAILY_QUERY = """
SELECT date, whoop_recovery_score, whoop_hrv_rmssd
FROM unified_daily
WHERE date BETWEEN :start AND :end
  AND user_id = :uid
"""

_UNIFIED_SLEEP_QUERY = """
SELECT date, whoop_performance, total_sleep_minutes
FROM unified_sleep
WHERE date BETWEEN :start AND :end
  AND user_id = :uid
"""

# Bounded to the request's UTC-widened range, not the whole history.
_ALL_RECOVERY_DATES_QUERY = """
SELECT DISTINCT start_time, timezone_offset
FROM whoop_workouts
WHERE strain IS NULL AND end_time IS NOT NULL
  AND user_id = :uid
  AND start_time >= :start
  AND start_time <  :end
"""

_DAILY_RECOVERY_QUERY = """
SELECT date, whoop_recovery_score AS next_day_recovery
FROM unified_daily
WHERE date >= :start AND date <= :end
  AND whoop_recovery_score IS NOT NULL
  AND user_id = :uid
"""


def _duration_minutes(start_str: str, end_str: str) -> float | None:
    """Compute duration in minutes from two ISO 8601 strings."""
    try:
        from datetime import datetime as dt

        fmt = lambda s: dt.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
        delta = fmt(end_str) - fmt(start_str)
        return round(delta.total_seconds() / 60, 1)
    except (ValueError, AttributeError, TypeError):
        return None


@router.get(
    "",
    response_model=list[RecoveryActivityItem],
    summary="List recovery activities",
)
async def list_recovery(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[RecoveryActivityItem]:
    """Return Whoop recovery activities (strain IS NULL) for the date range."""
    start, end = dates.validated()

    # UTC bounds are widened by one day each side: a local date can sit on the
    # neighbouring UTC date. Rows are filtered on the local date in Python below.
    fetch_start = (start - timedelta(days=1)).isoformat()
    fetch_end = (end + timedelta(days=2)).isoformat()
    # Fetch window: start – (end + 1 day) for activities; need next-day data too
    lookup_end = (end + timedelta(days=1)).isoformat()

    with engine.connect() as conn:
        act_rows = (
            conn.execute(
                text(_ACTIVITY_QUERY),
                {"start": fetch_start, "end": fetch_end, "uid": current_user.id},
            )
            .mappings()
            .all()
        )

        daily_rows = (
            conn.execute(
                text(_UNIFIED_DAILY_QUERY),
                {"start": str(start), "end": lookup_end, "uid": current_user.id},
            )
            .mappings()
            .all()
        )

        sleep_rows = (
            conn.execute(
                text(_UNIFIED_SLEEP_QUERY),
                {"start": str(start), "end": lookup_end, "uid": current_user.id},
            )
            .mappings()
            .all()
        )

    daily_by_date = {r["date"]: r for r in daily_rows}
    sleep_by_date = {r["date"]: r for r in sleep_rows}

    results = []
    for row in act_rows:
        act_date = local_date(row["start_time"], row["timezone_offset"])
        if act_date is None or not (start.isoformat() <= act_date <= end.isoformat()):
            continue
        next_date = (date.fromisoformat(act_date) + timedelta(days=1)).isoformat()

        same_day = daily_by_date.get(act_date, {})
        next_day_daily = daily_by_date.get(next_date, {})
        next_day_sleep = sleep_by_date.get(next_date, {})

        results.append(
            RecoveryActivityItem(
                date=act_date,
                activity=(row["activity"] or "Unknown").replace("-", " ").replace("_", " ").title(),
                dur_min=_duration_minutes(row["start_time"], row["end_time"]),
                same_day_recovery=same_day.get("whoop_recovery_score"),
                next_day_recovery=next_day_daily.get("whoop_recovery_score"),
                next_day_hrv=next_day_daily.get("whoop_hrv_rmssd"),
                next_day_sleep_perf=next_day_sleep.get("whoop_performance"),
                next_day_sleep_min=next_day_sleep.get("total_sleep_minutes"),
            )
        )
    return results


@router.get(
    "/with-without",
    response_model=WithWithoutResponse,
    summary="Next-day recovery: with vs without prior recovery activity",
)
async def with_without(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> WithWithoutResponse:
    """Compare avg next-day recovery on days where previous day had a recovery activity vs not."""
    start, end = dates.validated()
    with engine.connect() as conn:
        rec_dates = {
            local_date(r[0], r[1])
            for r in conn.execute(
                text(_ALL_RECOVERY_DATES_QUERY),
                {
                    "uid": current_user.id,
                    # Local dates in [start-1, end-1] sit within 1 UTC day of them; 2 is margin.
                    "start": (start - timedelta(days=2)).isoformat(),
                    "end": (end + timedelta(days=2)).isoformat(),
                },
            ).fetchall()
        }
        daily_rows = (
            conn.execute(
                text(_DAILY_RECOVERY_QUERY),
                {"start": str(start), "end": str(end), "uid": current_user.id},
            )
            .mappings()
            .all()
        )

    with_vals: list[float] = []
    without_vals: list[float] = []
    for row in daily_rows:
        d = row["date"]
        prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
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
