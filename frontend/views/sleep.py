"""Sleep page."""

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
    date,
    total_sleep_minutes,
    deep_sleep_minutes,
    light_sleep_minutes,
    rem_sleep_minutes,
    awake_minutes,
    whoop_performance,
    whoop_efficiency,
    garmin_sleep_score,
    primary_source
FROM unified_sleep
WHERE date >= :start AND date < :end
ORDER BY date
"""

_STAGE_ORDER = ["Light", "Deep (SWS)", "REM", "Awake"]
_STAGE_COLORS = ["#5B9BD5", "#2E5C8A", "#7030A0", "#C0504D"]


@st.cache_data(ttl=300)
def _load(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY), conn, params={"start": start, "end": end})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["light_h"] = df["light_sleep_minutes"] / 60
    df["deep_h"] = df["deep_sleep_minutes"] / 60
    df["rem_h"] = df["rem_sleep_minutes"] / 60
    df["awake_h"] = df["awake_minutes"] / 60
    df["total_sleep_h"] = df["light_h"] + df["deep_h"] + df["rem_h"]
    return df


def render(start_date: date, end_date: date) -> None:
    st.title("Sleep")

    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    df = _load(start_date.isoformat(), end_exclusive)

    if df.empty:
        st.warning("No sleep data for the selected date range.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Avg Sleep", f"{df['total_sleep_h'].mean():.1f} h")
    with col2:
        st.metric(
            "Avg Performance",
            f"{df['whoop_performance'].mean():.0f}%"
            if df["whoop_performance"].notna().any()
            else "—",
        )
    with col3:
        st.metric(
            "Avg Efficiency",
            f"{df['whoop_efficiency'].mean():.0f}%"
            if df["whoop_efficiency"].notna().any()
            else "—",
        )
    with col4:
        st.metric(
            "Avg Garmin Score",
            f"{df['garmin_sleep_score'].mean():.0f}"
            if df["garmin_sleep_score"].notna().any()
            else "—",
        )

    st.divider()

    # ── Total sleep per night ──────────────────────────────────────────────
    st.subheader("Total Sleep per Night (hours)")
    total_chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
            y=alt.Y("total_sleep_h:Q", title="Hours", scale=alt.Scale(domainMin=0)),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%b %d"),
                alt.Tooltip("total_sleep_h:Q", title="Sleep (h)", format=".2f"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(total_chart, use_container_width=True)

    # ── Sleep stage breakdown — stacked bar ───────────────────────────────
    st.subheader("Sleep Stage Breakdown (hours)")
    stages_melted = df[["date", "light_h", "deep_h", "rem_h", "awake_h"]].melt(
        id_vars="date", var_name="stage", value_name="hours"
    )
    stages_melted["stage"] = stages_melted["stage"].map(
        {"light_h": "Light", "deep_h": "Deep (SWS)", "rem_h": "REM", "awake_h": "Awake"}
    )
    stacked_chart = (
        alt.Chart(stages_melted)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
            y=alt.Y("hours:Q", title="Hours", stack="zero", scale=alt.Scale(domainMin=0)),
            color=alt.Color(
                "stage:N",
                title="Stage",
                scale=alt.Scale(domain=_STAGE_ORDER, range=_STAGE_COLORS),
                sort=_STAGE_ORDER,
            ),
            order=alt.Order("stage:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%b %d"),
                alt.Tooltip("stage:N", title="Stage"),
                alt.Tooltip("hours:Q", title="Hours", format=".2f"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(stacked_chart, use_container_width=True)

    # ── Sleep performance trend ────────────────────────────────────────────
    st.subheader("Sleep Performance %")
    perf_df = df.dropna(subset=["whoop_performance"])
    if perf_df.empty:
        st.info("No sleep performance data in range.")
    else:
        perf_chart = (
            alt.Chart(perf_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y(
                    "whoop_performance:Q",
                    title="Performance %",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("whoop_performance:Q", title="Performance %", format=".0f"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(perf_chart, use_container_width=True)

    # ── Garmin Sleep Score ─────────────────────────────────────────────────
    st.subheader("Garmin Sleep Score")
    gs_df = df.dropna(subset=["garmin_sleep_score"])
    if gs_df.empty:
        st.info("No Garmin sleep score data (watch not worn during sleep).")
    else:
        gs_chart = (
            alt.Chart(gs_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y(
                    "garmin_sleep_score:Q", title="Score", scale=alt.Scale(domain=[0, 100])
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("garmin_sleep_score:Q", title="Score", format=".0f"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(gs_chart, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)
