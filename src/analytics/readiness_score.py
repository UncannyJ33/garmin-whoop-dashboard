"""Training readiness score computation.

Combines Whoop and Garmin data (via unified_daily and unified_sleep) into a
single 0–100 readiness score with a four-level training recommendation.

All computation is pure: query data once, pass dicts to pure functions, return
a ReadinessResult. No ORM models used — raw SQL only, for speed and clarity.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights — adjust here, no other code needs to change
# ---------------------------------------------------------------------------

READINESS_WEIGHTS: dict[str, float] = {
    "whoop_recovery": 0.25,  # Whoop recovery score (0–100 directly)
    "hrv_trend": 0.20,  # Today's HRV vs 7-day rolling average
    "body_battery": 0.15,  # Garmin Body Battery peak (0–100 directly)
    "sleep_quality": 0.30,  # Whoop sleep performance (0–100 directly)
    "training_load": 0.10,  # Recent 3-day strain vs 7-day average (inverted)
}

# Recommendation bands — checked from highest threshold downward
_RECOMMENDATION_BANDS: list[tuple[float, str]] = [
    (80.0, "Push hard — your body is primed for high intensity"),
    (60.0, "Train normally — good to go for planned workout"),
    (40.0, "Go easy — consider reducing intensity or volume"),
    (0.0, "Rest day — recovery is the priority"),
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReadinessResult:
    """Readiness score for a single date.

    Attributes:
        date: The date this result covers.
        score: Composite readiness score, 0–100. None when no data available
            (confidence == 0).
        recommendation: Human-readable training guidance string.
        contributing_factors: Dict keyed by component ID. Each value contains:
            ``name`` (str), ``raw_value`` (float|None),
            ``normalized_value`` (float|None, 0–100),
            ``weight`` (float, original weight),
            ``effective_weight`` (float, after redistribution for missing sources).
        confidence: 0–1 fraction of maximum possible weight that was covered by
            available data. 1.0 means all five sources had data.
    """

    date: date
    score: float | None
    recommendation: str
    contributing_factors: dict[str, dict[str, Any]]
    confidence: float


# ---------------------------------------------------------------------------
# Pure normalization helpers
# ---------------------------------------------------------------------------


def _get_recommendation(score: float) -> str:
    """Map a 0–100 readiness score to a training recommendation string."""
    for threshold, label in _RECOMMENDATION_BANDS:
        if score >= threshold:
            return label
    return _RECOMMENDATION_BANDS[-1][1]


def _normalize_hrv_trend(
    today_hrv: float | None,
    history_hrv: list[float | None],
) -> float | None:
    """Normalize HRV trend via z-score against 7-day rolling history.

    A z-score of 0 (today == average) → 50.
    A z-score of +2 (two std above average) → 100 (clamped).
    A z-score of -2 → 0 (clamped).

    Returns:
        Normalized value 0–100, or None if today's HRV is missing.
        Returns 50.0 (neutral) when there are fewer than 3 history points
        or when the historical standard deviation is zero.
    """
    if today_hrv is None:
        return None

    valid = [v for v in history_hrv if v is not None]
    if len(valid) < 3:
        return 50.0  # not enough history — neutral

    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    std = math.sqrt(variance)

    if std == 0.0:
        return 50.0  # all identical — neutral

    z = (today_hrv - mean) / std
    return max(0.0, min(100.0, z * 25.0 + 50.0))


def _normalize_training_load(
    recent_strains: list[float | None],
    history_strains: list[float | None],
) -> float | None:
    """Normalize training load with an inverse relationship.

    Compares the average strain from the 3 most recent days to the 7-day
    historical average. Higher recent load → lower readiness contribution.

    Mapping:
        ratio 0.5 (low load) → 75
        ratio 1.0 (average)  → 50
        ratio 2.0 (double)   → 0 (clamped)

    Returns:
        Normalized value 0–100, or None if no data is available at all.
        Returns 50.0 (neutral) if historical average strain is zero.
    """
    valid_recent = [v for v in recent_strains if v is not None]
    valid_history = [v for v in history_strains if v is not None]

    if not valid_recent and not valid_history:
        return None

    history_avg = sum(valid_history) / len(valid_history) if valid_history else 0.0
    if history_avg == 0.0:
        return 50.0  # no historical load baseline — neutral

    recent_avg = sum(valid_recent) / len(valid_recent) if valid_recent else 0.0
    ratio = recent_avg / history_avg
    return max(0.0, min(100.0, 50.0 + (1.0 - ratio) * 50.0))


# ---------------------------------------------------------------------------
# Component computation
# ---------------------------------------------------------------------------


def _compute_components(
    today_row: dict | None,
    history_rows: list[dict],
    sleep_row: dict | None,
) -> dict[str, dict[str, Any]]:
    """Compute raw and normalized values for all five readiness components.

    Args:
        today_row: unified_daily row for the target date (or None).
        history_rows: unified_daily rows for the 7 days prior, most-recent-first.
        sleep_row: unified_sleep row for the target date (or None).

    Returns:
        Dict keyed by component ID with keys: name, raw_value,
        normalized_value, weight, effective_weight (set to 0.0, caller fills in).
    """
    # 1. Whoop Recovery Score — already 0–100
    wr_raw = today_row["whoop_recovery_score"] if today_row else None
    wr_norm = float(wr_raw) if wr_raw is not None else None

    # 2. HRV Trend — z-score vs prior 7 days
    today_hrv = today_row["whoop_hrv_rmssd"] if today_row else None
    history_hrv = [r["whoop_hrv_rmssd"] for r in history_rows]
    hrv_norm = _normalize_hrv_trend(today_hrv, history_hrv)

    # 3. Garmin Body Battery — already 0–100
    bb_raw = today_row["garmin_body_battery_high"] if today_row else None
    bb_norm = float(bb_raw) if bb_raw is not None else None

    # 4. Sleep Quality — Whoop sleep performance, already 0–100
    sq_raw = sleep_row["whoop_performance"] if sleep_row else None
    sq_norm = float(sq_raw) if sq_raw is not None else None

    # 5. Training Load Context — recent 3 days vs full 7-day history (inverted)
    # history_rows[0] = yesterday, [1] = 2 days ago, … so [:3] = most recent 3
    recent_strains = [r["whoop_strain"] for r in history_rows[:3]]
    all_strains = [r["whoop_strain"] for r in history_rows]
    load_norm = _normalize_training_load(recent_strains, all_strains)
    valid_recent = [v for v in recent_strains if v is not None]
    load_raw = sum(valid_recent) / len(valid_recent) if valid_recent else None

    return {
        "whoop_recovery": {
            "name": "Whoop Recovery Score",
            "raw_value": wr_raw,
            "normalized_value": wr_norm,
            "weight": READINESS_WEIGHTS["whoop_recovery"],
            "effective_weight": 0.0,
        },
        "hrv_trend": {
            "name": "HRV Trend",
            "raw_value": today_hrv,
            "normalized_value": hrv_norm,
            "weight": READINESS_WEIGHTS["hrv_trend"],
            "effective_weight": 0.0,
        },
        "body_battery": {
            "name": "Garmin Body Battery",
            "raw_value": bb_raw,
            "normalized_value": bb_norm,
            "weight": READINESS_WEIGHTS["body_battery"],
            "effective_weight": 0.0,
        },
        "sleep_quality": {
            "name": "Sleep Quality",
            "raw_value": sq_raw,
            "normalized_value": sq_norm,
            "weight": READINESS_WEIGHTS["sleep_quality"],
            "effective_weight": 0.0,
        },
        "training_load": {
            "name": "Training Load Context",
            "raw_value": load_raw,
            "normalized_value": load_norm,
            "weight": READINESS_WEIGHTS["training_load"],
            "effective_weight": 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Core computation (pure — works from pre-fetched dicts)
# ---------------------------------------------------------------------------


def _compute_from_data(
    target_date: date,
    daily_by_date: dict[str, dict],
    sleep_by_date: dict[str, dict],
    weights: dict[str, float] | None = None,
) -> ReadinessResult:
    """Compute readiness from pre-fetched data dictionaries.

    Missing components are skipped and their weights are redistributed
    proportionally to the remaining components.

    Args:
        target_date: The date being scored.
        daily_by_date: Dict of unified_daily rows keyed by ISO date string.
        sleep_by_date: Dict of unified_sleep rows keyed by ISO date string.
        weights: Optional weight overrides. Values need not sum to 1.0;
                 they are normalized internally.

    Returns:
        ReadinessResult for the target date.
    """
    effective_weights = weights if weights is not None else READINESS_WEIGHTS

    today_str = target_date.isoformat()
    today_row = daily_by_date.get(today_str)

    # Build history list: 7 days before target, most-recent-first
    history_rows: list[dict] = []
    for i in range(1, 8):
        d = (target_date - timedelta(days=i)).isoformat()
        if d in daily_by_date:
            history_rows.append(daily_by_date[d])

    sleep_row = sleep_by_date.get(today_str)

    components = _compute_components(today_row, history_rows, sleep_row)

    # Identify which components have data
    available_keys = [k for k, v in components.items() if v["normalized_value"] is not None]
    total_available_weight = sum(effective_weights[k] for k in available_keys)

    if not available_keys or total_available_weight == 0.0:
        score = None
        confidence = 0.0
        # effective_weights already initialised to 0.0 in _compute_components
    else:
        raw_score = 0.0
        for key, component in components.items():
            if key in available_keys:
                eff_w = effective_weights[key] / total_available_weight
                component["effective_weight"] = eff_w
                raw_score += component["normalized_value"] * eff_w
        confidence = min(1.0, total_available_weight)
        score = max(0.0, min(100.0, raw_score))

    return ReadinessResult(
        date=target_date,
        score=round(score, 2) if score is not None else None,
        recommendation=_get_recommendation(score if score is not None else 0.0),
        contributing_factors=components,
        confidence=round(confidence, 3),
    )


# ---------------------------------------------------------------------------
# Database-backed public API
# ---------------------------------------------------------------------------


def _fetch_data_window(
    start_date: date,
    end_date: date,
    engine: Engine,
    user_id: str | None = None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Fetch unified_daily and unified_sleep rows for the given date range.

    Args:
        start_date: Start of the fetch window.
        end_date: End of the fetch window.
        engine: SQLAlchemy engine.
        user_id: Optional app user UUID to scope results. When provided,
            adds ``AND user_id = :uid`` to both queries.

    Returns:
        (daily_by_date, sleep_by_date): dicts keyed by ISO date string.
    """
    if user_id is not None:
        uid_clause = "AND user_id = :uid"
        params: dict = {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "uid": user_id,
        }
    else:
        uid_clause = "AND user_id IS NULL"
        params = {"start": start_date.isoformat(), "end": end_date.isoformat()}

    with engine.connect() as conn:
        daily_rows = (
            conn.execute(
                text(
                    f"""
                SELECT date, whoop_recovery_score, whoop_hrv_rmssd,
                       whoop_strain, garmin_body_battery_high
                FROM unified_daily
                WHERE date >= :start AND date <= :end {uid_clause}
                ORDER BY date
                """
                ),
                params,
            )
            .mappings()
            .all()
        )

        sleep_rows = (
            conn.execute(
                text(
                    f"""
                SELECT date, whoop_performance
                FROM unified_sleep
                WHERE date >= :start AND date <= :end {uid_clause}
                """
                ),
                params,
            )
            .mappings()
            .all()
        )

    daily_by_date = {r["date"]: dict(r) for r in daily_rows}
    sleep_by_date = {r["date"]: dict(r) for r in sleep_rows}
    return daily_by_date, sleep_by_date


