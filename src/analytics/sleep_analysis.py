"""Sleep impact analysis module.

Combines unified_sleep with surrounding days of unified_daily and training
data to surface how sleep quality, debt, and consistency relate to next-day
recovery and training load.

Public API
----------
get_sleep_insights(engine, start_date, end_date, target_sleep_minutes=480)
    -> list[SleepInsight]

get_strain_sleep_correlation(engine, days=30) -> dict
    Pearson r between prior-day strain and sleep/recovery outcomes.

get_sleep_consistency(engine, days=30) -> dict
    Bedtime variance, average total sleep, sleep debt trend.
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
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TARGET_SLEEP_MINUTES: float = 480.0  # 8 hours
_MIN_CORRELATION_SAMPLE: int = 7
_STABLE_SLOPE_THRESHOLD: float = 5.0  # minutes/day; below = "stable"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SleepInsight:
    """All sleep-related metrics and context for a single night.

    ``date`` is the wake-up date (the morning you got out of bed).

    Fields prefixed ``previous_day_`` come from the calendar day before
    the wake-up date (the day on which training occurred before this sleep).
    Fields prefixed ``next_day_`` come from the wake-up date itself
    (Whoop recovery and Garmin Body Battery are recorded at the start of
    the new cycle, i.e. the morning you wake up).
    """

    date: str  # wake-up date YYYY-MM-DD
    total_sleep_minutes: float | None
    deep_minutes: float | None
    light_minutes: float | None
    rem_minutes: float | None
    awake_minutes: float | None
    sleep_performance: float | None  # Whoop 0–100
    sleep_efficiency: float | None  # Whoop 0–100
    previous_day_strain: float | None  # Whoop cycle strain
    previous_day_training_load: float | None  # Garmin activity training load (sum)
    next_day_recovery_score: float | None  # Whoop recovery on wake-up date
    next_day_body_battery: int | None  # Garmin BB high on wake-up date
    sleep_debt_estimate: float | None  # rolling 7-day avg − target (min, neg = deficit)


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient between two equal-length lists.

    Returns None if the lists have fewer than ``_MIN_CORRELATION_SAMPLE``
    elements or if either variable has zero variance.
    """
    n = len(xs)
    if n < _MIN_CORRELATION_SAMPLE:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_x = sum((v - mean_x) ** 2 for v in xs)
    ss_y = sum((v - mean_y) ** 2 for v in ys)
    if ss_x == 0.0 or ss_y == 0.0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(ss_x * ss_y)


def _linear_slope(ys: list[float]) -> float | None:
    """Ordinary least squares slope for y ~ index.

    xs are implicitly 0, 1, 2, …, n-1.
    Returns None if fewer than 2 data points.
    """
    n = len(ys)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = sum(ys) / n
    ss_x = sum((x - mean_x) ** 2 for x in xs)
    if ss_x == 0.0:
        return None
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    return cov / ss_x


def _time_str_to_fractional_hours(iso_str: str | None) -> float | None:
    """Extract fractional hours from an ISO 8601 datetime string.

    Times before noon (hour < 12) are assumed to be early-morning
    post-midnight and have 24 added so that midnight-crossing averages
    work correctly (e.g. 01:30 → 25.5, 22:30 → 22.5).

    For wake times (which are always morning) use this function without
    the midnight offset — caller should subtract 24 after averaging if
    the mean exceeds 24.
    """
    if not iso_str:
        return None
    try:
        # Accept ISO 8601 with or without timezone suffix
        time_part = iso_str.split("T")[1] if "T" in iso_str else iso_str
        # Strip timezone offset / Z
        for sep in ("+", "-", "Z"):
            time_part = time_part.split(sep)[0]
        h, m, *_ = time_part.split(":")
        hours = int(h) + int(m) / 60.0
        return hours
    except (IndexError, ValueError):
        return None


def _avg_nonull(values: list[float | None]) -> float | None:
    """Mean of non-None values, or None if there are no valid values."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _std_nonull(values: list[float | None]) -> float | None:
    """Population std dev of non-None values, or None if fewer than 2."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return None
    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    return math.sqrt(variance)


def _add_days(date_str: str, days: int) -> str:
    return (date.fromisoformat(date_str) + timedelta(days=days)).isoformat()


