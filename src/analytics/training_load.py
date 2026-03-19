"""Training load analytics module — ACWR (Acute:Chronic Workload Ratio).

Compares recent training load (acute, 7 days) against longer-term baseline
(chronic, 28 days) to assess whether training volume is in a sustainable zone.

Public API
----------
get_training_load_ratio(engine, user_id, target_date=today) -> TrainingLoadResult
get_training_load_history(engine, user_id, start_date, end_date) -> list[dict]

ACWR zones
----------
< 0.6   detraining   — significantly less than usual
0.6–0.8 recovery     — lighter than usual, good for recovery weeks
0.8–1.3 sweet_spot   — sustainable and productive
1.3–1.5 overreaching — ramping up, monitor recovery closely
> 1.5   danger       — high injury risk, consider dialing back
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

_ACUTE_DAYS: int = 7
_CHRONIC_DAYS: int = 28
# Extra history needed: trend uses 7 daily ACWRs, each needs its own 28-day window.
# Earliest trend day = target - 6; its chronic window reaches target - 6 - 27 = target - 33.
_TREND_LOOKBACK: int = _CHRONIC_DAYS + _ACUTE_DAYS - 2  # 33

_TREND_DIRECTION_THRESHOLD: float = 0.002  # relative OLS slope per day

# ---------------------------------------------------------------------------
# Zone table: (lower_bound_inclusive, upper_bound_exclusive, name, description)
# Boundaries: 0.6, 0.8, 1.3, 1.5
# ---------------------------------------------------------------------------

_ZONE_TABLE: list[tuple[float, float, str, str]] = [
    (
        float("-inf"),
        0.6,
        "detraining",
        "You're doing significantly less than usual",
    ),
    (
        0.6,
        0.8,
        "recovery",
        "Training load is lighter than usual — good for recovery weeks",
    ),
    (
        0.8,
        1.3,
        "sweet_spot",
        "Your training load is sustainable and productive",
    ),
    (
        1.3,
        1.5,
        "overreaching",
        "You're ramping up — monitor recovery closely",
    ),
    (
        1.5,
        float("inf"),
        "danger",
        "High injury risk — consider dialing back",
    ),
]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WeeklyLoad:
    """Training load summary for one ISO calendar week."""

    week_start_date: str  # ISO date of the Monday that starts this week
    total_strain: float
    workout_count: int  # days with any whoop_strain > 0


@dataclass
class TrainingLoadResult:
    """ACWR result for a single target date.

    Attributes:
        acwr: Acute:Chronic ratio (7d avg / 28d avg). None when chronic avg is 0.
        acute_load: Sum of whoop_strain over the 7 days ending on target_date.
        chronic_load: Sum of whoop_strain over the 28 days ending on target_date.
        zone: Zone classification string (None when acwr is None).
        zone_description: Human-readable description of the zone.
        trend: Direction of ACWR over the last 7 days ("increasing" | "decreasing" | "stable").
        weekly_loads: Per-ISO-week summary for the 4 weeks in the chronic window.
        confidence_note: Set when fewer than 28 days of history are available.
    """

    acwr: float | None
    acute_load: float
    chronic_load: float
    zone: str | None
    zone_description: str | None
    trend: str
    weekly_loads: list[WeeklyLoad] = field(default_factory=list)
    confidence_note: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _classify_zone(acwr: float) -> tuple[str, str]:
    """Return (zone_name, zone_description) for an ACWR value."""
    for low, high, name, desc in _ZONE_TABLE:
        if low <= acwr < high:
            return name, desc
    # Unreachable: the table covers (−∞, +∞).
    return "danger", "High injury risk — consider dialing back"  # pragma: no cover


def _ols_slope(values: list[float]) -> float:
    """Return OLS slope (y per unit x) for evenly-spaced ``values``."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return numerator / denominator if denominator != 0 else 0.0


