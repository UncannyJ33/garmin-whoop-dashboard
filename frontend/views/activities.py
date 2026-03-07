"""Activities page."""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

from frontend.db import get_engine

_QUERY_WORKOUTS = """
SELECT
    date, start_time, activity_type, duration_minutes,
    whoop_strain, whoop_avg_hr, whoop_calories_kj,
    garmin_distance_m, garmin_avg_pace, garmin_elevation_gain,
    garmin_avg_cadence, garmin_training_effect,
    garmin_avg_ground_contact, garmin_avg_vertical_osc, garmin_avg_stride_length,
    matched, primary_source
FROM unified_workouts
WHERE date >= :start AND date < :end
ORDER BY date DESC, start_time DESC
"""

_QUERY_RECOVERIES = """
SELECT start_time, end_time, sport_name
FROM whoop_workouts
WHERE start_time >= :start AND start_time < :end AND strain IS NULL
ORDER BY start_time DESC
"""


def _category_bar(counts: pd.DataFrame, col: str) -> alt.Chart:
    return (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X(f"{col}:N", title=None, sort="-y"),
            y=alt.Y("count:Q", title="Count", scale=alt.Scale(domainMin=0)),
            tooltip=[
                alt.Tooltip(f"{col}:N", title="Activity"),
                alt.Tooltip("count:Q", title="Count"),
            ],
        )
        .properties(height=220)
    )


@st.cache_data(ttl=300)
def _load_workouts(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY_WORKOUTS), conn, params={"start": start, "end": end})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["matched_label"] = df.apply(
        lambda r: (
            "Both"
            if r["matched"]
            else r["primary_source"].capitalize()
            if pd.notna(r["primary_source"])
            else "Unknown"
        ),
        axis=1,
    )
    return df


@st.cache_data(ttl=300)
def _load_recoveries(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY_RECOVERIES), conn, params={"start": start, "end": end})
    df["start_time"] = pd.to_datetime(df["start_time"])
    df["end_time"] = pd.to_datetime(df["end_time"])
    df["date"] = df["start_time"].dt.date
    df["duration_min"] = (
        ((df["end_time"] - df["start_time"]).dt.total_seconds() / 60).round(0).astype("Int64")
    )
    return df


def render(start_date: date, end_date: date) -> None:
    st.title("Activities")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load activity data. This may be a temporary database issue. "
            f"Details: `{exc}`"
        )


