"""Training load API routes."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.training_load import get_training_load_history, get_training_load_ratio
from src.api.dependencies import DateRangeParams, get_engine_dep
from src.api.models import TrainingLoadHistoryItem, TrainingLoadResponse, WeeklyLoadItem
from src.auth.dependencies import get_current_user
from src.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get(
    "/load-ratio",
    response_model=TrainingLoadResponse,
    summary="Current ACWR training load ratio",
)
async def training_load_ratio(
    local_date: date | None = Query(
        None,
        alias="date",
        description="User's local date (YYYY-MM-DD); defaults to server UTC date if omitted",
    ),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> TrainingLoadResponse:
    """Compute the Acute:Chronic Workload Ratio for today (or the supplied date).

    Returns the ACWR value, zone classification, trend direction, and a per-week
    load breakdown for the last 4 weeks.  Returns 204 No Content when no training
    data exists for this user.
    """
    try:
        target = local_date or date.today()
        result = get_training_load_ratio(engine, current_user.id, target)
        return TrainingLoadResponse(
            acwr=result.acwr,
            acute_load=result.acute_load,
            chronic_load=result.chronic_load,
            zone=result.zone,
            zone_description=result.zone_description,
            trend=result.trend,
            weekly_loads=[
                WeeklyLoadItem(
                    week_start_date=wl.week_start_date,
                    total_strain=wl.total_strain,
                    workout_count=wl.workout_count,
                )
                for wl in result.weekly_loads
            ],
            confidence_note=result.confidence_note,
        )
    except Exception as exc:
        logger.exception("training_load_ratio failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/load-history",
    response_model=list[TrainingLoadHistoryItem],
    summary="Daily ACWR history for a date range",
)
async def training_load_history(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[TrainingLoadHistoryItem]:
    """Return a daily ACWR series for [start, end].

    Useful for rendering an ACWR trend chart over a custom date range.
    """
    start, end = dates.validated()
    try:
        history = get_training_load_history(engine, current_user.id, start, end)
        return [TrainingLoadHistoryItem(**h) for h in history]
    except Exception as exc:
        logger.exception("training_load_history failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