def _trend_direction(acwrs: list[float | None]) -> str:
    """Determine whether ACWR is "increasing", "decreasing", or "stable"
    based on the OLS slope of the non-None values."""
    valid = [v for v in acwrs if v is not None]
    if len(valid) < 2:
        return "stable"
    mean = sum(valid) / len(valid)
    if mean == 0:
        return "stable"
    slope = _ols_slope(valid)
    rel = slope / abs(mean)
    if rel > _TREND_DIRECTION_THRESHOLD:
        return "increasing"
    if rel < -_TREND_DIRECTION_THRESHOLD:
        return "decreasing"
    return "stable"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _fetch_daily_strain(
    engine: Engine,
    start_date: date,
    end_date: date,
    user_id: str | None = None,
) -> dict[str, float]:
    """Query unified_workouts for sum(whoop_strain) per day.

    Returns {date_iso: total_strain}. Days with no workouts are absent.
    """
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
    return {r[0]: float(r[1]) for r in rows}


def _fill_zeros(
    raw: dict[str, float],
    start: date,
    end: date,
) -> list[tuple[str, float]]:
    """Return (date_iso, strain) for every calendar day in [start, end].

    Days absent from ``raw`` are filled with 0.0 per spec — days with no
    workouts count as 0 strain, not as missing data.
    """
    result: list[tuple[str, float]] = []
    d = start
    while d <= end:
        iso = d.isoformat()
        result.append((iso, raw.get(iso, 0.0)))
        d += timedelta(days=1)
    return result


def _acwr_at(daily: list[tuple[str, float]], idx: int) -> float | None:
    """Compute ACWR for the day at ``idx`` within the pre-filled ``daily`` array.

    acute_avg  = sum(last 7 days) / 7
    chronic_avg = sum(last 28 days) / 28
    ACWR        = acute_avg / chronic_avg

    Always divides by the full window size (7 and 28) regardless of how many
    days are available, so short histories are naturally down-weighted.
    Returns None when chronic_avg is 0 (no training in 28 days).
    """
    acute_start = max(0, idx - _ACUTE_DAYS + 1)
    acute_load = sum(daily[j][1] for j in range(acute_start, idx + 1))
    acute_avg = acute_load / _ACUTE_DAYS

    chronic_start = max(0, idx - _CHRONIC_DAYS + 1)
    chronic_load = sum(daily[j][1] for j in range(chronic_start, idx + 1))
    chronic_avg = chronic_load / _CHRONIC_DAYS

    if chronic_avg == 0:
        return None
    return acute_avg / chronic_avg


