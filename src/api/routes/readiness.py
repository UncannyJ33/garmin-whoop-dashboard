"""Readiness API routes."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import Engine

from src.analytics.cache import analytics_cache
from src.analytics.limiting_factors import get_limiting_factors
from src.analytics.readiness_score import (
    ReadinessResult,
    compute_readiness,
    get_readiness_history,
)
from src.api.dependencies import DateRangeParams, get_engine_dep
from src.api.models import (
    ContributingFactor,
    LimitingFactorResponse,
    ReadinessHistoryItem,
    ReadinessResponse,
)
from src.auth.dependencies import get_current_user
from src.auth.models import User

logger = logging.getLogger(__name__)

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
    responses={204: {"description": "No readiness data for the date"}},
    summary="Today's readiness score",
)
async def readiness_today(
    local_date: date | None = Query(
        None,
        alias="date",
        description="User's local date (YYYY-MM-DD); defaults to server UTC date if omitted",
    ),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> Response | ReadinessResponse:
    """Compute the composite training readiness score for today.

    Returns 204 No Content when no data is available for this user.
    """
    try:
        target = local_date or date.today()
        cache_key_date = target.isoformat()
        cached = analytics_cache.get(current_user.id, "readiness", cache_key_date)
        if cached is not None:
            return cached  # type: ignore[return-value]
        result = compute_readiness(target, engine, user_id=current_user.id)
        if result.confidence == 0.0:
            return Response(status_code=204)
        resp = _to_response(result)
        analytics_cache.set(current_user.id, "readiness", cache_key_date, value=resp)
        return resp
    except Exception as exc:
        logger.exception("readiness_today failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/limiting-factors",
    response_model=list[LimitingFactorResponse],
    summary="Top factors suppressing today's readiness score",
)
async def readiness_limiting_factors(
    local_date: date | None = Query(
        None,
        alias="date",
        description="User's local date (YYYY-MM-DD); defaults to server UTC date if omitted",
    ),
    top_n: int = Query(2, ge=1, le=5, description="Maximum number of factors to return"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[LimitingFactorResponse]:
    """Return the top factors dragging today's readiness score below baseline.

    Each factor includes the current value, 7-day average, deviation percentage,
    and a plain-language explanation.  Returns an empty list on good days when
    all factors are near or above their 7-day baselines.
    """
    try:
        target = local_date or date.today()
        factors = get_limiting_factors(engine, current_user.id, target, top_n=top_n)
        return [LimitingFactorResponse(**vars(f)) for f in factors]
    except Exception as exc:
        logger.exception("readiness_limiting_factors failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/history",
    response_model=list[ReadinessHistoryItem],
    summary="Readiness score history",
)
async def readiness_history(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[ReadinessHistoryItem]:
    """Return daily readiness scores for a date range."""
    start, end = dates.validated()
    try:
        history = get_readiness_history(start, end, engine, user_id=current_user.id)
        return [ReadinessHistoryItem(**h) for h in history]
    except Exception as exc:
        logger.exception("readiness_history failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
