"""Insights API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.weekly_digest import get_weekly_digest
from src.api.dependencies import get_engine_dep
from src.api.models import WeeklyDigestResponse
from src.auth.dependencies import get_current_user
from src.auth.models import User

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get(
    "/weekly-digest",
    response_model=WeeklyDigestResponse,
    summary="Programmatic narrative digest of the past 7 days",
)
async def weekly_digest(
    local_date: date | None = Query(
        None,
        alias="date",
        description="End date of the digest period (YYYY-MM-DD); defaults to today",
    ),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> WeeklyDigestResponse:
    """Return 2–3 narrative takeaways about the past 7 days.

    Takeaways cover the most significant changes in readiness, training load,
    sleep, and recovery using template-based text and real metric deltas.
    Warnings for overreaching ACWR or significant recovery decline are always
    surfaced first.
    """
    try:
        target = local_date or date.today()
        result = get_weekly_digest(engine, current_user.id, target)
        return WeeklyDigestResponse(
            week_start=result.week_start.isoformat(),
            week_end=result.week_end.isoformat(),
            takeaways=result.takeaways,
            metrics_snapshot=result.metrics_snapshot,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
