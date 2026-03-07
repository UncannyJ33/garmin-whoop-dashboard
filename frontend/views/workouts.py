"""Workout analysis view — enriched workouts with Whoop + Garmin data.

Sections (top to bottom):
  1. Summary bar  — totals and averages for the selected period
  2. Type breakdown — per-activity-type table sorted by count
  3. Workout log   — condensed expander rows with full detail on click
  4. Scatter chart — strain vs next-day recovery, coloured by activity type
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from frontend.db import get_engine  # noqa: E402
from src.analytics.workout_analysis import (  # noqa: E402
    EnrichedWorkout,
    get_enriched_workouts,
    get_workout_type_summary,
)

# HR zone colour scale (Z1 easy → Z5 max)
_ZONE_COLORS = ["#4472CA", "#70AD47", "#FFC000", "#FF7A00", "#DC143C"]


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_workouts(start: str, end: str) -> list[EnrichedWorkout]:
    return get_enriched_workouts(get_engine(), date.fromisoformat(start), date.fromisoformat(end))


@st.cache_data(ttl=300)
def _load_type_summary(start: str, end: str) -> dict:
    return get_workout_type_summary(
        get_engine(), date.fromisoformat(start), date.fromisoformat(end)
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_dur(mins: float | None) -> str:
    if mins is None:
        return "—"
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _fmt_dist(m: float | None) -> str:
    return f"{m / 1000:.2f} km" if m is not None else "—"


def _fmt(v: float | None, spec: str = ".1f", suffix: str = "") -> str:
    return f"{v:{spec}}{suffix}" if v is not None else "—"


def _source_badge(w: EnrichedWorkout) -> str:
    if w.matched:
        return "W+G"
    if w.primary_source == "whoop":
        return "W"
    if w.primary_source == "garmin":
        return "G"
    return "?"


def _avg(vals: list) -> float | None:
    valid = [v for v in vals if v is not None]
    return sum(valid) / len(valid) if valid else None


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


def _hr_zone_chart(w: EnrichedWorkout) -> alt.Chart | None:
    """Single horizontal stacked bar showing time in each HR zone."""
    rows = [
        {"Zone": f"Z{i}", "Minutes": w.hr_zone_minutes.get(f"zone{i}") or 0.0, "order": i}
        for i in range(1, 6)
    ]
    rows = [r for r in rows if r["Minutes"] > 0]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(
                "sum(Minutes):Q",
                stack="zero",
                title="Minutes",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "Zone:N",
                sort=["Z1", "Z2", "Z3", "Z4", "Z5"],
                scale=alt.Scale(range=_ZONE_COLORS),
                legend=alt.Legend(orient="bottom", columns=5),
            ),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("Zone:N"), alt.Tooltip("Minutes:Q", format=".0f")],
        )
        .properties(height=40)
    )


# ---------------------------------------------------------------------------
# Detail renderer (inside expander)
# ---------------------------------------------------------------------------


def _render_detail(w: EnrichedWorkout) -> None:
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Physiological Load**")
        st.metric("Strain", _fmt(w.strain, ".1f"))
        st.metric("Avg HR", f"{w.avg_hr} bpm" if w.avg_hr else "—")
        st.metric("Max HR", f"{w.max_hr} bpm" if w.max_hr else "—")
        st.metric("Calories", _fmt(w.calories_kj, ".0f", " kJ"))
        st.metric("Intensity", _fmt(w.strain_per_minute, ".3f", " strain/min"))

    with c2:
        st.markdown("**Performance**")
        st.metric("Distance", _fmt_dist(w.distance_m))
        st.metric("Avg Pace", _fmt(w.avg_pace_min_per_km, ".2f", " min/km"))
        st.metric("Elevation", _fmt(w.elevation_gain_m, ".0f", " m"))
        st.metric("Cadence", _fmt(w.avg_cadence, ".0f", " spm"))
        st.metric("Training Load", _fmt(w.training_load, ".1f"))
        st.metric("Aerobic Effect", _fmt(w.training_effect_aerobic, ".1f"))
        st.metric("Anaerobic Effect", _fmt(w.training_effect_anaerobic, ".1f"))
        st.metric("VO2 Max", _fmt(w.vo2_max, ".1f"))

    with c3:
        st.markdown("**Running Dynamics**")
        st.metric("Ground Contact", _fmt(w.avg_ground_contact_time_ms, ".0f", " ms"))
        st.metric("Vert Oscillation", _fmt(w.avg_vertical_oscillation_cm, ".1f", " cm"))
        st.metric("Vert Ratio", _fmt(w.avg_vertical_ratio_pct, ".1f", "%"))
        st.metric("Stride Length", _fmt(w.avg_stride_length, ".2f", " m"))
        st.metric("Efficiency", _fmt(w.efficiency_score, ".0f", " m/strain"))

    # HR zone distribution
    zone_chart = _hr_zone_chart(w)
    if zone_chart is not None:
        st.markdown("**HR Zone Distribution**")
        st.altair_chart(zone_chart, use_container_width=True)

    # Recovery impact
    if w.next_day_recovery is not None:
        if w.recovery_impact is not None:
            direction = "above" if w.recovery_impact >= 0 else "below"
            delta = abs(w.recovery_impact)
            st.info(
                f"Next-day recovery was **{w.next_day_recovery:.0f}**, "
                f"which is **{delta:.1f} points {direction}** your 7-day average."
            )
        else:
            st.info(f"Next-day recovery: {w.next_day_recovery:.0f}")


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render(start_date: date, end_date: date) -> None:
    st.title("Workouts")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load workout data. This may be a temporary database issue. Details: `{exc}`"
        )


def _render_body(start_date: date, end_date: date) -> None:
    workouts = _load_workouts(start_date.isoformat(), end_date.isoformat())
    type_summary = _load_type_summary(start_date.isoformat(), end_date.isoformat())

    if not workouts:
        st.warning("No workout data for the selected date range.")
        return

    # ── 2. SUMMARY BAR ───────────────────────────────────────────────────────
    total_strain = sum(w.strain for w in workouts if w.strain is not None)
    total_minutes = sum(w.duration_minutes for w in workouts if w.duration_minutes is not None)
    avg_strain = total_strain / len(workouts) if workouts else None

    type_counts: dict[str, int] = {}
    for w in workouts:
        t = w.activity_type or "unknown"
        type_counts[t] = type_counts.get(t, 0) + 1
    most_common = max(type_counts, key=lambda k: type_counts[k]) if type_counts else "—"

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.metric("Workouts", len(workouts))
    with s2:
        st.metric("Total Strain", f"{total_strain:.1f}")
    with s3:
        st.metric("Training Time", _fmt_dur(total_minutes))
    with s4:
        st.metric("Avg Strain", f"{avg_strain:.1f}" if avg_strain is not None else "—")
    with s5:
        st.metric("Top Activity", most_common.title())

    st.divider()

    # ── 3. ACTIVITY TYPE BREAKDOWN ────────────────────────────────────────────
    st.subheader("Activity Type Breakdown")

    if type_summary:
        # Group workouts by type to compute avg HR (not in type_summary)
        by_type: dict[str, list[EnrichedWorkout]] = {}
        for w in workouts:
            by_type.setdefault(w.activity_type or "unknown", []).append(w)

        rows = []
        for atype, stats in sorted(type_summary.items(), key=lambda x: -x[1]["count"]):
            avg_hr = _avg([w.avg_hr for w in by_type.get(atype, [])])
            rows.append(
                {
                    "Activity": atype.title(),
                    "Count": stats["count"],
                    "Avg Strain": _fmt(stats["avg_strain"], ".1f"),
                    "Avg Duration": _fmt_dur(stats["avg_duration_minutes"]),
                    "Avg HR": f"{avg_hr:.0f} bpm" if avg_hr is not None else "—",
                    "Efficiency (m/strain)": _fmt(stats["avg_efficiency_score"], ".0f"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── 4. WORKOUT LOG ────────────────────────────────────────────────────────
    st.subheader("Workout Log")
    st.caption("Click a row to expand full details, HR zone breakdown, and recovery impact.")

    for w in sorted(workouts, key=lambda x: x.date, reverse=True):
        badge = _source_badge(w)
        atype = (w.activity_type or "Unknown").title()
        label = (
            f"{w.date}  ·  {atype}  ·  {_fmt_dur(w.duration_minutes)}  ·  "
            f"Strain: {_fmt(w.strain, '.1f')}  ·  "
            f"HR: {f'{w.avg_hr} bpm' if w.avg_hr else '—'}  ·  "
            f"Dist: {_fmt_dist(w.distance_m)}  ·  "
            f"Eff: {_fmt(w.efficiency_score, '.0f', ' m/s')}  ·  "
            f"[{badge}]"
        )
        with st.expander(label, expanded=False):
            _render_detail(w)

    st.divider()

    # ── 5. STRAIN vs RECOVERY SCATTER ─────────────────────────────────────────
    st.subheader("Strain vs Next-Day Recovery")

    scatter_rows = [
        {
            "Strain": w.strain,
            "Next-Day Recovery": w.next_day_recovery,
            "Activity": (w.activity_type or "unknown").title(),
            "Date": w.date,
            "Duration": _fmt_dur(w.duration_minutes),
            "Recovery Impact": _fmt(w.recovery_impact, "+.1f", " pts"),
        }
        for w in workouts
        if w.strain is not None and w.next_day_recovery is not None
    ]

    if not scatter_rows:
        st.info("Not enough paired strain + recovery data for this period.")
    else:
        scatter_df = pd.DataFrame(scatter_rows)
        scatter = (
            alt.Chart(scatter_df)
            .mark_circle(size=80, opacity=0.75)
            .encode(
                x=alt.X("Strain:Q", title="Workout Strain", scale=alt.Scale(zero=True)),
                y=alt.Y(
                    "Next-Day Recovery:Q",
                    title="Next-Day Recovery",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                color=alt.Color("Activity:N", title="Activity"),
                tooltip=[
                    alt.Tooltip("Date:N", title="Date"),
                    alt.Tooltip("Activity:N"),
                    alt.Tooltip("Strain:Q", format=".1f"),
                    alt.Tooltip("Next-Day Recovery:Q", format=".0f"),
                    alt.Tooltip("Duration:N"),
                    alt.Tooltip("Recovery Impact:N"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(scatter, use_container_width=True)
        st.caption(
            "Each dot is one workout. Dots in the upper-right corner indicate high-strain "
            "sessions your body recovers well from."
        )