def _net_sleep(row: dict) -> float | None:
    """Total sleep minus awake time for a unified_sleep row.

    Returns None when total_sleep_minutes is absent (no data for that night).
    Treats missing awake_minutes as zero.
    """
    total = row.get("total_sleep_minutes")
    if total is None:
        return None
    return total - (row.get("awake_minutes") or 0.0)


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------


def _fetch_unified_sleep(engine: Engine, start: str, end: str) -> dict[str, dict]:
    """Fetch unified_sleep rows keyed by date."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT date, total_sleep_minutes, deep_sleep_minutes,
                       light_sleep_minutes, rem_sleep_minutes, awake_minutes,
                       whoop_performance, whoop_efficiency
                FROM unified_sleep
                WHERE date >= :start AND date <= :end
                """
                ),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return {r["date"]: dict(r) for r in rows}


def _fetch_unified_daily(engine: Engine, start: str, end: str) -> dict[str, dict]:
    """Fetch unified_daily rows keyed by date."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT date, whoop_strain, whoop_recovery_score,
                       garmin_body_battery_high
                FROM unified_daily
                WHERE date >= :start AND date <= :end
                """
                ),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return {r["date"]: dict(r) for r in rows}


def _fetch_training_load_by_date(engine: Engine, start: str, end: str) -> dict[str, float]:
    """Sum garmin_activities.training_load per day via unified_workouts join."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT uw.date, SUM(ga.training_load) AS total_load
                FROM unified_workouts uw
                JOIN garmin_activities ga
                  ON uw.garmin_activity_id = ga.activity_id
                WHERE ga.training_load IS NOT NULL
                  AND uw.date >= :start
                  AND uw.date <= :end
                GROUP BY uw.date
                """
                ),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return {r["date"]: r["total_load"] for r in rows}


