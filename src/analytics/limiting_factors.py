"""Limiting factors analytics module.

Identifies the top 1–2 readiness components most suppressing today's score,
with contextual natural-language explanations.

Public API
----------
get_limiting_factors(engine, user_id, target_date=today, top_n=2) -> list[LimitingFactor]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine

from src.analytics.readiness_score import _compute_from_data, _fetch_data_window
from src.analytics.training_load import get_training_load_ratio

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Thresholds
# -----------------------------------------------------------------------

# Minimum number of prior-day normalized scores required to declare a baseline
_MIN_HISTORY: int = 3

# Severity bands: |deviation_pct| below 7-day average
_MILD_THRESHOLD: float = 5.0
_MODERATE_THRESHOLD: float = 15.0
_SIGNIFICANT_THRESHOLD: float = 30.0

# Factor display names (matches readiness_score contributing_factors keys)
_FACTOR_NAMES: dict[str, str] = {
    "whoop_recovery": "Recovery Score",
    "hrv_trend": "HRV Trend",
    "body_battery": "Body Battery",
    "sleep_quality": "Sleep Quality",
    "training_load": "Training Load",
}


# -----------------------------------------------------------------------
# Result dataclass
# -----------------------------------------------------------------------


@dataclass
class LimitingFactor:
    """One readiness component that is suppressing today's score.

    Attributes:
        factor_name: Human-readable component name (e.g. "Sleep Quality").
        current_value: Raw metric value today.
        current_value_display: Formatted current value (e.g. "52%", "38ms").
        normalized_score: Today's normalized 0–100 score as used in the
            readiness calculation.
        seven_day_avg: 7-day average of the raw metric (prior 7 days).
        seven_day_avg_display: Formatted 7-day average.
        deviation_pct: How far the normalized score is below its 7-day
            baseline as a percentage (negative = below average).
        explanation: One-sentence natural-language context string.
        severity: "mild" | "moderate" | "significant".
    """

    factor_name: str
    current_value: float
    current_value_display: str
    normalized_score: float
    seven_day_avg: float
    seven_day_avg_display: str
    deviation_pct: float
    explanation: str
    severity: str


# -----------------------------------------------------------------------
# Pure helpers
# -----------------------------------------------------------------------


def _avg(values: list[float | None]) -> float | None:
    """Mean of non-None values; None when fewer than _MIN_HISTORY exist."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if len(valid) >= _MIN_HISTORY else None


def _classify_severity(deviation: float) -> str:
    """deviation is negative (below baseline). Returns severity string."""
    abs_dev = abs(deviation)
    if abs_dev >= _SIGNIFICANT_THRESHOLD:
        return "significant"
    if abs_dev >= _MODERATE_THRESHOLD:
        return "moderate"
    return "mild"


def _severity_word(severity: str) -> str:
    return {
        "significant": "dragging",
        "moderate": "pulling",
        "mild": "slightly affecting",
    }[severity]


def _fmt(factor_key: str, value: float) -> str:
    """Format a raw metric value for display."""
    if factor_key in ("whoop_recovery", "sleep_quality"):
        return f"{value:.0f}%"
    if factor_key == "hrv_trend":
        return f"{value:.0f}ms"
    return f"{value:.0f}"


def _raw_7d_avgs(
    daily_by_date: dict,
    sleep_by_date: dict,
    target_date: date,
) -> dict[str, float | None]:
    """Return 7-day average of raw metrics for the 7 days prior to target_date.

    Used for display values (current vs avg in explanation text).
    Skips any day/factor that has no data.
    """
    rec: list[float] = []
    hrv: list[float] = []
    bb: list[float] = []
    sq: list[float] = []

    for i in range(1, 8):
        d = (target_date - timedelta(days=i)).isoformat()
        daily = daily_by_date.get(d, {})
        if daily.get("whoop_recovery_score") is not None:
            rec.append(float(daily["whoop_recovery_score"]))
        if daily.get("whoop_hrv_rmssd") is not None:
            hrv.append(float(daily["whoop_hrv_rmssd"]))
        if daily.get("garmin_body_battery_high") is not None:
            bb.append(float(daily["garmin_body_battery_high"]))
        sl = sleep_by_date.get(d, {})
        if sl.get("whoop_performance") is not None:
            sq.append(float(sl["whoop_performance"]))

    def _a(lst: list[float]) -> float | None:
        return sum(lst) / len(lst) if len(lst) >= _MIN_HISTORY else None

    return {
        "whoop_recovery": _a(rec),
        "hrv_trend": _a(hrv),
        "body_battery": _a(bb),
        "sleep_quality": _a(sq),
        "training_load": None,  # handled via ACWR
    }


