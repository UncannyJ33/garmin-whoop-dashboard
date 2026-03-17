"""Programmatic weekly digest module.

Generates 2–3 narrative takeaways about the past 7 days using template-based
text and the most significant metric deltas — no LLM required.

Public API
----------
get_weekly_digest(engine, user_id, target_date=today) -> WeeklyDigest

# TODO: Replace templates with LLM-generated insights for more natural language
#       and personalized recommendations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine

logger = logging.getLogger(__name__)

# % change thresholds that distinguish "noteworthy" from "stable"
_BIG_DELTA: float = 10.0
_SMALL_DELTA: float = 5.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class WeeklyDigest:
    """7-day narrative summary of fitness trends.

    Attributes:
        week_start: First day of the digest period.
        week_end: Last day of the digest period (the anchor / target date).
        takeaways: 2–3 standalone natural-language insight strings, ordered
            by priority (most urgent / impactful first).
        metrics_snapshot: Key metrics for the week (averages and totals),
            suitable for rendering a summary card in the frontend.
    """

    week_start: date
    week_end: date
    takeaways: list[str] = field(default_factory=list)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal candidate dataclass
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    text: str
    score: float   # higher = more important; used for ordering
    category: str  # "readiness" | "training" | "sleep" | "recovery" | "anomaly"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _prev_val(curr: float | None, delta_pct: float | None) -> float | None:
    """Reconstruct the previous-period value from current value and % change.

    The comparison dict stores ``round((curr - prev) / abs(prev) * 100, 1)``,
    so ``prev = curr / (1 + delta_pct / 100)`` when prev > 0.
    """
    if curr is None or delta_pct is None:
        return None
    denom = 1.0 + delta_pct / 100.0
    return curr / denom if denom != 0 else None


def _pct_str(delta: float) -> str:
    """Format a % change as '+12%' or '-8%'."""
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


# ---------------------------------------------------------------------------
# Candidate generators (one per category)
# ---------------------------------------------------------------------------


def _readiness_candidate(
    avg_readiness: float | None,
    delta_pct: float | None,
    limiting_factor: str | None = None,
) -> _Candidate | None:
    if avg_readiness is None:
        return None
    if delta_pct is not None and delta_pct <= -_BIG_DELTA:
        prev = _prev_val(avg_readiness, delta_pct)
        prev_str = f"{prev:.0f}%" if prev is not None else "last week's"
        drag = f" {limiting_factor} was the biggest drag." if limiting_factor else ""
        text = (
            f"Readiness dropped to {avg_readiness:.0f}% avg, "
            f"down {abs(delta_pct):.0f}% from {prev_str} last week.{drag}"
        ).rstrip()
        return _Candidate(text, score=80.0, category="readiness")
    if delta_pct is not None and delta_pct >= _BIG_DELTA:
        prev = _prev_val(avg_readiness, delta_pct)
        prev_str = f"{prev:.0f}%" if prev is not None else "last week"
        text = f"Readiness averaged {avg_readiness:.0f}% this week, up from {prev_str}."
        return _Candidate(text, score=70.0, category="readiness")
    text = f"Readiness held steady at {avg_readiness:.0f}% — consistent week overall."
    return _Candidate(text, score=15.0, category="readiness")


def _training_candidate(
    workout_count: int,
    total_training_minutes: float | None,
    prev_workout_count: int | None,
    acwr_result: Any,  # TrainingLoadResult | None
) -> _Candidate | None:
    zone = getattr(acwr_result, "zone", None)
    acwr = getattr(acwr_result, "acwr", None)
    acwr_str = f"{acwr:.2f}" if acwr is not None else "N/A"

    if zone in ("overreaching", "danger"):
        text = (
            f"Training load is in the overreaching zone "
            f"(ACWR {acwr_str}). Consider a lighter week."
        )
        return _Candidate(text, score=100.0, category="training")

    hours = total_training_minutes / 60.0 if total_training_minutes else None
    hours_str = f"{hours:.1f}h" if hours is not None else None
    acwr_context = f"ACWR is {acwr_str} ({zone})." if zone else f"ACWR is {acwr_str}."

    prev_n = prev_workout_count or 0
    sessions = f"{workout_count} session{'s' if workout_count != 1 else ''}"

    if prev_n > 0 and workout_count > prev_n * 1.25:
        hours_part = f" ({hours_str} total)" if hours_str else ""
        text = (
            f"You trained {sessions} this week{hours_part}, "
            f"up from {prev_n} last week. {acwr_context}"
        )
        return _Candidate(text, score=55.0, category="training")
    if prev_n > 0 and workout_count < prev_n * 0.75:
        text = (
            f"Lighter training week — {sessions} vs {prev_n}. "
            f"Your ACWR moved to {acwr_str} ({zone})." if zone else
            f"Lighter training week — {sessions} vs {prev_n}. {acwr_context}"
        )
        return _Candidate(text, score=50.0, category="training")
    text = f"You trained {sessions} this week. {acwr_context}"
    return _Candidate(text, score=20.0, category="training")


def _sleep_debt_status(avg_sleep_hours: float) -> str:
    """Simple heuristic sleep debt status from average nightly sleep hours."""
    if avg_sleep_hours < 6.5:
        return "accumulating"
    if avg_sleep_hours < 7.5:
        return "manageable"
    return "in good shape"


def _sleep_candidate(
    avg_sleep_duration: float | None,
    avg_deep_sleep: float | None,
    delta_pct: float | None,
) -> _Candidate | None:
    if avg_sleep_duration is None:
        return None
    hours = avg_sleep_duration / 60.0
    deep_pct = (
        round(avg_deep_sleep / avg_sleep_duration * 100.0)
        if avg_deep_sleep and avg_sleep_duration
        else None
    )
    deep_str = f" with {deep_pct}% deep sleep" if deep_pct is not None else ""

    if delta_pct is not None and delta_pct <= -_BIG_DELTA:
        debt = _sleep_debt_status(hours)
        text = (
            f"Sleep dropped to {hours:.1f}h avg, "
            f"{abs(delta_pct):.0f}% less than last week. "
            f"Sleep debt is {debt}."
        )
        return _Candidate(text, score=65.0, category="sleep")
    if delta_pct is not None and delta_pct >= _BIG_DELTA:
        text = (
            f"Sleep averaged {hours:.1f}h this week{deep_str} — "
            f"{_pct_str(delta_pct)} better than last week."
        )
        return _Candidate(text, score=50.0, category="sleep")
    text = f"Sleep averaged {hours:.1f}h this week{deep_str}."
    return _Candidate(text, score=15.0, category="sleep")


def _recovery_candidate(
    avg_recovery: float | None,
    delta_pct: float | None,
    limiting_factor: str | None = None,
) -> _Candidate | None:
    if avg_recovery is None:
        return None
    if delta_pct is not None and delta_pct <= -_BIG_DELTA:
        drag = f" — {limiting_factor} appears to be the main drag." if limiting_factor else "."
        text = (
            f"Recovery has been sluggish at {avg_recovery:.0f}% avg"
            f"{drag}"
        )
        return _Candidate(text, score=85.0, category="recovery")
    if delta_pct is not None and delta_pct >= _BIG_DELTA:
        text = (
            f"Recovery averaged {avg_recovery:.0f}% this week, "
            f"up {delta_pct:.0f}% from last week."
        )
        return _Candidate(text, score=60.0, category="recovery")
    # Low-delta recovery already covered by readiness — skip duplicate
    return None


def _anomaly_candidate(notable_anomalies: list[dict]) -> _Candidate | None:
    if not notable_anomalies:
        return None
    top = max(notable_anomalies, key=lambda a: abs(a.get("severity", 0)))
    metric = top.get("metric", "A metric")
    direction = top.get("direction", "anomalous")
    d = top.get("date", "")
    text = f"Notable: {metric} was {direction} on {d}"
    return _Candidate(text, score=55.0, category="anomaly")


def _select_takeaways(
    candidates: list[_Candidate],
    max_n: int = 3,
) -> list[str]:
    """Select up to ``max_n`` takeaways, one per category, sorted by score desc."""
    seen: set[str] = set()
    selected: list[_Candidate] = []
    for c in sorted(candidates, key=lambda x: -x.score):
        if c.category not in seen:
            seen.add(c.category)
            selected.append(c)
        if len(selected) >= max_n:
            break
    return [c.text for c in selected]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_weekly_digest(
    engine: Engine,
    user_id: str | None,
    target_date: date | None = None,
) -> WeeklyDigest:
    """Generate a 2–3 sentence programmatic digest for the past 7 days.

    Algorithm:
    1. Fetch the 7-day wellness summary (current week + % change vs prior week)
       via ``get_weekly_summary()``.
    2. Fetch ACWR for training-zone context via ``get_training_load_ratio()``
       (best-effort; digest continues if ACWR is unavailable).
    3. Generate one candidate takeaway per category (readiness, training,
       sleep, recovery, anomaly), scoring each by urgency and delta size.
    4. Select the top 2–3 highest-scoring candidates, one per category.

    When all metrics are near their baselines the takeaways describe a stable,
    consistent week so the digest is never empty.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID.
        target_date: Last day of the digest period (defaults to today).

    Returns:
        WeeklyDigest with ``takeaways`` and ``metrics_snapshot`` populated.

    # TODO: Replace templates with LLM-generated insights for more natural
    #       language and personalized recommendations.
    """
    if target_date is None:
        target_date = date.today()
    week_start = target_date - timedelta(days=6)

    # ------------------------------------------------------------------
    # 1. Fetch weekly summary
    # ------------------------------------------------------------------
    from src.analytics.trends import get_weekly_summary  # lazy — avoids circular

    summary = get_weekly_summary(engine, target_date, user_id=user_id)
    comparison = summary.get("comparison", {})

    avg_readiness: float | None = summary.get("avg_readiness")
    avg_recovery: float | None = summary.get("avg_recovery")
    avg_hrv: float | None = summary.get("avg_hrv")
    total_strain: float | None = summary.get("total_strain")
    workout_count: int = summary.get("workout_count") or 0
    total_training_minutes: float | None = summary.get("total_training_minutes")
    avg_sleep_duration: float | None = summary.get("avg_sleep_duration")
    avg_deep_sleep: float | None = summary.get("avg_deep_sleep")
    notable_anomalies: list[dict] = summary.get("notable_anomalies") or []

    # Reconstruct prev workout count for the training template
    count_delta = comparison.get("workout_count")
    prev_workout_count: int | None = None
    if count_delta is not None and workout_count:
        prev = _prev_val(float(workout_count), count_delta)
        prev_workout_count = round(prev) if prev is not None else None

    # ------------------------------------------------------------------
    # 2. Fetch ACWR (best-effort)
    # ------------------------------------------------------------------
    acwr_result = None
    try:
        from src.analytics.training_load import get_training_load_ratio  # lazy

        acwr_result = get_training_load_ratio(engine, user_id, target_date)
    except Exception:  # noqa: BLE001
        logger.debug("WeeklyDigest: ACWR unavailable")

    # ------------------------------------------------------------------
    # 3. Generate candidates
    # ------------------------------------------------------------------

    # Best-effort: top limiting factor for readiness/recovery decline context
    limiting_factor_name: str | None = None
    try:
        from src.analytics.limiting_factors import get_limiting_factors  # lazy

        factors = get_limiting_factors(engine, user_id, target_date, top_n=1)
        if factors:
            limiting_factor_name = factors[0].factor_name
    except Exception:  # noqa: BLE001
        logger.debug("WeeklyDigest: limiting factors unavailable")

    candidates: list[_Candidate] = []

    c = _readiness_candidate(
        avg_readiness, comparison.get("avg_readiness"), limiting_factor_name
    )
    if c:
        candidates.append(c)

    c = _training_candidate(
        workout_count,
        total_training_minutes,
        prev_workout_count,
        acwr_result,
    )
    if c:
        candidates.append(c)

    c = _sleep_candidate(
        avg_sleep_duration, avg_deep_sleep, comparison.get("avg_sleep_duration")
    )
    if c:
        candidates.append(c)

    c = _recovery_candidate(
        avg_recovery, comparison.get("avg_recovery"), limiting_factor_name
    )
    if c:
        candidates.append(c)

    c = _anomaly_candidate(notable_anomalies)
    if c:
        candidates.append(c)

    if not candidates:
        candidates.append(
            _Candidate(
                "Not enough data yet for a weekly summary",
                score=0.0,
                category="readiness",
            )
        )

    # ------------------------------------------------------------------
    # 4. Select top 2–3 takeaways (one per category, most urgent first)
    # ------------------------------------------------------------------
    takeaways = _select_takeaways(candidates)

    # ------------------------------------------------------------------
    # Metrics snapshot for the summary card
    # ------------------------------------------------------------------
    metrics_snapshot: dict[str, Any] = {
        "avg_readiness": round(avg_readiness, 1) if avg_readiness is not None else None,
        "avg_recovery": round(avg_recovery, 1) if avg_recovery is not None else None,
        "avg_hrv": round(avg_hrv, 1) if avg_hrv is not None else None,
        "total_strain": round(total_strain, 1) if total_strain is not None else None,
        "workout_count": workout_count,
        "total_training_hours": (
            round(total_training_minutes / 60.0, 1) if total_training_minutes else None
        ),
        "avg_sleep_hours": (
            round(avg_sleep_duration / 60.0, 1) if avg_sleep_duration else None
        ),
        "avg_deep_sleep_minutes": (
            round(avg_deep_sleep, 1) if avg_deep_sleep else None
        ),
        "acwr": getattr(acwr_result, "acwr", None),
        "acwr_zone": getattr(acwr_result, "zone", None),
    }

    return WeeklyDigest(
        week_start=week_start,
        week_end=target_date,
        takeaways=takeaways,
        metrics_snapshot=metrics_snapshot,
    )