def _fetch_whoop_sleep_times(engine: Engine, start: str, end: str) -> list[dict]:
    """Fetch non-nap whoop_sleep rows with start/end timestamps.

    Filters by DATE(end_time) (wake-up date) within the given range.
    Returns rows sorted by end_time ascending.
    """
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT start_time, end_time
                FROM whoop_sleep
                WHERE nap = 0
                  AND SUBSTR(end_time, 1, 10) >= :start
                  AND SUBSTR(end_time, 1, 10) <= :end
                ORDER BY end_time
                """
                ),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


def _build_insight(
    sleep_row: dict,
    daily_by_date: dict[str, dict],
    training_load_by_date: dict[str, float],
    sleep_history_by_date: dict[str, dict],
    target_sleep_minutes: float,
) -> SleepInsight:
    """Build one SleepInsight from pre-fetched data dicts."""
    wake_date = sleep_row["date"]
    prev_date = _add_days(wake_date, -1)

    prev_daily = daily_by_date.get(prev_date, {})
    today_daily = daily_by_date.get(wake_date, {})

    # 7-day rolling average (ending at wake_date, inclusive) — awake time excluded
    last_7 = [_net_sleep(sleep_history_by_date.get(_add_days(wake_date, -i), {})) for i in range(7)]
    rolling_avg = _avg_nonull(last_7)
    debt = (rolling_avg - target_sleep_minutes) if rolling_avg is not None else None

    bb = today_daily.get("garmin_body_battery_high")

    return SleepInsight(
        date=wake_date,
        total_sleep_minutes=sleep_row.get("total_sleep_minutes"),
        deep_minutes=sleep_row.get("deep_sleep_minutes"),
        light_minutes=sleep_row.get("light_sleep_minutes"),
        rem_minutes=sleep_row.get("rem_sleep_minutes"),
        awake_minutes=sleep_row.get("awake_minutes"),
        sleep_performance=sleep_row.get("whoop_performance"),
        sleep_efficiency=sleep_row.get("whoop_efficiency"),
        previous_day_strain=prev_daily.get("whoop_strain"),
        previous_day_training_load=training_load_by_date.get(prev_date),
        next_day_recovery_score=today_daily.get("whoop_recovery_score"),
        next_day_body_battery=int(bb) if bb is not None else None,
        sleep_debt_estimate=debt,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_sleep_insights(
    engine: Engine,
    start_date: date,
    end_date: date,
    target_sleep_minutes: float = DEFAULT_TARGET_SLEEP_MINUTES,
) -> list[SleepInsight]:
    """Build sleep insight records for a date range.

    Fetches unified_sleep + unified_daily (for the day before and after each
    sleep date) and garmin training load in a small set of batched queries.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        start_date: First wake-up date to include (inclusive).
        end_date: Last wake-up date to include (inclusive).
        target_sleep_minutes: Nightly sleep target used for debt calculation.
            Defaults to 480 (8 hours).

    Returns:
        List of SleepInsight sorted by date ascending.  Dates with no sleep
        data are omitted.
    """
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    # Extra history for rolling debt (6 days before start) and prev-day lookup
    history_start = _add_days(start_str, -6)
    daily_start = _add_days(start_str, -1)

    sleep_all = _fetch_unified_sleep(engine, history_start, end_str)
    daily_all = _fetch_unified_daily(engine, daily_start, end_str)
    load_all = _fetch_training_load_by_date(engine, daily_start, end_str)

    insights = []
    current = start_date
    while current <= end_date:
        d = current.isoformat()
        if d in sleep_all:
            insights.append(
                _build_insight(
                    sleep_all[d],
                    daily_all,
                    load_all,
                    sleep_all,  # full history dict for rolling avg
                    target_sleep_minutes,
                )
            )
        current += timedelta(days=1)

    return insights


def _correlation_result(pairs: list[tuple[float, float]], label: str) -> dict[str, Any]:
    """Build a correlation sub-dict from a list of (x, y) float pairs."""
    n = len(pairs)
    if n < _MIN_CORRELATION_SAMPLE:
        return {
            "r": None,
            "n": n,
            "sufficient_data": False,
            "message": (
                f"Need at least {_MIN_CORRELATION_SAMPLE} paired observations. Found: {n}."
            ),
        }
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    r = _pearson_r(xs, ys)
    return {"r": r, "n": n, "sufficient_data": True}


def get_strain_sleep_correlation(
    engine: Engine,
    days: int = 30,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Calculate Pearson correlations between prior-day strain and sleep outcomes.

    Analyses three relationships:
    - ``strain_vs_total_sleep``:   does high strain lead to more total sleep?
    - ``strain_vs_deep_sleep``:    does high strain increase deep (SWS) sleep?
    - ``strain_vs_next_day_recovery``: does more sleep after high strain improve recovery?

    Args:
        engine: SQLAlchemy engine for the fitness database.
        days: Number of most-recent days to analyse. Defaults to 30.
        end_date: Last date to include. Defaults to today. Pass a fixed date
            in tests to avoid interference from other test data.

    Returns:
        Dict with keys ``strain_vs_total_sleep``, ``strain_vs_deep_sleep``,
        ``strain_vs_next_day_recovery`` (each a sub-dict with ``r``, ``n``,
        ``sufficient_data``), plus ``days_analyzed``.
    """
    end = end_date or date.today()
    start = end - timedelta(days=days - 1)
    insights = get_sleep_insights(engine, start, end)

    strain_total: list[tuple[float, float]] = []
    strain_deep: list[tuple[float, float]] = []
    strain_recovery: list[tuple[float, float]] = []

    for ins in insights:
        s = ins.previous_day_strain
        if s is None:
            continue
        if ins.total_sleep_minutes is not None:
            strain_total.append((s, ins.total_sleep_minutes))
        if ins.deep_minutes is not None:
            strain_deep.append((s, ins.deep_minutes))
        if ins.next_day_recovery_score is not None:
            strain_recovery.append((s, ins.next_day_recovery_score))

    return {
        "strain_vs_total_sleep": _correlation_result(strain_total, "strain_vs_total_sleep"),
        "strain_vs_deep_sleep": _correlation_result(strain_deep, "strain_vs_deep_sleep"),
        "strain_vs_next_day_recovery": _correlation_result(
            strain_recovery, "strain_vs_next_day_recovery"
        ),
        "days_analyzed": days,
    }


