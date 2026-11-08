"""Schema comparison tool: side-by-side view of Whoop vs Garmin data.

Alignment rules (Whoop is source of truth):
  - Daily  : Whoop recovery keyed by DATE(whoop_cycles.start_time)
             matched to garmin_daily_summary.date
  - Sleep  : Whoop sleep keyed by DATE(whoop_sleep.end_time) (wake-up date)
             matched to garmin_sleep.date
  - Workouts: Whoop strain-only workouts (strain IS NOT NULL)
              matched to garmin_activities by start-time diff ≤5 min AND
              duration diff ≤20% of the longer activity

Note: dev-only; keeps UTC DATE(...) keys, whereas the production normalizer keys
Whoop dates by local time (see whoop_mapper.local_date).

Output: formatted table to stdout + CSV files saved to data/review/.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import TextClause
from tabulate import tabulate

logger = logging.getLogger(__name__)

REVIEW_DIR = Path("data/review")
_MATCH_START_THRESHOLD_MIN = 5
_MATCH_DURATION_THRESHOLD_PCT = 0.20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_review_dir() -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def _fmt(value: object, fmt: str = "") -> str:
    """Format a value for display, returning '—' for None/NaN."""
    if value is None:
        return "—"
    if isinstance(value, float) and (value != value):  # NaN check
        return "—"
    if fmt:
        return format(value, fmt)
    return str(value)


def _default_range() -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    return today - timedelta(days=14), today


# ---------------------------------------------------------------------------
# Daily comparison
# ---------------------------------------------------------------------------


def _load_daily(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Return Whoop recovery + Garmin daily summary merged on date."""
    whoop_sql = text("""
        SELECT
            DATE(wc.start_time)        AS date,
            wr.recovery_score          AS whoop_recovery,
            ROUND(wr.hrv_rmssd, 1)     AS whoop_hrv_ms,
            ROUND(wr.resting_heart_rate, 0) AS whoop_rhr,
            ROUND(wc.strain, 1)        AS whoop_strain,
            ROUND(wr.spo2_pct, 1)      AS whoop_spo2
        FROM whoop_recovery wr
        JOIN whoop_cycles wc ON wr.cycle_id = wc.id
        WHERE DATE(wc.start_time) >= :start
          AND DATE(wc.start_time) <= :end
        ORDER BY date
    """)

    garmin_sql = text("""
        SELECT
            date,
            body_battery_high          AS garmin_bb_high,
            body_battery_low           AS garmin_bb_low,
            resting_heart_rate         AS garmin_rhr,
            avg_stress_level           AS garmin_stress,
            ROUND(avg_spo2, 1)         AS garmin_spo2
        FROM garmin_daily_summary
        WHERE date >= :start
          AND date <= :end
        ORDER BY date
    """)

    w, g = _read_pair(engine, whoop_sql, garmin_sql, start, end)
    return pd.merge(w, g, on="date", how="outer").sort_values("date").reset_index(drop=True)


