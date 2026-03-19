"""Trends analytics module.

Provides rolling averages, anomaly detection, trend direction, and weekly
summaries for key metrics sourced from ``unified_daily``, ``unified_sleep``,
and ``unified_workouts``.

Public API
----------
get_metric_series(engine, metric, start_date, end_date) -> list[DailyPoint]
get_metric_trend(engine, metric_name, start_date, end_date) -> MetricTrend
detect_anomalies(values, dates, window=7, threshold=2.0) -> list[dict]
calculate_trend_direction(rolling_avg, window=7) -> str
get_weekly_summary(engine, date) -> dict
get_weekly_rollup(engine, metric, start_date, end_date) -> list[PeriodRollup]
get_monthly_rollup(engine, metric, start_date, end_date) -> list[PeriodRollup]

Supported metrics
-----------------
Standard (maps to a single table column):
  "recovery" / "recovery_score"          — unified_daily.whoop_recovery_score
  "hrv"                                  — unified_daily.whoop_hrv_rmssd
  "resting_hr"                           — unified_daily.whoop_rhr
  "body_battery"                         — unified_daily.garmin_body_battery_high
  "stress"                               — unified_daily.garmin_avg_stress
  "steps"                                — unified_daily.garmin_total_steps
  "strain" / "daily_strain"              — unified_daily.whoop_strain
  "sleep_duration" / "total_sleep"       — unified_sleep.total_sleep_minutes
  "deep_sleep"                           — unified_sleep.deep_sleep_minutes
  "rem_sleep"                            — unified_sleep.rem_sleep_minutes
  "sleep_performance"                    — unified_sleep.whoop_performance

Computed (get_metric_trend only):
  "readiness"     — computed via get_readiness_history()
  "training_load" — SUM(whoop_strain) per day from unified_workouts
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------

_METRIC_SOURCE: dict[str, tuple[str, str]] = {
    # Legacy names — kept for backward compatibility
    "recovery": ("unified_daily", "whoop_recovery_score"),
    "hrv": ("unified_daily", "whoop_hrv_rmssd"),
    "resting_hr": ("unified_daily", "whoop_rhr"),
    "body_battery": ("unified_daily", "garmin_body_battery_high"),
    "stress": ("unified_daily", "garmin_avg_stress"),
    "steps": ("unified_daily", "garmin_total_steps"),
    "daily_strain": ("unified_daily", "whoop_strain"),
    "total_sleep": ("unified_sleep", "total_sleep_minutes"),
    "deep_sleep": ("unified_sleep", "deep_sleep_minutes"),
    "rem_sleep": ("unified_sleep", "rem_sleep_minutes"),
    "sleep_performance": ("unified_sleep", "whoop_performance"),
    # Spec-required names
    "recovery_score": ("unified_daily", "whoop_recovery_score"),
    "strain": ("unified_daily", "whoop_strain"),
    "sleep_duration": ("unified_sleep", "total_sleep_minutes"),
}

# Metrics requiring custom fetch logic (not a simple table.column lookup)
_SPECIAL_METRICS: frozenset[str] = frozenset({"readiness", "training_load"})

_ROLLING_SHORT: int = 7
_ROLLING_LONG: int = 28
_MIN_ANOMALY_SAMPLE: int = 7
_DEFAULT_Z_THRESHOLD: float = 2.0
# Relative slope threshold for trend direction: 0.2% per day vs mean value
_TREND_DIRECTION_THRESHOLD: float = 0.002

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DailyPoint:
    """A single calendar day's metric value with rolling context.

    Rolling averages span the N calendar days ending on (and including) this
    date, averaging only non-None values.  ``rolling_28d_std`` is the sample
    standard deviation of the same 28-day window.  ``z_score`` requires at
    least ``_MIN_ANOMALY_SAMPLE`` non-None values in that window; it is None
    when that condition is not met or when ``value`` is None.

    Days where the metric was not recorded still appear in the output (with
    ``value=None``) so that callers can render continuous rolling-average
    lines over sparse data.
    """

    date: str  # YYYY-MM-DD
    value: float | None
    rolling_7d: float | None
    rolling_28d: float | None
    rolling_28d_std: float | None
    z_score: float | None


@dataclass
class AnomalyPoint:
    """A day whose value deviated significantly from its 28-day rolling mean.

    ``z_score`` is positive when the value was above the baseline ("high")
    and negative when below ("low").
    """

    date: str
    value: float
    z_score: float
    direction: str  # "high" | "low"
    rolling_mean: float
    rolling_std: float


@dataclass
class PeriodRollup:
    """Aggregate stats for one calendar week or month.

    ``period`` uses ISO week notation ("2025-W01") for weekly rollups and
    "YYYY-MM" for monthly rollups.  ``period_start`` is the ISO date of the
    first day of the period (Monday for weeks, the 1st for months).

    ``count`` is the number of non-None values that contributed to the
    aggregates.  All numeric fields are None when ``count`` is 0.
    """

    period: str  # "2025-W01" or "2025-01"
    period_start: str  # YYYY-MM-DD
    count: int
    avg: float | None
    min: float | None
    max: float | None
    std: float | None


@dataclass
class MetricTrend:
    """Combined trend result for a metric over a date range.

    Attributes:
        metric_name: The metric that was queried.
        dates: ISO date strings, one per calendar day in [start_date, end_date].
        values: Raw daily values aligned with ``dates`` (None for missing days).
        rolling_avg_7d: 7-day trailing rolling average aligned with ``dates``.
        rolling_avg_30d: 30-day trailing rolling average aligned with ``dates``.
        rolling_std_7d: 7-day trailing rolling std dev aligned with ``dates``.
        anomalies: Days in the range that deviated ≥ 2σ from the 7-day prior
            rolling mean.  Each entry: {date, value, direction, severity}.
        trend_direction: "improving", "declining", or "stable" based on the
            OLS slope of ``rolling_avg_7d`` over the last 7 values.
    """

    metric_name: str
    dates: list[str]
    values: list[float | None]
    rolling_avg_7d: list[float | None]
    rolling_avg_30d: list[float | None]
    rolling_std_7d: list[float | None]
    anomalies: list[dict] = field(default_factory=list)
    trend_direction: str = "stable"


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _avg_nonull(values: list[float | None]) -> float | None:
    """Mean of non-None values, or None if there are none."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _std_nonull(values: list[float | None]) -> float | None:
    """Sample std dev of non-None values; None if fewer than 2 values."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return None
    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / (len(valid) - 1)
    return variance**0.5


def _z_score(value: float | None, window: list[float | None]) -> float | None:
    """Z-score of ``value`` relative to the non-None values in ``window``.

    Returns None when ``value`` is None, when fewer than
    ``_MIN_ANOMALY_SAMPLE`` non-None values exist in the window, or when
    the sample standard deviation is zero (all values identical).
    """
    if value is None:
        return None
    valid = [v for v in window if v is not None]
    if len(valid) < _MIN_ANOMALY_SAMPLE:
        return None
    mean = sum(valid) / len(valid)
    std = _std_nonull(window)
    if std is None or std == 0.0:
        return 0.0
    return (value - mean) / std


def _week_key(d: date) -> tuple[str, str]:
    """Return (ISO-week label, Monday ISO date) for ``d``."""
    iso = d.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    monday = d - timedelta(days=d.weekday())
    return label, monday.isoformat()


def _month_key(d: date) -> tuple[str, str]:
    """Return (YYYY-MM label, first-of-month ISO date) for ``d``."""
    return d.strftime("%Y-%m"), date(d.year, d.month, 1).isoformat()


def _rolling_avg(values: list[float | None], window: int) -> list[float | None]:
    """Trailing rolling average over ``window`` days including the current day."""
    return [_avg_nonull(values[max(0, i - window + 1) : i + 1]) for i in range(len(values))]


def _rolling_std(values: list[float | None], window: int) -> list[float | None]:
    """Trailing rolling std dev over ``window`` days including the current day."""
    return [_std_nonull(values[max(0, i - window + 1) : i + 1]) for i in range(len(values))]


def _date_range(start: date, end: date) -> list[date]:
    """All calendar dates from ``start`` through ``end`` inclusive."""
    dates: list[date] = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _metric_source(metric: str) -> tuple[str, str]:
    """Resolve metric name → (table, column); raise ValueError if unknown."""
    if metric not in _METRIC_SOURCE:
        raise ValueError(f"Unknown metric {metric!r}. Valid metrics: {sorted(_METRIC_SOURCE)}")
    return _METRIC_SOURCE[metric]


def _fetch_raw(
    engine: Engine,
    table: str,
    column: str,
    start_iso: str,
    end_iso: str,
    user_id: str | None = None,
) -> list[tuple[str, float | None]]:
    """Fetch (date, value) pairs from ``table`` ordered by date."""
    if user_id is not None:
        uid_clause = "AND user_id = :uid"
        params: dict = {"s": start_iso, "e": end_iso, "uid": user_id}
    else:
        uid_clause = "AND user_id IS NULL"
        params = {"s": start_iso, "e": end_iso}
    with engine.connect() as conn:
        rows = conn.execute(
            text(  # noqa: S608
                f"SELECT date, {column} FROM {table}"
                f" WHERE date >= :s AND date <= :e {uid_clause} ORDER BY date"
            ),
            params,
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _calendar_fill(
    raw: list[tuple[str, float | None]],
    start: date,
    end: date,
) -> list[tuple[str, float | None]]:
    """Expand sparse ``raw`` to one entry per calendar day, None for gaps."""
    by_date = dict(raw)
    result: list[tuple[str, float | None]] = []
    d = start
    while d <= end:
        iso = d.isoformat()
        result.append((iso, by_date.get(iso)))
        d += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Special metric fetchers (used by get_metric_trend)
# ---------------------------------------------------------------------------


def _fetch_readiness_values(
    engine: Engine,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[tuple[str, float | None]]:
    """Return per-day readiness scores via get_readiness_history."""
    from src.analytics.readiness_score import get_readiness_history  # lazy import

    history = get_readiness_history(start_date, end_date, engine, user_id=user_id)
    by_date = {r["date"]: r["score"] for r in history if r.get("score") is not None}
    return [(d.isoformat(), by_date.get(d.isoformat())) for d in _date_range(start_date, end_date)]


def _fetch_training_load_values(
    engine: Engine,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[tuple[str, float | None]]:
    """Return per-day total whoop_strain summed from unified_workouts."""
    if user_id is not None:
        uid_clause = "AND user_id = :uid"
        params: dict = {"s": start_date.isoformat(), "e": end_date.isoformat(), "uid": user_id}
    else:
        uid_clause = "AND user_id IS NULL"
        params = {"s": start_date.isoformat(), "e": end_date.isoformat()}
    with engine.connect() as conn:
        rows = conn.execute(
            text(  # noqa: S608
                "SELECT date, SUM(whoop_strain) FROM unified_workouts"
                f" WHERE date >= :s AND date <= :e AND whoop_strain IS NOT NULL {uid_clause}"
                " GROUP BY date ORDER BY date"
            ),
            params,
        ).fetchall()
    by_date = {r[0]: float(r[1]) for r in rows}
    return [(d.isoformat(), by_date.get(d.isoformat())) for d in _date_range(start_date, end_date)]


def _fetch_metric_calendar(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[tuple[str, float | None]]:
    """Return (date, value) pairs for every calendar day in [start_date, end_date]."""
    if metric == "readiness":
        return _fetch_readiness_values(engine, start_date, end_date, user_id)
    if metric == "training_load":
        return _fetch_training_load_values(engine, start_date, end_date, user_id)
    table, column = _metric_source(metric)
    raw = _fetch_raw(engine, table, column, start_date.isoformat(), end_date.isoformat(), user_id)
    return _calendar_fill(raw, start_date, end_date)


def _get_notable_anomalies(
    engine: Engine,
    fetch_start: date,
    fetch_end: date,
    current_week_start: date,
    user_id: str | None = None,
) -> list[dict]:
    """Detect anomalies in key metrics over a 14-day window; return only
    those whose date falls within the current week."""
    _KEY_METRICS = ("recovery_score", "hrv", "resting_hr", "body_battery")
    current_week_start_iso = current_week_start.isoformat()
    notable: list[dict] = []
    for metric in _KEY_METRICS:
        try:
            calendar = _fetch_metric_calendar(engine, metric, fetch_start, fetch_end, user_id)
            values = [v for _, v in calendar]
            dates = [d for d, _ in calendar]
            for a in detect_anomalies(values, dates):
                if a["date"] >= current_week_start_iso:
                    notable.append({"metric": metric, **a})
        except Exception:  # noqa: BLE001
            continue
    return notable


# ---------------------------------------------------------------------------
# Public API — existing
# ---------------------------------------------------------------------------


def get_metric_series(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[DailyPoint]:
    """Return one DailyPoint per calendar day in [start_date, end_date].

    Each point carries the raw value plus 7-day and 28-day trailing rolling
    averages (over calendar days, skipping days with no data), a 28-day
    sample std dev, and a z-score relative to that window.

    Days where the metric was not recorded still appear with ``value=None``
    so that callers can draw a continuous rolling-average line over gaps.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        metric: One of the supported metric names (see module docstring).
        start_date: First date in the output (inclusive).
        end_date: Last date in the output (inclusive).

    Returns:
        List of DailyPoint sorted ascending by date.

    Raises:
        ValueError: If ``metric`` is not recognised.
    """
    table, column = _metric_source(metric)
    fetch_start = start_date - timedelta(days=_ROLLING_LONG - 1)
    raw = _fetch_raw(engine, table, column, fetch_start.isoformat(), end_date.isoformat(), user_id)
    calendar = _calendar_fill(raw, fetch_start, end_date)

    start_iso = start_date.isoformat()
    results: list[DailyPoint] = []

    for i, (d, value) in enumerate(calendar):
        if d < start_iso:
            continue
        short_win = [calendar[j][1] for j in range(max(0, i - _ROLLING_SHORT + 1), i + 1)]
        long_win = [calendar[j][1] for j in range(max(0, i - _ROLLING_LONG + 1), i + 1)]
        results.append(
            DailyPoint(
                date=d,
                value=value,
                rolling_7d=_avg_nonull(short_win),
                rolling_28d=_avg_nonull(long_win),
                rolling_28d_std=_std_nonull(long_win),
                z_score=_z_score(value, long_win),
            )
        )

    return results


def _detect_anomalies_engine(
    engine: Engine,
    metric: str,
    days: int = 30,
    end_date: date | None = None,
    z_threshold: float = _DEFAULT_Z_THRESHOLD,
) -> list[AnomalyPoint]:
    """Engine-based anomaly detection using the 28-day z-score window from
    get_metric_series.  Returns AnomalyPoint instances.

    This is an internal helper; callers outside this module should use
    get_metric_trend (which uses the pure detect_anomalies).
    """
    if end_date is None:
        end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    series = get_metric_series(engine, metric, start_date, end_date)

    return [
        AnomalyPoint(
            date=pt.date,
            value=pt.value,  # type: ignore[arg-type]
            z_score=pt.z_score,  # type: ignore[arg-type]
            direction="high" if pt.z_score > 0 else "low",  # type: ignore[operator]
            rolling_mean=pt.rolling_28d,  # type: ignore[arg-type]
            rolling_std=pt.rolling_28d_std,  # type: ignore[arg-type]
        )
        for pt in series
        if pt.value is not None and pt.z_score is not None and abs(pt.z_score) >= z_threshold
    ]


def get_weekly_rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[PeriodRollup]:
    """Aggregate ``metric`` by ISO calendar week for [start_date, end_date].

    Weeks with no non-None data produce no entry.  Weeks that straddle
    ``start_date`` or ``end_date`` include only the days within range.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        metric: One of the supported metric names.
        start_date: First date to include (inclusive).
        end_date: Last date to include (inclusive).

    Returns:
        List of PeriodRollup sorted by ISO week label (chronological order).
    """
    return _rollup(engine, metric, start_date, end_date, _week_key, user_id)


def get_monthly_rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> list[PeriodRollup]:
    """Aggregate ``metric`` by calendar month for [start_date, end_date].

    Months with no non-None data produce no entry.  Partial months at the
    range boundaries include only the days within range.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        metric: One of the supported metric names.
        start_date: First date to include (inclusive).
        end_date: Last date to include (inclusive).

    Returns:
        List of PeriodRollup sorted by month label (chronological order).
    """
    return _rollup(engine, metric, start_date, end_date, _month_key, user_id)


def _rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    key_fn: Callable[[date], tuple[str, str]],
    user_id: str | None = None,
) -> list[PeriodRollup]:
    """Shared implementation for weekly and monthly rollups."""
    table, column = _metric_source(metric)
    raw = _fetch_raw(engine, table, column, start_date.isoformat(), end_date.isoformat(), user_id)

    groups: dict[str, list[float]] = {}
    period_starts: dict[str, str] = {}

    for date_str, value in raw:
        if value is None:
            continue
        d = date.fromisoformat(date_str)
        label, ps = key_fn(d)
        groups.setdefault(label, []).append(float(value))
        period_starts[label] = ps

    return [
        PeriodRollup(
            period=label,
            period_start=period_starts[label],
            count=len(vals),
            avg=sum(vals) / len(vals),
            min=min(vals),
            max=max(vals),
            std=_std_nonull(vals),
        )
        for label in sorted(groups)
        for vals in [groups[label]]
    ]


# ---------------------------------------------------------------------------
# Public API — new
# ---------------------------------------------------------------------------


def detect_anomalies(
    values: list[float | None],
    dates: list[str],
    window: int = 7,
    threshold: float = 2.0,
) -> list[dict]:
    """Flag days whose value deviates ≥ ``threshold`` std devs from the
    rolling mean of the preceding ``window`` non-None values.

    Requires at least ``window`` non-None *prior* values before a day can
    be flagged, so the first ``window`` calendar positions are never flagged
    regardless of their value.

    Args:
        values: Daily metric values (None for missing days), aligned with dates.
        dates: ISO date strings aligned with ``values``.
        window: Minimum prior non-None values required; also the rolling
            window size (default 7).
        threshold: Minimum |severity| to flag a day (default 2.0).

    Returns:
        List of dicts sorted ascending by date:
        {date, value, direction ("high"/"low"), severity (z-score)}.
    """
    result: list[dict] = []
    for i, (d, v) in enumerate(zip(dates, values)):
        if v is None:
            continue
        prior = [values[j] for j in range(max(0, i - window), i) if values[j] is not None]
        if len(prior) < window:
            continue
        mean = sum(prior) / len(prior)
        variance = sum((x - mean) ** 2 for x in prior) / (len(prior) - 1)
        std = variance**0.5
        if std == 0:
            continue
        severity = (v - mean) / std
        if abs(severity) >= threshold:
            result.append(
                {
                    "date": d,
                    "value": v,
                    "direction": "high" if severity > 0 else "low",
                    "severity": severity,
                }
            )
    if result:
        logger.debug("detect_anomalies: %d anomalies found in %d values", len(result), len(values))
    return result


def calculate_trend_direction(
    rolling_avg: list[float | None],
    window: int = 7,
) -> str:
    """Determine trend direction from the OLS slope of the last ``window``
    rolling-average values.

    The slope is normalised by the absolute mean of the window to produce a
    scale-independent relative rate (fraction per day):

    - relative slope > +0.2 % per day → "improving"
    - relative slope < −0.2 % per day → "declining"
    - otherwise                        → "stable"

    Returns "stable" when fewer than 2 non-None values are available.

    Args:
        rolling_avg: Rolling average series (parallel to a dates list).
        window: Number of trailing values to use for the regression (default 7).

    Returns:
        "improving", "declining", or "stable".
    """
    recent = [v for v in rolling_avg[-window:] if v is not None]
    if len(recent) < 2:
        return "stable"
    n = len(recent)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(recent) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, recent))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0 or y_mean == 0:
        return "stable"
    relative_slope = (numerator / denominator) / abs(y_mean)
    if relative_slope > _TREND_DIRECTION_THRESHOLD:
        return "improving"
    if relative_slope < -_TREND_DIRECTION_THRESHOLD:
        return "declining"
    return "stable"


def get_metric_trend(
    engine: Engine,
    metric_name: str,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> MetricTrend:
    """Compute rolling averages, anomalies, and trend direction for a metric.

    Fetches an extra 29-day lookback window before ``start_date`` so that
    rolling averages are seeded from real data rather than a short partial
    window.

    Supported metrics: all names in ``_METRIC_SOURCE`` plus "readiness" and
    "training_load" (see module docstring for the full list).

    Args:
        engine: SQLAlchemy engine connected to the fitness database.
        metric_name: Metric to compute (see module docstring).
        start_date: First date in the output (inclusive).
        end_date: Last date in the output (inclusive).

    Returns:
        MetricTrend with dates/values aligned to [start_date, end_date] and
        rolling averages seeded from the prior 29 days.

    Raises:
        ValueError: If ``metric_name`` is not recognised.
    """
    if metric_name not in _METRIC_SOURCE and metric_name not in _SPECIAL_METRICS:
        raise ValueError(
            f"Unknown metric {metric_name!r}. "
            f"Valid metrics: {sorted(_METRIC_SOURCE) + sorted(_SPECIAL_METRICS)}"
        )

    lookback_start = start_date - timedelta(days=29)
    full_calendar = _fetch_metric_calendar(engine, metric_name, lookback_start, end_date, user_id)

    all_dates = [d for d, _ in full_calendar]
    all_values = [v for _, v in full_calendar]
    start_iso = start_date.isoformat()
    start_idx = next(i for i, d in enumerate(all_dates) if d >= start_iso)

    rolling_7d_full = _rolling_avg(all_values, _ROLLING_SHORT)
    rolling_30d_full = _rolling_avg(all_values, 30)
    rolling_std_7d_full = _rolling_std(all_values, _ROLLING_SHORT)

    dates = all_dates[start_idx:]
    values = all_values[start_idx:]
    rolling_7d = rolling_7d_full[start_idx:]
    rolling_30d = rolling_30d_full[start_idx:]
    rolling_std_7d = rolling_std_7d_full[start_idx:]

    anomalies = detect_anomalies(values, dates)
    trend_direction = calculate_trend_direction(rolling_7d)

    return MetricTrend(
        metric_name=metric_name,
        dates=dates,
        values=values,
        rolling_avg_7d=rolling_7d,
        rolling_avg_30d=rolling_30d,
        rolling_std_7d=rolling_std_7d,
        anomalies=anomalies,
        trend_direction=trend_direction,
    )


# ---------------------------------------------------------------------------
# Enriched anomaly constants and dataclass
# ---------------------------------------------------------------------------

_ENRICHED_ANOMALY_METRICS: list[str] = [
    "recovery",
    "hrv",
    "resting_hr",
    "strain",
    "body_battery",
    "sleep_duration",
    "deep_sleep",
]

_ENRICHED_METRIC_LABELS: dict[str, str] = {
    "recovery": "Recovery Score",
    "hrv": "HRV",
    "resting_hr": "Resting HR",
    "strain": "Strain",
    "body_battery": "Body Battery",
    "sleep_duration": "Sleep Duration",
    "deep_sleep": "Deep Sleep",
}


@dataclass
class EnrichedAnomaly:
    """An anomaly with 48-hour surrounding context and a plain-language explanation.

    Attributes:
        date: ISO date string (YYYY-MM-DD) of the anomalous day.
        metric: Internal metric key (e.g. "hrv").
        metric_label: Human-readable label (e.g. "HRV").
        value: Raw metric value on the anomalous day.
        direction: "high" or "low" relative to the rolling mean.
        severity: Absolute z-score (always positive).
        context: Dict with keys:
            training_48h — {total_strain, workout_count} for the 2 days prior.
            sleep_prior_night — {duration_hours, quality_pct, deep_pct}.
            recovery_trend — "improving" | "declining" | "stable" over 7d.
            co_anomalies — list of metric labels also flagged on the same day.
        explanation: One-sentence natural-language summary.
    """

    date: str
    metric: str
    metric_label: str
    value: float
    direction: str  # "high" | "low"
    severity: float  # abs z-score
    context: dict
    explanation: str


# ---------------------------------------------------------------------------
# Enriched anomaly helpers (private)
# ---------------------------------------------------------------------------


def _enriched_severity_label(z_abs: float) -> str:
    """Human-readable severity label from an absolute z-score."""
    if z_abs >= 3.5:
        return "significant"
    if z_abs >= 2.5:
        return "moderate"
    return "mild"


def _fmt_anomaly_value(metric: str, value: float) -> str:
    """Format a raw metric value for use in an explanation string."""
    if metric == "hrv":
        return f"{value:.0f}ms"
    if metric in ("recovery", "sleep_performance"):
        return f"{value:.0f}%"
    if metric == "resting_hr":
        return f"{value:.0f}bpm"
    if metric == "sleep_duration":
        return f"{value / 60.0:.1f}h"
    if metric == "deep_sleep":
        return f"{value:.0f}min"
    return f"{value:.1f}"


def _fetch_training_ctx(engine: Engine, user_id: str | None, anomaly_date: date) -> dict:
    """Return total strain and workout count in the 2 days prior to anomaly_date."""
    start_iso = (anomaly_date - timedelta(days=2)).isoformat()
    end_iso = (anomaly_date - timedelta(days=1)).isoformat()
    if user_id is not None:
        uid_clause = "AND user_id = :uid"
        params: dict = {"s": start_iso, "e": end_iso, "uid": user_id}
    else:
        uid_clause = "AND user_id IS NULL"
        params = {"s": start_iso, "e": end_iso}
    with engine.connect() as conn:
        row = conn.execute(
            text(  # noqa: S608
                "SELECT COALESCE(SUM(whoop_strain), 0), COUNT(*)"
                " FROM unified_workouts"
                f" WHERE date >= :s AND date <= :e AND whoop_strain IS NOT NULL {uid_clause}"
            ),
            params,
        ).fetchone()
    total_strain = float(row[0]) if row[0] else None
    workout_count = int(row[1]) if row[1] else 0
    return {"total_strain": total_strain, "workout_count": workout_count}


def _fetch_sleep_ctx(engine: Engine, user_id: str | None, anomaly_date: date) -> dict:
    """Return sleep duration, quality, and deep-sleep % for the night before anomaly_date."""
    prev_iso = (anomaly_date - timedelta(days=1)).isoformat()
    if user_id is not None:
        uid_clause = "AND user_id = :uid"
        params: dict = {"d": prev_iso, "uid": user_id}
    else:
        uid_clause = "AND user_id IS NULL"
        params = {"d": prev_iso}
    with engine.connect() as conn:
        row = conn.execute(
            text(  # noqa: S608
                "SELECT total_sleep_minutes, whoop_performance, deep_sleep_minutes"
                f" FROM unified_sleep WHERE date = :d {uid_clause} LIMIT 1"
            ),
            params,
        ).fetchone()
    if row is None:
        return {"duration_hours": None, "quality_pct": None, "deep_pct": None}
    total_min = row[0]
    quality = row[1]
    deep_min = row[2]
    duration_hours = round(total_min / 60.0, 1) if total_min else None
    deep_pct = (
        round(deep_min / total_min * 100.0, 1)
        if (deep_min and total_min and total_min > 0)
        else None
    )
    return {
        "duration_hours": duration_hours,
        "quality_pct": float(quality) if quality is not None else None,
        "deep_pct": deep_pct,
    }


def _fetch_recovery_ctx(engine: Engine, user_id: str | None, anomaly_date: date) -> str:
    """Return recovery trend direction over the 7 days ending on anomaly_date."""
    start = anomaly_date - timedelta(days=6)
    raw = _fetch_raw(
        engine,
        "unified_daily",
        "whoop_recovery_score",
        start.isoformat(),
        anomaly_date.isoformat(),
        user_id,
    )
    values = [float(v) for _, v in raw if v is not None]
    rolling = _rolling_avg(values, len(values))
    return calculate_trend_direction(rolling)


def _build_enriched_explanation(
    metric: str,
    metric_label: str,
    value: float,
    direction: str,
    severity: float,
    context: dict,
) -> str:
    """Build a natural-language explanation for an enriched anomaly."""
    sev_label = _enriched_severity_label(severity)
    verb = (
        "elevated"
        if (metric == "resting_hr" and direction == "high")
        else ("spiked" if direction == "high" else "dropped")
    )
    fmt_val = _fmt_anomaly_value(metric, value)
    base = f"{metric_label} {verb} to {fmt_val} ({sev_label})"

    training = context.get("training_48h", {})
    sleep = context.get("sleep_prior_night", {})
    co_anomalies = context.get("co_anomalies", [])
    recovery_trend = context.get("recovery_trend", "stable")

    strain = training.get("total_strain")
    workout_count = training.get("workout_count", 0)

    # High training load explains fatigue signals (low hrv/recovery/bb, high resting_hr)
    fatigue_signal = (metric in ("hrv", "recovery", "body_battery") and direction == "low") or (
        metric == "resting_hr" and direction == "high"
    )
    if fatigue_signal and strain and strain > 0 and workout_count > 0:
        sessions = f"{workout_count} session{'s' if workout_count != 1 else ''}"
        return f"{base} — you logged {sessions} in the prior 48h totaling {strain:.1f} strain"

    # Good sleep explains positive recovery/hrv spikes
    good_signal = metric in ("recovery", "hrv") and direction == "high"
    dur = sleep.get("duration_hours")
    if good_signal and dur is not None:
        deep_pct = sleep.get("deep_pct")
        if deep_pct is not None:
            return (
                f"{base} — follows {dur:.1f}h of sleep with {deep_pct:.0f}% deep sleep proportion"
            )
        return f"{base} — follows {dur:.1f}h of sleep the night before"

    # Co-occurring anomalies on the same day
    if co_anomalies:
        co_str = " and ".join(co_anomalies[:2])
        return f"{base} — {co_str} was also flagged on the same day"

    # Recovery trend as fallback context
    if recovery_trend != "stable":
        return f"{base} — recovery has been {recovery_trend} over the past week"

    return base


# ---------------------------------------------------------------------------
# Enriched anomaly public API
# ---------------------------------------------------------------------------


def enrich_anomaly(
    engine: Engine,
    user_id: str | None,
    metric: str,
    anomaly: dict,
    co_anomalies_by_date: dict[str, list[str]] | None = None,
) -> EnrichedAnomaly:
    """Enrich a single anomaly dict with 48-hour surrounding context.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID (None → match rows where user_id IS NULL).
        metric: Internal metric key (e.g. "hrv").
        anomaly: Dict with keys {date, value, direction, severity} as returned
            by detect_anomalies().
        co_anomalies_by_date: Optional pre-built map of date → list of metric
            labels flagged on that day.  If provided, the co-anomaly lookup uses
            this cache rather than re-computing.

    Returns:
        EnrichedAnomaly with context and explanation populated.
    """
    anomaly_date = date.fromisoformat(anomaly["date"])
    metric_label = _ENRICHED_METRIC_LABELS.get(metric, metric)
    severity = abs(anomaly["severity"])

    training_ctx = _fetch_training_ctx(engine, user_id, anomaly_date)
    sleep_ctx = _fetch_sleep_ctx(engine, user_id, anomaly_date)
    recovery_trend = _fetch_recovery_ctx(engine, user_id, anomaly_date)

    # Co-anomalies: other metric labels flagged on the same date (excluding self)
    same_day = (co_anomalies_by_date or {}).get(anomaly["date"], [])
    co_anomalies = [lbl for lbl in same_day if lbl != metric_label]

    context = {
        "training_48h": training_ctx,
        "sleep_prior_night": sleep_ctx,
        "recovery_trend": recovery_trend,
        "co_anomalies": co_anomalies,
    }
    explanation = _build_enriched_explanation(
        metric, metric_label, anomaly["value"], anomaly["direction"], severity, context
    )
    return EnrichedAnomaly(
        date=anomaly["date"],
        metric=metric,
        metric_label=metric_label,
        value=anomaly["value"],
        direction=anomaly["direction"],
        severity=round(severity, 2),
        context=context,
        explanation=explanation,
    )


def get_enriched_anomalies(
    engine: Engine,
    user_id: str | None,
    start_date: date,
    end_date: date,
    limit: int = 20,
) -> list[EnrichedAnomaly]:
    """Detect anomalies across all tracked metrics and enrich with 48h context.

    Algorithm:
    1. Run anomaly detection for each metric in ``_ENRICHED_ANOMALY_METRICS``
       over [start_date, end_date].
    2. Build a co-anomaly map (date → list of metric labels flagged that day).
    3. Enrich each anomaly with training/sleep/recovery context.
    4. Sort by date descending (most recent first), then by severity descending
       within the same date.
    5. Return the top ``limit`` enriched anomalies.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID.
        start_date: First date to search for anomalies (inclusive).
        end_date: Last date to search for anomalies (inclusive).
        limit: Maximum number of enriched anomalies to return (default 20).

    Returns:
        List of EnrichedAnomaly sorted most-recent-first.  Empty when there
        is no data or no anomalies in the date range.
    """
    # 1. Collect raw anomalies per metric
    raw_pairs: list[tuple[str, dict]] = []
    for metric in _ENRICHED_ANOMALY_METRICS:
        try:
            trend = get_metric_trend(engine, metric, start_date, end_date, user_id)
            for a in trend.anomalies:
                raw_pairs.append((metric, a))
        except Exception:  # noqa: BLE001
            logger.debug("get_enriched_anomalies: skipping metric %r", metric)
            continue

    if not raw_pairs:
        return []

    # 2. Build co-anomaly map: date → [metric_label, ...]
    co_map: dict[str, list[str]] = {}
    for metric, a in raw_pairs:
        lbl = _ENRICHED_METRIC_LABELS.get(metric, metric)
        co_map.setdefault(a["date"], []).append(lbl)

    # 3. Enrich each anomaly
    enriched: list[EnrichedAnomaly] = [
        enrich_anomaly(engine, user_id, metric, a, co_map) for metric, a in raw_pairs
    ]

    # 4. Sort: date descending, severity descending within same date
    enriched.sort(key=lambda x: (x.date, x.severity), reverse=True)

    return enriched[:limit]


def get_weekly_summary(engine: Engine, end_date: date, user_id: str | None = None) -> dict:
    """Compute a 7-day wellness summary ending on ``end_date``.

    Queries unified_daily, unified_sleep, and unified_workouts for the
    current 7-day period and the preceding 7-day period, then computes
    per-metric percentage changes for week-over-week comparison.

    Args:
        engine: SQLAlchemy engine connected to the fitness database.
        end_date: Last date of the current 7-day period (inclusive).

    Returns:
        Dict with keys:
            period_start, period_end,
            avg_readiness, avg_recovery, avg_hrv, avg_rhr,
            total_strain, workout_count, total_training_minutes,
            avg_sleep_duration, avg_deep_sleep,
            notable_anomalies,
            comparison (dict of metric → % change vs previous week, or None).
    """
    start_date = end_date - timedelta(days=6)
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)

    if user_id is not None:
        _uid_clause = "AND user_id = :uid"
    else:
        _uid_clause = "AND user_id IS NULL"

    def _daily_stats(s: date, e: date) -> dict:
        p: dict = {"s": s.isoformat(), "e": e.isoformat()}
        if user_id is not None:
            p["uid"] = user_id
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT AVG(whoop_recovery_score), AVG(whoop_hrv_rmssd),"
                    "       AVG(whoop_rhr), SUM(whoop_strain)"
                    f" FROM unified_daily WHERE date >= :s AND date <= :e {_uid_clause}"
                ),
                p,
            ).fetchone()
        return {
            "avg_recovery": row[0],
            "avg_hrv": row[1],
            "avg_rhr": row[2],
            "total_strain": row[3],
        }

    def _sleep_stats(s: date, e: date) -> dict:
        p: dict = {"s": s.isoformat(), "e": e.isoformat()}
        if user_id is not None:
            p["uid"] = user_id
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT AVG(total_sleep_minutes - COALESCE(awake_minutes, 0)),"
                    "       AVG(deep_sleep_minutes)"
                    f" FROM unified_sleep WHERE date >= :s AND date <= :e {_uid_clause}"
                ),
                p,
            ).fetchone()
        return {
            "avg_sleep_duration": row[0],
            "avg_deep_sleep": row[1],
        }

    def _workout_stats(s: date, e: date) -> dict:
        p: dict = {"s": s.isoformat(), "e": e.isoformat()}
        if user_id is not None:
            p["uid"] = user_id
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*), SUM(duration_minutes)"
                    f" FROM unified_workouts WHERE date >= :s AND date <= :e {_uid_clause}"
                ),
                p,
            ).fetchone()
        return {
            "workout_count": row[0] or 0,
            "total_training_minutes": row[1],
        }

    def _avg_readiness(s: date, e: date) -> float | None:
        from src.analytics.readiness_score import get_readiness_history  # lazy import

        history = get_readiness_history(s, e, engine, user_id=user_id)
        scores = [r["score"] for r in history if r.get("score") is not None]
        return sum(scores) / len(scores) if scores else None

    def _pct_change(curr: float | None, prev: float | None) -> float | None:
        if curr is None or prev is None or prev == 0:
            return None
        return round((curr - prev) / abs(prev) * 100, 1)

    curr_daily = _daily_stats(start_date, end_date)
    curr_sleep = _sleep_stats(start_date, end_date)
    curr_workouts = _workout_stats(start_date, end_date)
    curr_readiness = _avg_readiness(start_date, end_date)

    prev_daily = _daily_stats(prev_start, prev_end)
    prev_sleep = _sleep_stats(prev_start, prev_end)
    prev_workouts = _workout_stats(prev_start, prev_end)
    prev_readiness = _avg_readiness(prev_start, prev_end)

    notable_anomalies = _get_notable_anomalies(engine, prev_start, end_date, start_date, user_id)

    comparison = {
        "avg_readiness": _pct_change(curr_readiness, prev_readiness),
        "avg_recovery": _pct_change(curr_daily["avg_recovery"], prev_daily["avg_recovery"]),
        "avg_hrv": _pct_change(curr_daily["avg_hrv"], prev_daily["avg_hrv"]),
        "avg_rhr": _pct_change(curr_daily["avg_rhr"], prev_daily["avg_rhr"]),
        "total_strain": _pct_change(curr_daily["total_strain"], prev_daily["total_strain"]),
        "workout_count": _pct_change(
            curr_workouts["workout_count"], prev_workouts["workout_count"]
        ),
        "total_training_minutes": _pct_change(
            curr_workouts["total_training_minutes"],
            prev_workouts["total_training_minutes"],
        ),
        "avg_sleep_duration": _pct_change(
            curr_sleep["avg_sleep_duration"], prev_sleep["avg_sleep_duration"]
        ),
        "avg_deep_sleep": _pct_change(curr_sleep["avg_deep_sleep"], prev_sleep["avg_deep_sleep"]),
    }

    return {
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "avg_readiness": curr_readiness,
        **curr_daily,
        **curr_sleep,
        **curr_workouts,
        "notable_anomalies": notable_anomalies,
        "comparison": comparison,
    }
