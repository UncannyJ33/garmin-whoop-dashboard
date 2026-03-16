"""Readiness API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import Engine

from src.analytics.readiness_score import (
    ReadinessResult,
    compute_readiness,
    get_readiness_history,
)
from src.api.dependencies import get_engine_dep
from src.api.models import ContributingFactor, ReadinessHistoryItem, ReadinessResponse
from src.auth.dependencies import get_current_user
from src.auth.models import User

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
    response_model=None,
    summary="Today's readiness score",
)
async def readiness_today(
    local_date: date | None = Query(None, alias="date", description="User's local date (YYYY-MM-DD); defaults to server UTC date if omitted"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> Response | ReadinessResponse:
    """Compute the composite training readiness score for today.

    Returns 204 No Content when no data is available for this user.
    """
    try:
        target = local_date or date.today()
        result = compute_readiness(target, engine, user_id=current_user.id)
        if result.confidence == 0.0:
            return Response(status_code=204)
        return _to_response(result)
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
    current_user: User = Depends(get_current_user),
) -> list[ReadinessHistoryItem]:
    """Return daily readiness scores for a date range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        history = get_readiness_history(start, end, engine, user_id=current_user.id)
        return [ReadinessHistoryItem(**h) for h in history]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
