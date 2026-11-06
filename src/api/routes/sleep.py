"""Sleep API routes."""

import dataclasses
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.sleep_analysis import (
    get_sleep_consistency,
    get_sleep_insights,
    get_strain_sleep_correlation,
)
from src.api.dependencies import get_engine_dep
from src.api.models import (
    CorrelationResult,
    SleepConsistencyResponse,
    SleepCorrelationResponse,
    SleepInsightResponse,
)
from src.auth.dependencies import get_current_user
from src.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sleep", tags=["sleep"])


@router.get(
    "/insights",
    response_model=list[SleepInsightResponse],
    summary="Sleep insights for a date range",
)
async def sleep_insights(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[SleepInsightResponse]:
    """Return per-night sleep insights linking sleep quality, prior training, and recovery."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        insights = get_sleep_insights(engine, start, end, user_id=current_user.id)
        return [SleepInsightResponse(**dataclasses.asdict(s)) for s in insights]
    except Exception as exc:
        logger.exception("sleep_insights failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/correlations",
    response_model=SleepCorrelationResponse,
    summary="Strain–sleep correlation analysis",
)
async def sleep_correlations(
    days: int = Query(default=30, ge=7, le=365, description="Number of days to analyse"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> SleepCorrelationResponse:
    """Pearson correlations between prior-day strain and sleep/recovery outcomes."""
    try:
        result = get_strain_sleep_correlation(engine, days=days, user_id=current_user.id)
        return SleepCorrelationResponse(
            strain_vs_total_sleep=CorrelationResult(**result["strain_vs_total_sleep"]),
            strain_vs_deep_sleep=CorrelationResult(**result["strain_vs_deep_sleep"]),
            strain_vs_next_day_recovery=CorrelationResult(**result["strain_vs_next_day_recovery"]),
            days_analyzed=result["days_analyzed"],
        )
    except Exception as exc:
        logger.exception("sleep_correlations failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/consistency",
    response_model=SleepConsistencyResponse,
    summary="Sleep schedule consistency metrics",
)
async def sleep_consistency(
    days: int = Query(default=30, ge=7, le=365, description="Number of days to analyse"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> SleepConsistencyResponse:
    """Bedtime variance, average total sleep, and sleep debt trend."""
    try:
        result = get_sleep_consistency(engine, days=days, user_id=current_user.id)
        return SleepConsistencyResponse(**result)
    except Exception as exc:
        logger.exception("sleep_consistency failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
