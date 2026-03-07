"""Readiness API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.readiness_score import (
    ReadinessResult,
    compute_readiness,
    get_readiness_history,
)
from src.api.dependencies import get_engine_dep
from src.api.models import ContributingFactor, ReadinessHistoryItem, ReadinessResponse

router = APIRouter(prefix="/api/readiness", tags=["readiness"])


def _to_response(r: ReadinessResult) -> ReadinessResponse:
    return ReadinessResponse(
        date=r.date.isoformat(),
        score=r.score,
        recommendation=r.recommendation,
        contributing_factors={
            k: ContributingFactor(**v) for k, v in r.contributing_factors.items()
        },
        confidence=r.confidence,
    )


@router.get(
    "/today",
    response_model=ReadinessResponse,
    summary="Today's readiness score",
)
async def readiness_today(engine: Engine = Depends(get_engine_dep)) -> ReadinessResponse:
    """Compute the composite training readiness score for today."""
    try:
        return _to_response(compute_readiness(date.today(), engine))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/history",
    response_model=list[ReadinessHistoryItem],
    summary="Readiness score history",
)
async def readiness_history(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
) -> list[ReadinessHistoryItem]:
    """Return daily readiness scores for a date range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        history = get_readiness_history(start, end, engine)
        return [ReadinessHistoryItem(**h) for h in history]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