def _build_explanation(
    factor_key: str,
    current_raw: float,
    seven_day_avg_raw: float,
    deviation_pct: float,
    severity: str,
    *,
    acute_load: float | None = None,
    chronic_load: float | None = None,
) -> str:
    """Build a natural-language explanation for a limiting factor."""
    if factor_key == "sleep_quality":
        word = _severity_word(severity)
        return (
            f"Sleep quality is {word} you — "
            f"{current_raw:.0f}% vs your 7d avg of {seven_day_avg_raw:.0f}%"
        )

    if factor_key == "hrv_trend":
        abs_dev = abs(deviation_pct)
        direction = "low" if deviation_pct < 0 else "elevated"
        below_above = "below" if deviation_pct < 0 else "above"
        return (
            f"HRV is {direction} at {current_raw:.0f}ms — "
            f"{abs_dev:.0f}% {below_above} your baseline of {seven_day_avg_raw:.0f}ms"
        )

    if factor_key == "whoop_recovery":
        return (
            f"Recovery hasn't bounced back — "
            f"{current_raw:.0f}% vs your 7d avg of {seven_day_avg_raw:.0f}%"
        )

    if factor_key == "body_battery":
        return (
            f"Body Battery is low at {current_raw:.0f} — "
            f"you typically start the day at {seven_day_avg_raw:.0f}"
        )

    if factor_key == "training_load":
        level = "high" if abs(deviation_pct) >= _MODERATE_THRESHOLD else "elevated"
        if acute_load is not None and chronic_load is not None:
            return (
                f"Training load is {level} — "
                f"{acute_load:.1f} strain in 7 days vs {chronic_load:.1f} in the prior 28"
            )
        return f"Training load is {level} — above your recent baseline"

    return f"{_FACTOR_NAMES.get(factor_key, factor_key)} is {abs(deviation_pct):.0f}% below your 7-day average"


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def get_limiting_factors(
    engine: Engine,
    user_id: str | None,
    target_date: date | None = None,
    top_n: int = 2,
) -> list[LimitingFactor]:
    """Identify the top ``top_n`` readiness components dragging today's score.

    Algorithm:
    1. Fetch 14 days of data (enough for prior days to have full HRV history).
    2. Compute today's readiness to get each factor's normalized_value.
    3. Recompute readiness for each of the 7 prior days using the same data
       window to build each factor's baseline normalized score.
    4. Factors whose normalized score is ≥ _MILD_THRESHOLD below baseline
       are candidates.
    5. For display, compute 7-day average of raw metric values.
    6. Return the top ``top_n`` candidates sorted by severity (most limiting first).

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID.
        target_date: Date to evaluate (defaults to today).
        top_n: Maximum number of limiting factors to return.

    Returns:
        List of LimitingFactor sorted most-limiting-first.  Empty list when
        all factors are near or above baseline, or when there is no data.
    """
    if target_date is None:
        target_date = date.today()

    # Fetch 14 days so prior-day computations have full 7-day HRV histories
    fetch_start = target_date - timedelta(days=14)
    daily_by_date, sleep_by_date = _fetch_data_window(fetch_start, target_date, engine, user_id)

    # Today's readiness factors
    today_result = _compute_from_data(target_date, daily_by_date, sleep_by_date)
    if today_result.confidence == 0.0:
        return []

    # Build 7-day prior baseline of normalized scores per factor
    prior_norm: dict[str, list[float | None]] = {k: [] for k in today_result.contributing_factors}
    for i in range(1, 8):
        prior = _compute_from_data(target_date - timedelta(days=i), daily_by_date, sleep_by_date)
        for key in prior_norm:
            prior_norm[key].append(prior.contributing_factors[key]["normalized_value"])

    # 7-day raw metric averages (for display strings and explanations)
    raw_7d = _raw_7d_avgs(daily_by_date, sleep_by_date, target_date)

    # ACWR data for training_load explanation (best-effort)
    acwr = None
    try:
        acwr = get_training_load_ratio(engine, user_id, target_date)
    except Exception:  # noqa: BLE001
        logger.warning("ACWR unavailable for limiting factor explanation", exc_info=True)

    limiting: list[LimitingFactor] = []

    for key, factor in today_result.contributing_factors.items():
        norm_today = factor["normalized_value"]
        raw_today = factor["raw_value"]
        if norm_today is None:
            continue

        avg_norm = _avg(prior_norm[key])
        if avg_norm is None or avg_norm == 0:
            continue

        # Deviation on normalized score (handles inverted training_load correctly)
        deviation = (norm_today - avg_norm) / avg_norm * 100

        # Skip factors that are not meaningfully below baseline
        if deviation >= -_MILD_THRESHOLD:
            continue

        severity = _classify_severity(deviation)

        if key == "training_load":
            # Use ACWR totals for display; fall back to normalized score display
            if acwr is not None:
                c_val = acwr.acute_load
                avg_val = acwr.chronic_load / 4 if acwr.chronic_load else avg_norm
            else:
                c_val = raw_today if raw_today is not None else norm_today
                avg_val = raw_7d.get(key) or avg_norm
            limiting.append(
                LimitingFactor(
                    factor_name=_FACTOR_NAMES[key],
                    current_value=round(c_val, 2),
                    current_value_display=f"{c_val:.1f}",
                    normalized_score=round(norm_today, 2),
                    seven_day_avg=round(avg_val, 2),
                    seven_day_avg_display=f"{avg_val:.1f}",
                    deviation_pct=round(deviation, 1),
                    explanation=_build_explanation(
                        key,
                        c_val,
                        avg_val,
                        deviation,
                        severity,
                        acute_load=acwr.acute_load if acwr else None,
                        chronic_load=acwr.chronic_load if acwr else None,
                    ),
                    severity=severity,
                )
            )
        else:
            raw_avg = raw_7d.get(key)
            if raw_avg is None or raw_today is None:
                continue
            limiting.append(
                LimitingFactor(
                    factor_name=_FACTOR_NAMES[key],
                    current_value=round(raw_today, 2),
                    current_value_display=_fmt(key, raw_today),
                    normalized_score=round(norm_today, 2),
                    seven_day_avg=round(raw_avg, 2),
                    seven_day_avg_display=_fmt(key, raw_avg),
                    deviation_pct=round(deviation, 1),
                    explanation=_build_explanation(key, raw_today, raw_avg, deviation, severity),
                    severity=severity,
                )
            )

    # Sort most-limiting first (most negative deviation)
    limiting.sort(key=lambda f: f.deviation_pct)
    return limiting[:top_n]
