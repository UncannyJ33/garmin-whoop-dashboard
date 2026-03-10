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
from sqlalchemy import text  # noqa: E402

from frontend.db import get_engine  # noqa: E402
from src.analytics.workout_analysis import (  # noqa: E402
    EnrichedWorkout,
    get_enriched_workouts,
    get_workout_type_summary,
)

_STRENGTH_TYPES = {
    "strength_training",
    "weight_training",
    "indoor_cardio",
    "hiit",
    "pilates",
    "yoga",
}

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


@st.cache_data(ttl=300)
def _load_exercise_sets(garmin_activity_id: str) -> list[dict]:
    """Load exercise sets for a single Garmin strength activity."""
    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT set_order, set_type, exercise_category, exercise_name,
                       repetition_count, weight_kg, duration_seconds
                FROM garmin_exercise_sets
                WHERE activity_id = :aid
                ORDER BY set_order
            """),
                {"aid": garmin_activity_id},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
@st.cache_data(ttl=300)
def _load_strength_session_volume(start: str, end: str) -> list[dict]:
    """Load total volume (kg × reps) per strength session for the date range."""
    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT
                    uw.date,
                    SUM(es.repetition_count * es.weight_kg) AS total_volume_kg
                FROM unified_workouts uw
                JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                WHERE uw.date BETWEEN :start AND :end
                  AND es.set_type = 'ACTIVE'
                  AND es.repetition_count IS NOT NULL
                  AND es.weight_kg IS NOT NULL
                  AND es.weight_kg > 0
                GROUP BY uw.date
                ORDER BY uw.date
            """),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def _load_strength_max_weight(start: str, end: str) -> list[dict]:
    """Load max weight per tracked exercise per session for the date range."""
    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT
                    uw.date,
                    es.exercise_name,
                    MAX(es.weight_kg) AS max_weight_kg
                FROM unified_workouts uw
                JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                WHERE uw.date BETWEEN :start AND :end
                  AND es.set_type = 'ACTIVE'
                  AND es.weight_kg IS NOT NULL
                  AND es.weight_kg > 0
                GROUP BY uw.date, es.exercise_name
                ORDER BY uw.date, es.exercise_name
            """),
                {"start": start, "end": end},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


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

    # Exercise sets (strength activities only)
    is_strength = (w.activity_type or "").lower() in _STRENGTH_TYPES
    if is_strength and w.garmin_activity_id:
        sets = _load_exercise_sets(w.garmin_activity_id)
        active_sets = [s for s in sets if s["set_type"] == "ACTIVE"]
        if active_sets:
            st.markdown("**Exercise Sets**")
            # Group by exercise name
            by_exercise: dict[str, list[dict]] = {}
            for s in active_sets:
                name = (
                    (s["exercise_name"] or s["exercise_category"] or "Unknown")
                    .replace("_", " ")
                    .title()
                )
                by_exercise.setdefault(name, []).append(s)
            for ex_name, ex_sets in by_exercise.items():
                set_rows = []
                total_volume = 0.0
                for i, s in enumerate(ex_sets, 1):
                    reps = s["repetition_count"]
                    kg = s["weight_kg"]
                    vol = (reps or 0) * (kg or 0)
                    total_volume += vol
                    set_rows.append(
                        {
                            "Set": i,
                            "Reps": reps if reps is not None else "—",
                            "Weight (kg)": f"{kg:.1f}" if kg is not None else "BW",
                            "Volume (kg)": f"{vol:.0f}" if (reps and kg) else "—",
                        }
                    )
                vol_str = f"  ·  {total_volume:.0f} kg total volume" if total_volume > 0 else ""
                st.markdown(f"*{ex_name}* — {len(ex_sets)} sets{vol_str}")
                st.dataframe(pd.DataFrame(set_rows), width="stretch", hide_index=True)

    # HR zone distribution
    zone_chart = _hr_zone_chart(w)
    if zone_chart is not None:
        st.markdown("**HR Zone Distribution**")
        st.altair_chart(zone_chart, width="stretch")

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
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.divider()

    # ── 4. STRAIN vs RECOVERY SCATTER ─────────────────────────────────────────
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
        all_activity_types = sorted(scatter_df["Activity"].unique().tolist())
        selected_types = st.multiselect(
            "Filter activities",
            options=all_activity_types,
            default=all_activity_types,
            key="scatter_activity_filter",
        )
        filtered_df = scatter_df[scatter_df["Activity"].isin(selected_types)]
        if filtered_df.empty:
            st.info("No data for the selected activity types.")
        else:
            scatter = (
                alt.Chart(filtered_df)
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
            st.altair_chart(scatter, width="stretch")
            st.caption(
                "Each dot is one workout. Dots in the upper-right corner indicate high-strain "
                "sessions your body recovers well from."
            )

    st.divider()

    # ── 6. RUNNING SECTION ────────────────────────────────────────────────────
    runs = [
        w
        for w in sorted(workouts, key=lambda x: x.date)
        if (w.activity_type or "").lower().find("run") != -1
    ]

    if not runs:
        st.info("No running data in the selected date range.")
        return

    st.subheader("Running")

    # ── 6a. Weekly Volume ─────────────────────────────────────────────────────
    st.markdown("**Weekly Volume**")

    from datetime import datetime  # noqa: E402 (local import to avoid top-level churn)

    week_vol: dict[str, dict] = {}
    for w in runs:
        d = datetime.fromisoformat(w.date)
        # ISO week label: "YYYY-Www"
        week = d.strftime("%G-W%V")
        if week not in week_vol:
            week_vol[week] = {"Week": week, "Distance (km)": 0.0, "Time (min)": 0.0}
        if w.distance_m is not None:
            week_vol[week]["Distance (km)"] += w.distance_m / 1000
        if w.duration_minutes is not None:
            week_vol[week]["Time (min)"] += w.duration_minutes

    if week_vol:
        vol_df = pd.DataFrame(sorted(week_vol.values(), key=lambda r: r["Week"]))

        vol_dist = (
            alt.Chart(vol_df)
            .mark_bar(color="#4472CA")
            .encode(
                x=alt.X("Week:N", title="Week", sort=None),
                y=alt.Y("Distance (km):Q", title="Distance (km)"),
                tooltip=[
                    alt.Tooltip("Week:N"),
                    alt.Tooltip("Distance (km):Q", format=".1f"),
                    alt.Tooltip("Time (min):Q", format=".0f", title="Time (min)"),
                ],
            )
            .properties(height=200)
        )
        vol_time = (
            alt.Chart(vol_df)
            .mark_bar(color="#70AD47")
            .encode(
                x=alt.X("Week:N", title="Week", sort=None),
                y=alt.Y("Time (min):Q", title="Time on Foot (min)"),
                tooltip=[
                    alt.Tooltip("Week:N"),
                    alt.Tooltip("Distance (km):Q", format=".1f"),
                    alt.Tooltip("Time (min):Q", format=".0f", title="Time (min)"),
                ],
            )
            .properties(height=200)
        )
        st.altair_chart(vol_dist | vol_time, width="stretch")
        st.caption("Weekly totals across all runs in the selected period.")

    st.divider()

    # ── 6b. Running Dynamics Trends ───────────────────────────────────────────
    st.markdown("**Running Dynamics Trends**")

    dyn_metrics = {
        "Cadence (spm)": "avg_cadence",
        "Vertical Ratio (%)": "avg_vertical_ratio_pct",
        "Vertical Oscillation (cm)": "avg_vertical_oscillation_cm",
        "Ground Contact (ms)": "avg_ground_contact_time_ms",
        "Stride Length (m)": "avg_stride_length",
    }
    metric_label = st.selectbox("Metric", list(dyn_metrics.keys()), key="run_dyn_metric")
    field = dyn_metrics[metric_label]

    dyn_rows = [
        {"Date": w.date, metric_label: getattr(w, field)}
        for w in runs
        if getattr(w, field) is not None
    ]

    if len(dyn_rows) < 2:
        st.info("Not enough running dynamics data in this period.")
    else:
        dyn_df = pd.DataFrame(dyn_rows)
        # Reference bands for cadence
        layers: list[alt.Chart] = []
        if metric_label == "Cadence (spm)":
            band_df = pd.DataFrame([{"y1": 170, "y2": 185}])
            band = (
                alt.Chart(band_df)
                .mark_rect(opacity=0.10, color="#70AD47")
                .encode(y=alt.Y("y1:Q"), y2=alt.Y2("y2:Q"))
            )
            layers.append(band)

        line = (
            alt.Chart(dyn_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("Date:T", title="Date"),
                y=alt.Y(f"{metric_label}:Q", title=metric_label),
                tooltip=[
                    alt.Tooltip("Date:T", format="%b %d"),
                    alt.Tooltip(f"{metric_label}:Q", format=".2f"),
                ],
            )
            .properties(height=260)
        )
        layers.append(line)
        st.altair_chart(alt.layer(*layers), width="stretch")
        if metric_label == "Cadence (spm)":
            st.caption("Green band = optimal cadence zone (170–185 spm).")
        elif metric_label == "Vertical Ratio (%)":
            st.caption("Lower is better — indicates less energy lost to vertical movement.")
        elif metric_label == "Vertical Oscillation (cm)":
            st.caption("Lower is better — less bounce means more forward propulsion.")
        elif metric_label == "Ground Contact (ms)":
            st.caption("Lower is better — shorter contact time indicates more elastic running.")

    st.divider()

    # ── 6c. Pace vs Cadence Scatter ───────────────────────────────────────────
    st.markdown("**Pace vs Cadence**")

    pc_rows = [
        {
            "Avg Pace (min/km)": w.avg_pace_min_per_km,
            "Cadence (spm)": w.avg_cadence,
            "Date": w.date,
            "Distance": _fmt_dist(w.distance_m),
            "Duration": _fmt_dur(w.duration_minutes),
        }
        for w in runs
        if w.avg_pace_min_per_km is not None and w.avg_cadence is not None
    ]

    if len(pc_rows) < 3:
        st.info("Not enough runs with both pace and cadence data.")
    else:
        pc_df = pd.DataFrame(pc_rows)
        pc_scatter = (
            alt.Chart(pc_df)
            .mark_circle(size=80, opacity=0.75, color="#4472CA")
            .encode(
                x=alt.X(
                    "Cadence (spm):Q",
                    title="Avg Cadence (spm)",
                    scale=alt.Scale(zero=False),
                ),
                y=alt.Y(
                    "Avg Pace (min/km):Q",
                    title="Avg Pace (min/km)",
                    scale=alt.Scale(zero=False),
                    sort="descending",
                ),
                tooltip=[
                    alt.Tooltip("Date:N"),
                    alt.Tooltip("Cadence (spm):Q", format=".0f"),
                    alt.Tooltip("Avg Pace (min/km):Q", format=".2f"),
                    alt.Tooltip("Distance:N"),
                    alt.Tooltip("Duration:N"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(pc_scatter, width="stretch")
        st.caption(
            "Y-axis is inverted — lower = faster. Higher cadence with faster pace suggests "
            "efficient turnover rather than overstriding."
        )

    st.divider()

    # ── 6d. Training Load Over Time ───────────────────────────────────────────
    st.markdown("**Training Load Over Time**")

    tl_rows = [
        {
            "Date": w.date,
            "Training Load": w.training_load,
            "Aerobic Effect": w.training_effect_aerobic,
            "Anaerobic Effect": w.training_effect_anaerobic,
        }
        for w in runs
        if w.training_load is not None
    ]

    if len(tl_rows) < 2:
        st.info("Not enough training load data in this period.")
    else:
        tl_df = pd.DataFrame(tl_rows)
        tl_bar = (
            alt.Chart(tl_df)
            .mark_bar(color="#4472CA", opacity=0.85)
            .encode(
                x=alt.X("Date:T", title="Date"),
                y=alt.Y("Training Load:Q", title="Training Load"),
                tooltip=[
                    alt.Tooltip("Date:T", format="%b %d"),
                    alt.Tooltip("Training Load:Q", format=".1f"),
                    alt.Tooltip("Aerobic Effect:Q", format=".1f"),
                    alt.Tooltip("Anaerobic Effect:Q", format=".1f"),
                ],
            )
            .properties(height=200)
        )
        st.altair_chart(tl_bar, width="stretch")
        st.caption(
            "Garmin training load per run. Hover for aerobic/anaerobic training effect breakdown."
        )

    st.divider()

    # ── 6e. VO2 Max Trend ─────────────────────────────────────────────────────
    st.markdown("**VO2 Max Trend**")

    vo2_rows = [{"Date": w.date, "VO2 Max": w.vo2_max} for w in runs if w.vo2_max is not None]

    if len(vo2_rows) < 2:
        st.info("Not enough VO2 max readings in this period.")
    else:
        vo2_df = pd.DataFrame(vo2_rows)
        vo2_line = (
            alt.Chart(vo2_df)
            .mark_line(point=True, color="#FFC000")
            .encode(
                x=alt.X("Date:T", title="Date"),
                y=alt.Y(
                    "VO2 Max:Q",
                    title="VO2 Max (mL/kg/min)",
                    scale=alt.Scale(zero=False),
                ),
                tooltip=[
                    alt.Tooltip("Date:T", format="%b %d"),
                    alt.Tooltip("VO2 Max:Q", format=".1f"),
                ],
            )
            .properties(height=200)
        )
        st.altair_chart(vo2_line, width="stretch")
        st.caption(
            "Garmin estimated VO2 max from run effort. Upward trend indicates improving aerobic fitness."
        )

    st.divider()

    # ── 7. STRENGTH SECTION ───────────────────────────────────────────────────
    strength_workouts = [
        w
        for w in sorted(workouts, key=lambda x: x.date)
        if (w.activity_type or "").lower() in _STRENGTH_TYPES
    ]

    if strength_workouts:
        st.subheader("Strength Training")

        # Exercises to track, keyed by Garmin exercise_name → display label
        _TRACKED_EXERCISES: dict[str, str] = {
            "BARBELL_DEADLIFT": "Deadlift",
            "STRAIGHT_LEG_DEADLIFT": "Romanian Deadlift",
            "BARBELL_FRONT_SQUAT": "Front Squat",
            "BARBELL_SQUAT": "Squat",
            "INCLINE_DUMBBELL_BENCH_PRESS": "Incline DB Press",
            "BARBELL_BENCH_PRESS": "Barbell Bench",
            "LAT_PULLDOWN": "Lat Pulldown",
        }

        # ── 7a. Max weight trend ──────────────────────────────────────────────
        st.markdown("**Max Weight Per Session**")
        weight_rows = _load_strength_max_weight(start_date.isoformat(), end_date.isoformat())

        if not weight_rows:
            st.info("No exercise set data yet — run a sync to fetch strength set details.")
        else:
            wdf = pd.DataFrame(weight_rows)
            wdf = wdf[wdf["exercise_name"].isin(_TRACKED_EXERCISES)].copy()

            if wdf.empty:
                st.info("No tracked exercises found in this period.")
            else:
                wdf["Exercise"] = wdf["exercise_name"].map(_TRACKED_EXERCISES)
                wdf["date"] = pd.to_datetime(wdf["date"]).dt.date.astype(str)
                wdf["max_weight_lb"] = wdf["max_weight_kg"] * 2.20462

                weight_chart = (
                    alt.Chart(wdf)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X(
                            "date:O",
                            title="Date",
                            axis=alt.Axis(labelAngle=-30),
                        ),
                        y=alt.Y(
                            "max_weight_lb:Q",
                            title="Max Weight (lb)",
                            scale=alt.Scale(zero=False),
                        ),
                        color=alt.Color("Exercise:N", title="Exercise"),
                        tooltip=[
                            alt.Tooltip("date:O", title="Date"),
                            alt.Tooltip("Exercise:N"),
                            alt.Tooltip("max_weight_lb:Q", format=".1f", title="Max Weight (lb)"),
                        ],
                    )
                    .properties(height=320)
                )
                st.altair_chart(weight_chart, width="stretch")
                st.caption(
                    "Max weight lifted per session. New exercises appear automatically once synced."
                )

        st.divider()

        # ── 7b. Total Volume per Session ─────────────────────────────────────
        st.markdown("**Total Volume Per Session**")
        vol_rows = _load_strength_session_volume(start_date.isoformat(), end_date.isoformat())

        if not vol_rows:
            st.info("No volume data yet — run a sync to fetch strength set details.")
        else:
            vol_df = pd.DataFrame(vol_rows)
            vol_df["total_volume_lb"] = vol_df["total_volume_kg"] * 2.20462
            vol_df["date"] = pd.to_datetime(vol_df["date"]).dt.date.astype(str)

            vol_chart = (
                alt.Chart(vol_df)
                .mark_bar(color="#4472CA", opacity=0.85)
                .encode(
                    x=alt.X("date:O", title="Date", axis=alt.Axis(labelAngle=-30)),
                    y=alt.Y("total_volume_lb:Q", title="Total Volume (lb)"),
                    tooltip=[
                        alt.Tooltip("date:O", title="Date"),
                        alt.Tooltip("total_volume_lb:Q", format=".0f", title="Volume (lb)"),
                    ],
                )
                .properties(height=240)
            )
            st.altair_chart(vol_chart, width="stretch")
            st.caption("Total volume = sum of (weight × reps) across all sets in the session.")

        st.divider()

        # ── 7c. Strain + Duration per Session ────────────────────────────────
        st.markdown("**Strain & Duration Per Session**")

        strain_rows = [
            {
                "date": w.date,
                "Strain": w.strain,
                "Duration (min)": w.duration_minutes,
            }
            for w in strength_workouts
            if w.strain is not None or w.duration_minutes is not None
        ]

        if not strain_rows:
            st.info("No strain data for strength sessions in this period.")
        else:
            sd_df = pd.DataFrame(strain_rows)
            sd_df["date"] = pd.to_datetime(sd_df["date"]).dt.date.astype(str)

            strain_bar = (
                alt.Chart(sd_df[sd_df["Strain"].notna()])
                .mark_bar(color="#FF7A00", opacity=0.8)
                .encode(
                    x=alt.X("date:O", title="Date", axis=alt.Axis(labelAngle=-30)),
                    y=alt.Y("Strain:Q", title="Strain", scale=alt.Scale(zero=True)),
                    tooltip=[
                        alt.Tooltip("date:O", title="Date"),
                        alt.Tooltip("Strain:Q", format=".1f"),
                    ],
                )
            )

            dur_line = (
                alt.Chart(sd_df[sd_df["Duration (min)"].notna()])
                .mark_line(
                    color="#4472CA",
                    strokeDash=[4, 2],
                    point=alt.OverlayMarkDef(color="#4472CA", size=60),
                )
                .encode(
                    x=alt.X("date:O", title="Date"),
                    y=alt.Y(
                        "Duration (min):Q",
                        title="Duration (min)",
                        scale=alt.Scale(zero=True),
                    ),
                    tooltip=[
                        alt.Tooltip("date:O", title="Date"),
                        alt.Tooltip("Duration (min):Q", format=".0f"),
                    ],
                )
            )

            combined = (
                alt.layer(strain_bar, dur_line)
                .resolve_scale(y="independent")
                .properties(height=260)
            )
            st.altair_chart(combined, width="stretch")
            st.caption(
                "Bars = Whoop strain (left axis) · Dashed line = session duration (right axis)."
            )

    st.divider()

    # ── 8. WORKOUT LOG ────────────────────────────────────────────────────────
    st.subheader("Workout Log")
    st.caption(
        "Click a row to expand full details, HR zone breakdown, exercise sets, and recovery impact."
    )

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
