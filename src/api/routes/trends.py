"""Trends API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.anomaly_store import get_cached_anomalies, get_cached_enriched_anomalies
from src.analytics.cache import analytics_cache
from src.analytics.trends import (
    get_batch_metric_trends,
    get_enriched_anomalies,
    get_metric_trend,
    get_weekly_summary,
)
from src.api.dependencies import get_engine_dep
from src.api.models import (
    AnomalyItem,
    EnrichedAnomalyResponse,
    MetricTrendResponse,
    WeeklySummaryResponse,
)
from src.auth.dependencies import get_current_user
from src.auth.models import User

router = APIRouter(prefix="/api/trends", tags=["trends"])

_ANOMALY_METRICS = [
    "recovery",
    "hrv",
    "resting_hr",
    "strain",
    "body_battery",
    "sleep_duration",
    "deep_sleep",
]

_METRIC_LABELS: dict[str, str] = {
    "recovery": "Recovery Score",
    "hrv": "HRV",
    "resting_hr": "Resting HR",
    "strain": "Strain (Daily)",
    "body_battery": "Body Battery",
    "sleep_duration": "Sleep Duration",
    "deep_sleep": "Deep Sleep",
}


def _trend_to_response(t) -> MetricTrendResponse:
    return MetricTrendResponse(
        metric_name=t.metric_name,
        dates=t.dates,
        values=t.values,
        rolling_avg_7d=t.rolling_avg_7d,
        rolling_avg_30d=t.rolling_avg_30d,
        rolling_std_7d=t.rolling_std_7d,
        anomalies=t.anomalies,
        trend_direction=t.trend_direction,
    )


# Fixed paths MUST be declared before the {metric} parameterized path.


@router.get(
    "/weekly-summary",
    response_model=WeeklySummaryResponse,
    summary="7-day wellness summary with week-over-week comparison",
)
async def weekly_summary(
    end: date = Query(default=None, description="End date (YYYY-MM-DD); defaults to today"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> WeeklySummaryResponse:
    """Return current-week averages and % change vs the prior week."""
    target = end or date.today()
    cache_key_date = target.isoformat()
    cached = analytics_cache.get(current_user.id, "weekly_summary", cache_key_date)
    if cached is not None:
        return cached  # type: ignore[return-value]
    try:
        result = get_weekly_summary(engine, target, user_id=current_user.id)
        resp = WeeklySummaryResponse(**result)
        analytics_cache.set(current_user.id, "weekly_summary", cache_key_date, value=resp)
        return resp
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/anomalies",
    response_model=list[AnomalyItem],
    summary="Anomaly log across all tracked metrics",
)
async def anomaly_log(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[AnomalyItem]:
    """Return all anomalous days (≥ 2σ from 7-day prior mean) across key metrics."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")

    # Try pre-computed cache first (populated after each sync)
    cached = get_cached_anomalies(engine, current_user.id, start, end)
    if cached:
        return [AnomalyItem(**c) for c in cached]

    # Fallback: compute live (first load before any sync, or cache miss)
    rows: list[AnomalyItem] = []
    try:
        trends = get_batch_metric_trends(
            engine, list(_ANOMALY_METRICS), start, end, user_id=current_user.id
        )
    except Exception:  # noqa: BLE001
        trends = {}
    for metric in _ANOMALY_METRICS:
        trend = trends.get(metric)
        if trend is None:
            continue
        for a in trend.anomalies:
            rows.append(
                AnomalyItem(
                    date=a["date"],
                    metric=_METRIC_LABELS.get(metric, metric),
                    value=a["value"],
                    direction=a["direction"],
                    severity=abs(a["severity"]),
                )
            )
    return sorted(rows, key=lambda x: x.date, reverse=True)


@router.get(
    "/anomalies/enriched",
    response_model=list[EnrichedAnomalyResponse],
    summary="Anomaly log with 48-hour contextual explanations",
)
async def enriched_anomaly_log(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of anomalies to return"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[EnrichedAnomalyResponse]:
    """Return anomalous days enriched with training load, sleep, and co-anomaly context.

    Each entry includes a natural-language explanation of what was happening
    in the 48 hours surrounding the anomaly.
    """
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")

    # Try pre-computed cache first
    cached = get_cached_enriched_anomalies(engine, current_user.id, start, end, limit=limit)
    if cached:
        return [EnrichedAnomalyResponse(**c) for c in cached]

    # Fallback: compute live
    try:
        results = get_enriched_anomalies(engine, current_user.id, start, end, limit=limit)
        return [EnrichedAnomalyResponse(**vars(r)) for r in results]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{metric}",
    response_model=MetricTrendResponse,
    summary="Rolling trend for a single metric",
)
async def metric_trend(
    metric: str,
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> MetricTrendResponse:
    """Return daily values, 7d/30d rolling averages, anomalies, and trend direction.

    Supported metrics: recovery, hrv, resting_hr, body_battery, strain,
    sleep_duration, deep_sleep, readiness, training_load (and aliases).
    """
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        trend = get_metric_trend(engine, metric, start, end, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _trend_to_response(trend)
