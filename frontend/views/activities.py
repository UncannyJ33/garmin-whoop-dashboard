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

_QUERY = """
SELECT
    start_time,
    end_time,
    sport_name,
    strain,
    avg_heart_rate,
    max_heart_rate,
    kilojoules,
    distance_meter,
    score_state
FROM whoop_workouts
WHERE start_time >= :start
  AND start_time <  :end
ORDER BY start_time DESC
"""


def _category_bar(counts: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("sport_name:N", title=None, sort="-y"),
            y=alt.Y("count:Q", title="Count", scale=alt.Scale(domainMin=0)),
            tooltip=[
                alt.Tooltip("sport_name:N", title="Activity"),
                alt.Tooltip("count:Q", title="Count"),
            ],
        )
        .properties(height=220)
    )


@st.cache_data(ttl=300)
def _load(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY), conn, params={"start": start, "end": end})
    df["start_time"] = pd.to_datetime(df["start_time"])
    df["end_time"] = pd.to_datetime(df["end_time"])
    df["date"] = df["start_time"].dt.date
    df["duration_min"] = (
        ((df["end_time"] - df["start_time"]).dt.total_seconds() / 60).round(0).astype("Int64")
    )
    return df


def render(start_date: date, end_date: date) -> None:
    st.title("Activities")

    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    df = _load(start_date.isoformat(), end_exclusive)

    if df.empty:
        st.warning("No activity data for the selected date range.")
        return

    strain_df = df[df["strain"].notna()].sort_values("date")
    recovery_df = df[df["strain"].isna()]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Strain Activities", len(strain_df))
    with col2:
        st.metric("Recovery Activities", len(recovery_df))
    with col3:
        avg_strain = strain_df["strain"].mean()
        st.metric("Avg Strain", f"{avg_strain:.1f}" if pd.notna(avg_strain) else "—")
    with col4:
        avg_hr = strain_df["avg_heart_rate"].mean()
        st.metric("Avg HR (strain)", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "—")

    st.divider()

    # ── Strain over time: one point per day (peak strain) ─────────────────
    st.subheader("Strain over Time")
    if strain_df.empty:
        st.info("No strain activities in range.")
    else:
        # Peak strain per day
        daily_peak = strain_df.groupby("date")["strain"].max().reset_index()

        # Sport name that achieved the peak
        top_sport = strain_df.loc[
            strain_df.groupby("date")["strain"].idxmax(), ["date", "sport_name"]
        ].reset_index(drop=True)

        # All activities for the day as a readable string, sorted by strain desc
        def _day_summary(g: pd.DataFrame) -> str:
            return ", ".join(
                f"{row['sport_name']} ({row['strain']:.1f})"
                for _, row in g.sort_values("strain", ascending=False).iterrows()
            )

        all_activities = (
            strain_df.groupby("date")[["sport_name", "strain"]]
            .apply(_day_summary)
            .reset_index(name="all_activities")
        )

        daily = daily_peak.merge(top_sport, on="date").merge(all_activities, on="date")

        strain_chart = (
            alt.Chart(daily)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("strain:Q", title="Peak Strain", scale=alt.Scale(domainMin=0)),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("strain:Q", title="Peak Strain", format=".1f"),
                    alt.Tooltip("sport_name:N", title="Top Activity"),
                    alt.Tooltip("all_activities:N", title="All Activities"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(strain_chart, use_container_width=True)

    # ── Strain Activity Categories ─────────────────────────────────────────
    st.subheader("Strain Activity Categories")
    if strain_df.empty:
        st.info("No strain activities in range.")
    else:
        strain_counts = (
            strain_df["sport_name"]
            .value_counts()
            .rename_axis("sport_name")
            .reset_index(name="count")
        )
        st.altair_chart(_category_bar(strain_counts), use_container_width=True)

    # ── Recovery Activity Categories ───────────────────────────────────────
    st.subheader("Recovery Activity Categories")
    if recovery_df.empty:
        st.info("No recovery activities in range.")
    else:
        recovery_counts = (
            recovery_df["sport_name"]
            .value_counts()
            .rename_axis("sport_name")
            .reset_index(name="count")
        )
        st.altair_chart(_category_bar(recovery_counts), use_container_width=True)

    # ── Recent workouts table (strain activities) ──────────────────────────
    st.subheader("Recent Workouts")
    workouts_display = (
        strain_df[["date", "sport_name", "strain", "avg_heart_rate", "duration_min"]]
        .rename(
            columns={
                "date": "Date",
                "sport_name": "Activity",
                "strain": "Strain",
                "avg_heart_rate": "Avg HR",
                "duration_min": "Duration (min)",
            }
        )
        .reset_index(drop=True)
    )
    st.dataframe(workouts_display, use_container_width=True)

    # ── Recent recoveries table (recovery activities) ──────────────────────
    st.subheader("Recent Recoveries")
    recoveries_display = (
        recovery_df[["date", "sport_name", "duration_min"]]
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