def _render_body(start_date: date, end_date: date) -> None:
    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    wdf = _load_workouts(start_date.isoformat(), end_exclusive)
    rdf = _load_recoveries(start_date.isoformat(), end_exclusive)

    if wdf.empty and rdf.empty:
        st.warning("No activity data for the selected date range.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Strain Activities", len(wdf))
    with col2:
        st.metric("Recovery Activities", len(rdf))
    with col3:
        avg_strain = wdf["whoop_strain"].mean()
        st.metric("Avg Strain", f"{avg_strain:.1f}" if pd.notna(avg_strain) else "—")
    with col4:
        avg_hr = wdf["whoop_avg_hr"].mean()
        st.metric("Avg HR (strain)", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "—")

    st.divider()

    # ── Strain over time: one point per day (peak strain) ─────────────────
    st.subheader("Strain over Time")
    if wdf.empty:
        st.info("No strain activities in range.")
    else:
        strain_sorted = wdf.sort_values("date")
        daily_peak = strain_sorted.groupby("date")["whoop_strain"].max().reset_index()

        top_activity = strain_sorted.loc[
            strain_sorted.groupby("date")["whoop_strain"].idxmax(), ["date", "activity_type"]
        ].reset_index(drop=True)

        def _day_summary(g: pd.DataFrame) -> str:
            return ", ".join(
                f"{row['activity_type']} ({row['whoop_strain']:.1f})"
                for _, row in g.sort_values("whoop_strain", ascending=False).iterrows()
                if pd.notna(row["whoop_strain"])
            )

        all_activities = (
            strain_sorted.groupby("date")[["activity_type", "whoop_strain"]]
            .apply(_day_summary)
            .reset_index(name="all_activities")
        )

        daily = daily_peak.merge(top_activity, on="date").merge(all_activities, on="date")

        strain_chart = (
            alt.Chart(daily)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("whoop_strain:Q", title="Peak Strain", scale=alt.Scale(domainMin=0)),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("whoop_strain:Q", title="Peak Strain", format=".1f"),
                    alt.Tooltip("activity_type:N", title="Top Activity"),
                    alt.Tooltip("all_activities:N", title="All Activities"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(strain_chart, use_container_width=True)

    # ── Strain Activity Categories ─────────────────────────────────────────
    st.subheader("Strain Activity Categories")
    if wdf.empty:
        st.info("No strain activities in range.")
    else:
        strain_counts = (
            wdf["activity_type"]
            .value_counts()
            .rename_axis("activity_type")
            .reset_index(name="count")
        )
        st.altair_chart(_category_bar(strain_counts, "activity_type"), use_container_width=True)

    # ── Recent Workouts table ──────────────────────────────────────────────
    st.subheader("Recent Workouts")
    if not wdf.empty:
        display_cols = {
            "date": "Date",
            "activity_type": "Activity",
            "whoop_strain": "Strain",
            "garmin_training_effect": "Training Effect",
            "whoop_avg_hr": "Avg HR",
            "duration_minutes": "Duration (min)",
            "matched_label": "Sources",
        }
        workouts_display = (
            wdf[[c for c in display_cols if c in wdf.columns]]
            .rename(columns=display_cols)
            .reset_index(drop=True)
        )
        st.dataframe(workouts_display, use_container_width=True)

    # ── Running Data ───────────────────────────────────────────────────────
    st.subheader("Running Data (Garmin)")
    rd_df = wdf[wdf["activity_type"].str.contains("run", case=False, na=False)]
    if rd_df.empty:
        st.info("No running data in range.")
    else:
        rd_cols = {
            "date": "Date",
            "activity_type": "Activity",
            "duration_minutes": "Duration (min)",
            "garmin_distance_m": "Distance (m)",
            "garmin_avg_pace": "Pace (min/km)",
            "garmin_elevation_gain": "Elevation (m)",
            "whoop_avg_hr": "Avg HR",
            "garmin_training_effect": "Training Effect",
            "whoop_strain": "Strain",
            "garmin_avg_cadence": "Cadence (spm)",
            "garmin_avg_ground_contact": "Ground Contact (ms)",
            "garmin_avg_vertical_osc": "Vert Osc (cm)",
            "garmin_avg_stride_length": "Stride Length (m)",
            "matched_label": "Sources",
        }
        st.dataframe(
            rd_df[[c for c in rd_cols if c in rd_df.columns]]
            .rename(columns=rd_cols)
            .reset_index(drop=True),
            use_container_width=True,
        )

    # ── Recovery Activity Categories ───────────────────────────────────────
    st.subheader("Recovery Activity Categories")
    if rdf.empty:
        st.info("No recovery activities in range.")
    else:
        recovery_counts = (
            rdf["sport_name"].value_counts().rename_axis("sport_name").reset_index(name="count")
        )
        st.altair_chart(_category_bar(recovery_counts, "sport_name"), use_container_width=True)

    # ── Recent recoveries table ────────────────────────────────────────────
    st.subheader("Recent Recoveries")
    if not rdf.empty:
        recoveries_display = (
            rdf[["date", "sport_name", "duration_min"]]
            .rename(
                columns={
                    "date": "Date",
                    "sport_name": "Activity",
                    "duration_min": "Duration (min)",
                }
            )
            .reset_index(drop=True)
        )
        st.dataframe(recoveries_display, use_container_width=True)