def get_sleep_consistency(
    engine: Engine,
    days: int = 30,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Summarise sleep schedule consistency over the most recent N days.

    Bedtime and wake time are extracted from ``whoop_sleep`` timestamps.
    Times before noon are assumed to be early-morning (post-midnight) and are
    offset by +24 h for averaging, so midnight-crossing schedules compute
    correctly.

    Sleep debt trend is estimated via linear regression of the per-day debt
    series. A negative slope means debt is growing more negative (worsening);
    positive means improving.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        days: Number of most-recent days to analyse. Defaults to 30.
        end_date: Last date to include. Defaults to today. Pass a fixed date
            in tests to avoid interference from other test data.

    Returns:
        Dict with consistency metrics, or ``{"insufficient_data": True, ...}``
        if fewer than ``_MIN_CORRELATION_SAMPLE`` nights are available.
    """
    end = end_date or date.today()
    start = end - timedelta(days=days - 1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    whoop_rows = _fetch_whoop_sleep_times(engine, start_str, end_str)
    n = len(whoop_rows)

    if n < _MIN_CORRELATION_SAMPLE:
        return {
            "insufficient_data": True,
            "message": (f"Need at least {_MIN_CORRELATION_SAMPLE} nights of data. Found: {n}."),
            "sample_size": n,
        }

    # Bedtime (start_time): offset times before noon by +24 so midnight averages work
    bed_hours_raw = [_time_str_to_fractional_hours(r["start_time"]) for r in whoop_rows]
    bed_hours = [h + 24.0 if (h is not None and h < 12.0) else h for h in bed_hours_raw]

    # Wake time (end_time): typically 5–10 AM, no offset needed
    wake_hours = [_time_str_to_fractional_hours(r["end_time"]) for r in whoop_rows]

    avg_bed = _avg_nonull(bed_hours)
    # Normalise back to 0–24 range for display
    if avg_bed is not None and avg_bed >= 24.0:
        avg_bed -= 24.0

    avg_wake = _avg_nonull(wake_hours)
    std_bed = _std_nonull(bed_hours)
    std_wake = _std_nonull(wake_hours)

    # Sleep debt trend from unified_sleep (7 extra days for rolling avg)
    history_start = _add_days(start_str, -6)
    sleep_all = _fetch_unified_sleep(engine, history_start, end_str)

    # Compute daily debt in chronological order for linear regression
    debt_series: list[float] = []
    current = start
    while current <= end:
        d = current.isoformat()
        last_7 = [_net_sleep(sleep_all.get(_add_days(d, -i), {})) for i in range(7)]
        avg_sleep = _avg_nonull(last_7)
        if avg_sleep is not None:
            debt_series.append(avg_sleep - DEFAULT_TARGET_SLEEP_MINUTES)
        current += timedelta(days=1)

    slope = _linear_slope(debt_series)
    # debt = avg_sleep − target; slope < 0 means debt getting more negative (worsening).
    if slope is None:
        trend = "unknown"
    elif abs(slope) < _STABLE_SLOPE_THRESHOLD:
        trend = "stable"
    elif slope < 0:
        trend = "worsening"
    else:
        trend = "improving"

    # Average sleep for the period: net (awake excluded) and time-in-bed (awake included)
    sleep_range = _fetch_unified_sleep(engine, start_str, end_str)
    avg_total_sleep = _avg_nonull([_net_sleep(r) for r in sleep_range.values()])
    avg_time_in_bed = _avg_nonull([r.get("total_sleep_minutes") for r in sleep_range.values()])

    return {
        "insufficient_data": False,
        "sample_size": n,
        "avg_bedtime_hour": round(avg_bed, 3) if avg_bed is not None else None,
        "bedtime_std_hours": round(std_bed, 3) if std_bed is not None else None,
        "avg_wake_hour": round(avg_wake, 3) if avg_wake is not None else None,
        "wake_time_std_hours": round(std_wake, 3) if std_wake is not None else None,
        "avg_total_sleep_minutes": round(avg_total_sleep, 1)
        if avg_total_sleep is not None
        else None,
        "avg_time_in_bed_minutes": round(avg_time_in_bed, 1)
        if avg_time_in_bed is not None
        else None,
        "sleep_debt_trend": trend,
        "sleep_debt_trend_slope_min_per_day": round(slope, 3) if slope is not None else None,
        "message": None,
    }
