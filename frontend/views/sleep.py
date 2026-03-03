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
    start_time,
    total_in_bed_ms,
    total_awake_ms,
    total_light_ms,
    total_sws_ms,
    total_rem_ms,
    sleep_performance,
    sleep_efficiency,
    nap
FROM whoop_sleep
WHERE start_time >= :start
  AND start_time <  :end
ORDER BY start_time
"""

_MS_TO_H = 1 / 3_600_000

_STAGE_ORDER = ["Light", "Deep (SWS)", "REM", "Awake"]
_STAGE_COLORS = ["#5B9BD5", "#2E5C8A", "#7030A0", "#C0504D"]



@st.cache_data(ttl=300)
def _load(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY), conn, params={"start": start, "end": end})
    df["start_time"] = pd.to_datetime(df["start_time"])
    df["date"] = df["start_time"].dt.date
    for col, lbl in [
        ("total_light_ms", "light_h"),
        ("total_sws_ms", "sws_h"),
        ("total_rem_ms", "rem_h"),
        ("total_awake_ms", "awake_h"),
    ]:
        df[lbl] = df[col] * _MS_TO_H
    df["total_sleep_h"] = df["light_h"] + df["sws_h"] + df["rem_h"]
    return df


def render(start_date: date, end_date: date) -> None:
    st.title("Sleep")

    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    df = _load(start_date.isoformat(), end_exclusive)

    if df.empty:
        st.warning("No sleep data for the selected date range.")
        return

    main = df[df["nap"] == 0].copy()
    nap_count = len(df[df["nap"] == 1])
    if nap_count:
        st.caption(f"{nap_count} nap(s) excluded from charts below.")

    if main.empty:
        st.warning("No full-night sleep records in range (only naps).")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Avg Sleep", f"{main['total_sleep_h'].mean():.1f} h")
    with col2:
        st.metric("Avg Performance", f"{main['sleep_performance'].mean():.0f}%" if main["sleep_performance"].notna().any() else "—")
    with col3:
        st.metric("Avg Efficiency", f"{main['sleep_efficiency'].mean():.0f}%" if main["sleep_efficiency"].notna().any() else "—")

    st.divider()

    # ── Total sleep per night ──────────────────────────────────────────────
    st.subheader("Total Sleep per Night (hours)")
    total_chart = (
        alt.Chart(main)
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
    stages_melted = main[["date", "light_h", "sws_h", "rem_h", "awake_h"]].melt(
        id_vars="date", var_name="stage", value_name="hours"
    )
    stages_melted["stage"] = stages_melted["stage"].map(
        {"light_h": "Light", "sws_h": "Deep (SWS)", "rem_h": "REM", "awake_h": "Awake"}
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
    perf_df = main.dropna(subset=["sleep_performance"])
    if perf_df.empty:
        st.info("No sleep performance data in range.")
    else:
        perf_chart = (
            alt.Chart(perf_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("sleep_performance:Q", title="Performance %", scale=alt.Scale(domain=[0, 100])),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("sleep_performance:Q", title="Performance %", format=".0f"),
                ],
            )
    
            .properties(height=220)
        )
        st.altair_chart(perf_chart, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)
