"""Trends analytics module.

Provides rolling averages, anomaly detection, and weekly/monthly rollups
for key metrics sourced from ``unified_daily`` and ``unified_sleep``.

Public API
----------
get_metric_series(engine, metric, start_date, end_date) -> list[DailyPoint]
detect_anomalies(engine, metric, days=30, end_date=None, z_threshold=2.0) -> list[AnomalyPoint]
get_weekly_rollup(engine, metric, start_date, end_date) -> list[PeriodRollup]
get_monthly_rollup(engine, metric, start_date, end_date) -> list[PeriodRollup]

Supported metrics
-----------------
"recovery"         — unified_daily.whoop_recovery_score
"hrv"              — unified_daily.whoop_hrv_rmssd
"resting_hr"       — unified_daily.whoop_rhr
"body_battery"     — unified_daily.garmin_body_battery_high
"stress"           — unified_daily.garmin_avg_stress
"steps"            — unified_daily.garmin_total_steps
"daily_strain"     — unified_daily.whoop_strain
"total_sleep"      — unified_sleep.total_sleep_minutes
"deep_sleep"       — unified_sleep.deep_sleep_minutes
"rem_sleep"        — unified_sleep.rem_sleep_minutes
"sleep_performance"— unified_sleep.whoop_performance
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine, text

# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------

_METRIC_SOURCE: dict[str, tuple[str, str]] = {
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
}

_ROLLING_SHORT: int = 7
_ROLLING_LONG: int = 28
_MIN_ANOMALY_SAMPLE: int = 7
_DEFAULT_Z_THRESHOLD: float = 2.0

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

    date: str                    # YYYY-MM-DD
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
    direction: str       # "high" | "low"
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

    period: str          # "2025-W01" or "2025-01"
    period_start: str    # YYYY-MM-DD
    count: int
    avg: float | None
    min: float | None
    max: float | None
    std: float | None


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
    return variance ** 0.5


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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _metric_source(metric: str) -> tuple[str, str]:
    """Resolve metric name → (table, column); raise ValueError if unknown."""
    if metric not in _METRIC_SOURCE:
        raise ValueError(
            f"Unknown metric {metric!r}. Valid metrics: {sorted(_METRIC_SOURCE)}"
        )
    return _METRIC_SOURCE[metric]


def _fetch_raw(
    engine: Engine, table: str, column: str, start_iso: str, end_iso: str
) -> list[tuple[str, float | None]]:
    """Fetch (date, value) pairs from ``table`` ordered by date."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(  # noqa: S608
                f"SELECT date, {column} FROM {table}"
                " WHERE date >= :s AND date <= :e ORDER BY date"
            ),
            {"s": start_iso, "e": end_iso},
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
# Public API
# ---------------------------------------------------------------------------


def get_metric_series(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
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
    raw = _fetch_raw(engine, table, column, fetch_start.isoformat(), end_date.isoformat())
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


def detect_anomalies(
    engine: Engine,
    metric: str,
    days: int = 30,
    end_date: date | None = None,
    z_threshold: float = _DEFAULT_Z_THRESHOLD,
) -> list[AnomalyPoint]:
    """Return days whose value deviated by ≥ ``z_threshold`` std devs from
    the 28-day rolling mean.

    Only days with a non-None value and at least ``_MIN_ANOMALY_SAMPLE``
    non-None values in the 28-day window are candidates.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        metric: One of the supported metric names.
        days: Number of calendar days to scan (default 30).
        end_date: Last date to scan; defaults to today.
        z_threshold: Minimum absolute z-score to flag (default 2.0).

    Returns:
        List of AnomalyPoint sorted ascending by date.
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
        if pt.value is not None
        and pt.z_score is not None
        and abs(pt.z_score) >= z_threshold
    ]


def get_weekly_rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
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
    return _rollup(engine, metric, start_date, end_date, _week_key)


def get_monthly_rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
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
    return _rollup(engine, metric, start_date, end_date, _month_key)


def _rollup(
    engine: Engine,
    metric: str,
    start_date: date,
    end_date: date,
    key_fn: Callable[[date], tuple[str, str]],
) -> list[PeriodRollup]:
    """Shared implementation for weekly and monthly rollups."""
    table, column = _metric_source(metric)
    raw = _fetch_raw(engine, table, column, start_date.isoformat(), end_date.isoformat())

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