def _read_pair(
    engine: Engine, whoop_sql: TextClause, garmin_sql: TextClause, start: date, end: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the Whoop and Garmin queries over [start, end] and return both frames."""
    params = {"start": start.isoformat(), "end": end.isoformat()}
    with engine.connect() as conn:
        return (
            pd.read_sql(whoop_sql, conn, params=params),
            pd.read_sql(garmin_sql, conn, params=params),
        )


# ---------------------------------------------------------------------------
# Sleep comparison
# ---------------------------------------------------------------------------


def _load_sleep(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Return Whoop sleep + Garmin sleep merged on wake-up date, all in minutes."""
    whoop_sql = text("""
        SELECT
            DATE(end_time)                          AS date,
            ROUND(total_in_bed_ms / 60000.0, 1)    AS whoop_in_bed_min,
            ROUND(total_sws_ms / 60000.0, 1)        AS whoop_deep_min,
            ROUND(total_light_ms / 60000.0, 1)      AS whoop_light_min,
            ROUND(total_rem_ms / 60000.0, 1)         AS whoop_rem_min,
            ROUND(total_awake_ms / 60000.0, 1)      AS whoop_awake_min,
            ROUND(sleep_performance, 1)             AS whoop_perf_pct
        FROM whoop_sleep
        WHERE nap = false
          AND DATE(end_time) >= :start
          AND DATE(end_time) <= :end
        ORDER BY date
    """)

    garmin_sql = text("""
        SELECT
            date,
            ROUND(total_sleep_seconds / 60.0, 1)   AS garmin_total_min,
            ROUND(deep_sleep_seconds / 60.0, 1)    AS garmin_deep_min,
            ROUND(light_sleep_seconds / 60.0, 1)   AS garmin_light_min,
            ROUND(rem_sleep_seconds / 60.0, 1)      AS garmin_rem_min,
            ROUND(awake_seconds / 60.0, 1)          AS garmin_awake_min,
            ROUND(sleep_score, 1)                   AS garmin_sleep_score
        FROM garmin_sleep
        WHERE date >= :start
          AND date <= :end
        ORDER BY date
    """)

    w, g = _read_pair(engine, whoop_sql, garmin_sql, start, end)
    return pd.merge(w, g, on="date", how="outer").sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Workout comparison
# ---------------------------------------------------------------------------


def _load_workouts(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Return Whoop strain workouts and Garmin activities with match flags."""
    whoop_sql = text("""
        SELECT
            DATE(start_time)   AS date,
            start_time         AS whoop_start,
            end_time           AS whoop_end,
            sport_name         AS whoop_sport,
            ROUND(strain, 2)   AS whoop_strain,
            avg_heart_rate     AS whoop_avg_hr,
            distance_meter     AS whoop_dist_m
        FROM whoop_workouts
        WHERE strain IS NOT NULL
          AND DATE(start_time) >= :start
          AND DATE(start_time) <= :end
        ORDER BY start_time
    """)

    garmin_sql = text("""
        SELECT
            -- Use start_time_gmt (UTC) for date bucketing so Whoop UTC dates align.
            -- Fall back to local start_time if gmt is missing.
            DATE(COALESCE(start_time_gmt, start_time)) AS date,
            start_time                                  AS garmin_start,
            start_time_gmt                              AS garmin_start_gmt,
            ROUND(duration_seconds / 60.0, 1)           AS garmin_dur_min,
            duration_seconds                            AS garmin_dur_s,
            activity_type                               AS garmin_type,
            avg_heart_rate                              AS garmin_avg_hr,
            distance_meters                             AS garmin_dist_m
        FROM garmin_activities
        WHERE DATE(COALESCE(start_time_gmt, start_time)) >= :start
          AND DATE(COALESCE(start_time_gmt, start_time)) <= :end
        ORDER BY start_time_gmt
    """)

    w, g = _read_pair(engine, whoop_sql, garmin_sql, start, end)

    if w.empty and g.empty:
        return pd.DataFrame()

    # Parse timestamps for matching.
    # Whoop start_time is UTC (stored with Z / offset). Garmin start_time_gmt is also
    # UTC but stored without a tz marker. Convert both to tz-naive UTC so they're
    # directly comparable regardless of the user's local timezone.
    if not w.empty:
        w["_w_start_dt"] = pd.to_datetime(w["whoop_start"], utc=True).dt.tz_convert(None)
        w["_w_end_dt"] = pd.to_datetime(w["whoop_end"], utc=True).dt.tz_convert(None)
        w["whoop_dur_min"] = ((w["_w_end_dt"] - w["_w_start_dt"]).dt.total_seconds() / 60).round(1)
        w["_w_dur_s"] = (w["_w_end_dt"] - w["_w_start_dt"]).dt.total_seconds()

    if not g.empty:
        # garmin_start_gmt is naive UTC in SQLite; parse directly, fall back to local.
        gmt_col = g["garmin_start_gmt"].fillna(g["garmin_start"])
        g["_g_start_dt"] = pd.to_datetime(gmt_col)

    # Match pairs within threshold, per day
    all_dates = sorted(
        set(w["date"].tolist() if not w.empty else [])
        | set(g["date"].tolist() if not g.empty else [])
    )
    rows = []

    for d in all_dates:
        w_day = w[w["date"] == d].copy() if not w.empty else pd.DataFrame()
        g_day = g[g["date"] == d].copy() if not g.empty else pd.DataFrame()

        matched_w: set[int] = set()
        matched_g: set[int] = set()

        # Try to match each Garmin activity to the closest Whoop workout
        for gi, grow in g_day.iterrows():
            best_wi = None
            best_start_diff = float("inf")
            for wi, wrow in w_day.iterrows():
                if wi in matched_w:
                    continue
                start_diff_min = abs(
                    (grow["_g_start_dt"] - wrow["_w_start_dt"]).total_seconds() / 60
                )
                if start_diff_min > _MATCH_START_THRESHOLD_MIN:
                    continue
                w_dur = wrow["_w_dur_s"]
                g_dur = grow["garmin_dur_s"]
                if w_dur and g_dur and w_dur > 0 and g_dur > 0:
                    dur_diff_pct = abs(w_dur - g_dur) / max(w_dur, g_dur)
                    if (
                        dur_diff_pct <= _MATCH_DURATION_THRESHOLD_PCT
                        and start_diff_min < best_start_diff
                    ):
                        best_start_diff = start_diff_min
                        best_wi = wi

            if best_wi is not None:
                wrow = w_day.loc[best_wi]
                matched_w.add(best_wi)
                matched_g.add(gi)
                rows.append(_matched_row(d, wrow, grow))

        # Unmatched Whoop
        for wi, wrow in w_day.iterrows():
            if wi not in matched_w:
                rows.append(_whoop_only_row(d, wrow))

        # Unmatched Garmin
        for gi, grow in g_day.iterrows():
            if gi not in matched_g:
                rows.append(_garmin_only_row(d, grow))

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(["date", "whoop_start", "garmin_start"])
        .reset_index(drop=True)
    )


def _matched_row(d: str, w: "pd.Series", g: "pd.Series") -> dict[str, Any]:
    return {
        "date": d,
        "match": "✓",
        "whoop_start": w["whoop_start"],
        "whoop_sport": w["whoop_sport"],
        "whoop_dur_min": w["whoop_dur_min"],
        "whoop_strain": w["whoop_strain"],
        "whoop_avg_hr": w["whoop_avg_hr"],
        "whoop_dist_m": w["whoop_dist_m"],
        "garmin_start": g["garmin_start"],
        "garmin_type": g["garmin_type"],
        "garmin_dur_min": g["garmin_dur_min"],
        "garmin_avg_hr": g["garmin_avg_hr"],
        "garmin_dist_m": g["garmin_dist_m"],
    }


def _whoop_only_row(d: str, w: "pd.Series") -> dict[str, Any]:
    return {
        "date": d,
        "match": "—",
        "whoop_start": w["whoop_start"],
        "whoop_sport": w["whoop_sport"],
        "whoop_dur_min": w["whoop_dur_min"],
        "whoop_strain": w["whoop_strain"],
        "whoop_avg_hr": w["whoop_avg_hr"],
        "whoop_dist_m": w["whoop_dist_m"],
        "garmin_start": None,
        "garmin_type": None,
        "garmin_dur_min": None,
        "garmin_avg_hr": None,
        "garmin_dist_m": None,
    }


def _garmin_only_row(d: str, g: "pd.Series") -> dict[str, Any]:
    return {
        "date": d,
        "match": "—",
        "whoop_start": None,
        "whoop_sport": None,
        "whoop_dur_min": None,
        "whoop_strain": None,
        "whoop_avg_hr": None,
        "whoop_dist_m": None,
        "garmin_start": g["garmin_start"],
        "garmin_type": g["garmin_type"],
        "garmin_dur_min": g["garmin_dur_min"],
        "garmin_avg_hr": g["garmin_avg_hr"],
        "garmin_dist_m": g["garmin_dist_m"],
    }


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------


def _print_section(title: str, df: pd.DataFrame, tablefmt: str = "simple") -> None:
    """Print a labelled section with row count."""
    bar = "═" * 70
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)
    if df.empty:
        print("  (no data in range)")
        return
    # Replace NaN with — for display
    display = df.fillna("—")
    print(tabulate(display, headers="keys", tablefmt=tablefmt, showindex=False))
    print(f"\n  {len(df)} rows")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_comparison(
    engine: Engine,
    start: date | None = None,
    end: date | None = None,
    tablefmt: str = "simple",
    save_csv: bool = True,
) -> dict[str, pd.DataFrame]:
    """Run all three comparisons and print + save results.

    Args:
        engine: SQLAlchemy engine connected to the fitness database.
        start: Start date for the comparison window. Defaults to 14 days ago.
        end: End date (inclusive). Defaults to today.
        tablefmt: tabulate format string (e.g. "simple", "grid", "pipe").
        save_csv: Whether to save CSV files to data/review/.

    Returns:
        Dict with keys "daily", "sleep", "workouts" mapping to DataFrames.
    """
    if start is None or end is None:
        default_start, default_end = _default_range()
        start = start or default_start
        end = end or default_end

    print(f"\nSchema comparison: {start} → {end}")
    print(f"Generated at: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")

    daily_df = _load_daily(engine, start, end)
    sleep_df = _load_sleep(engine, start, end)
    workout_df = _load_workouts(engine, start, end)

    _print_section("DAILY  —  Whoop Recovery vs Garmin Daily Summary", daily_df, tablefmt)
    _print_section("SLEEP  —  Whoop Sleep vs Garmin Sleep (minutes)", sleep_df, tablefmt)
    _print_section(
        "WORKOUTS  —  Whoop Strain vs Garmin Activities  (✓ = matched)", workout_df, tablefmt
    )

    if save_csv:
        _ensure_review_dir()
        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M")
        paths = {
            "daily": REVIEW_DIR / f"daily_{ts}.csv",
            "sleep": REVIEW_DIR / f"sleep_{ts}.csv",
            "workouts": REVIEW_DIR / f"workouts_{ts}.csv",
        }
        daily_df.to_csv(paths["daily"], index=False)
        sleep_df.to_csv(paths["sleep"], index=False)
        workout_df.to_csv(paths["workouts"], index=False)
        print(f"\nCSVs saved to {REVIEW_DIR}/")
        for name, path in paths.items():
            print(f"  {name:10s} → {path.name}")

    return {"daily": daily_df, "sleep": sleep_df, "workouts": workout_df}