def compute_readiness(
    target_date: date,
    engine: Engine,
    user_id: str | None = None,
    weights: dict[str, float] | None = None,
) -> ReadinessResult:
    """Compute training readiness score for a single date.

    Queries unified_daily (for today + prior 7 days) and unified_sleep
    (for today) to build the composite score.

    Args:
        target_date: The date to score.
        engine: SQLAlchemy engine connected to the fitness database.
        user_id: App user UUID to scope data. When provided, only data
            belonging to that user is returned.
        weights: Optional dict overriding READINESS_WEIGHTS. Must use the same
                 five keys; values are normalized internally so they need not
                 sum to 1.0.

    Returns:
        ReadinessResult with score, recommendation, contributing_factors,
        and confidence.
    """
    fetch_start = target_date - timedelta(days=7)
    daily_by_date, sleep_by_date = _fetch_data_window(fetch_start, target_date, engine, user_id)
    result = _compute_from_data(target_date, daily_by_date, sleep_by_date, weights)
    logger.debug(
        "Readiness computed: date=%s score=%.1f confidence=%.2f sources=%d/5",
        target_date,
        result.score,
        result.confidence,
        sum(1 for f in result.contributing_factors.values() if f["normalized_value"] is not None),
    )
    return result


def get_readiness_history(
    start_date: date,
    end_date: date,
    engine: Engine,
    user_id: str | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Compute readiness scores for a date range in a single batch.

    Fetches all required data in two queries (daily + sleep), then computes
    each date's score from in-memory dicts. Suitable for trend charts.

    Args:
        start_date: First date to include (inclusive).
        end_date: Last date to include (inclusive).
        engine: SQLAlchemy engine connected to the fitness database.
        weights: Optional weight overrides (see compute_readiness).

    Returns:
        List of dicts for dates that have data (confidence > 0), sorted ascending:
        ``{"date": "YYYY-MM-DD", "score": float, "recommendation": str,
           "confidence": float}``.
        Dates with no data (confidence == 0) are omitted. Returns [] if no data.
    """
    # Pull 7 extra days of history so start_date has a full HRV window
    fetch_start = start_date - timedelta(days=7)
    daily_by_date, sleep_by_date = _fetch_data_window(fetch_start, end_date, engine, user_id)

    results: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        result = _compute_from_data(current, daily_by_date, sleep_by_date, weights)
        if result.confidence > 0:
            results.append(
                {
                    "date": current.isoformat(),
                    "score": result.score,
                    "recommendation": result.recommendation,
                    "confidence": result.confidence,
                }
            )
        current += timedelta(days=1)

    return results