def _weekly_loads(
    daily: list[tuple[str, float]],
    start_idx: int,
    end_idx: int,
) -> list[WeeklyLoad]:
    """Group daily strain in [start_idx, end_idx] by ISO calendar week.

    Returns the last 4 weeks, sorted oldest-first.
    """
    from collections import defaultdict

    # week_key → {"monday": str, "strain": float, "count": int}
    weeks: dict[str, dict] = defaultdict(lambda: {"monday": "", "strain": 0.0, "count": 0})

    for j in range(start_idx, end_idx + 1):
        d_str, strain = daily[j]
        d = date.fromisoformat(d_str)
        iso = d.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        monday = (d - timedelta(days=d.weekday())).isoformat()
        weeks[key]["monday"] = monday
        weeks[key]["strain"] += strain
        if strain > 0:
            weeks[key]["count"] += 1

    sorted_keys = sorted(weeks)[-4:]
    return [
        WeeklyLoad(
            week_start_date=weeks[k]["monday"],
            total_strain=round(weeks[k]["strain"], 2),
            workout_count=weeks[k]["count"],
        )
        for k in sorted_keys
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_training_load_ratio(
    engine: Engine,
    user_id: str | None,
    target_date: date | None = None,
) -> TrainingLoadResult:
    """Compute the ACWR and zone classification for ``target_date``.

    Fetches 34 days of history (28-day chronic window + 6-day trend lookback)
    so that ACWR trend can be computed from 7 daily values ending on target_date.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID to scope the query.
        target_date: Date to evaluate (defaults to today).

    Returns:
        TrainingLoadResult with ACWR, zone, trend, weekly loads, and an
        optional confidence note when fewer than 28 days of history exist.
    """
    if target_date is None:
        target_date = date.today()

    fetch_start = target_date - timedelta(days=_TREND_LOOKBACK)
    raw = _fetch_daily_strain(engine, fetch_start, target_date, user_id)
    daily = _fill_zeros(raw, fetch_start, target_date)

    target_idx = len(daily) - 1  # always the last element

    # --- Loads for target_date ---
    acute_start = max(0, target_idx - _ACUTE_DAYS + 1)
    chronic_start = max(0, target_idx - _CHRONIC_DAYS + 1)
    acute_load = sum(daily[j][1] for j in range(acute_start, target_idx + 1))
    chronic_load = sum(daily[j][1] for j in range(chronic_start, target_idx + 1))

    acute_avg = acute_load / _ACUTE_DAYS
    chronic_avg = chronic_load / _CHRONIC_DAYS

    # --- ACWR, zone, confidence note ---
    if raw:
        earliest_data = date.fromisoformat(min(raw.keys()))
        days_of_history = (target_date - earliest_data).days + 1
    else:
        days_of_history = 0

    if chronic_avg == 0:
        acwr = None
        zone: str | None = None
        zone_description: str | None = None
        confidence_note: str | None = (
            "No training recorded in the last 28 days — ACWR is not available"
        )
    else:
        acwr = acute_avg / chronic_avg
        zone, zone_description = _classify_zone(acwr)
        confidence_note = (
            f"ACWR based on {days_of_history} days of history "
            f"(full confidence at {_CHRONIC_DAYS} days)"
            if days_of_history < _CHRONIC_DAYS
            else None
        )

    # --- Trend: 7 daily ACWR values ending on target_date ---
    trend_start = max(0, target_idx - _ACUTE_DAYS + 1)
    trend_acwrs: list[float | None] = [
        _acwr_at(daily, i) for i in range(trend_start, target_idx + 1)
    ]
    trend = _trend_direction(trend_acwrs)

    # --- Weekly loads for the 28-day chronic window ---
    loads = _weekly_loads(daily, chronic_start, target_idx)

    logger.debug(
        "ACWR for %s: acwr=%.2f zone=%s trend=%s",
        target_date,
        acwr if acwr is not None else -1,
        zone,
        trend,
    )

    return TrainingLoadResult(
        acwr=round(acwr, 4) if acwr is not None else None,
        acute_load=round(acute_load, 2),
        chronic_load=round(chronic_load, 2),
        zone=zone,
        zone_description=zone_description,
        trend=trend,
        weekly_loads=loads,
        confidence_note=confidence_note,
    )


def get_training_load_history(
    engine: Engine,
    user_id: str | None,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Return a daily ACWR series for every day in [start_date, end_date].

    Fetches a 27-day lookback before ``start_date`` so that the first day
    in the result has a properly-seeded 28-day chronic window.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        user_id: App user UUID to scope the query.
        start_date: First date in the output (inclusive).
        end_date: Last date in the output (inclusive).

    Returns:
        List of dicts, one per calendar day:
        {date, acwr, acute_load, chronic_load, zone}
        ``acwr`` and ``zone`` are None when chronic_avg is 0.
    """
    fetch_start = start_date - timedelta(days=_CHRONIC_DAYS - 1)
    raw = _fetch_daily_strain(engine, fetch_start, end_date, user_id)
    daily = _fill_zeros(raw, fetch_start, end_date)

    start_iso = start_date.isoformat()
    results: list[dict] = []

    for i, (d, _) in enumerate(daily):
        if d < start_iso:
            continue

        acute_start = max(0, i - _ACUTE_DAYS + 1)
        chronic_start = max(0, i - _CHRONIC_DAYS + 1)
        acute_load = sum(daily[j][1] for j in range(acute_start, i + 1))
        chronic_load = sum(daily[j][1] for j in range(chronic_start, i + 1))

        acwr = _acwr_at(daily, i)
        zone: str | None
        if acwr is not None:
            zone, _ = _classify_zone(acwr)
        else:
            zone = None

        results.append(
            {
                "date": d,
                "acwr": round(acwr, 4) if acwr is not None else None,
                "acute_load": round(acute_load, 2),
                "chronic_load": round(chronic_load, 2),
                "zone": zone,
            }
        )

    return results
