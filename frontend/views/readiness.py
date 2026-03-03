"""Recovery / Readiness page."""
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
    c.start_time                AS cycle_date,
    r.recovery_score,
    r.hrv_rmssd,
    r.resting_heart_rate,
    r.spo2_pct,
    r.skin_temp_celsius,
    s.respiratory_rate
FROM whoop_recovery r
JOIN whoop_cycles c ON r.cycle_id = c.id
LEFT JOIN whoop_sleep s ON r.sleep_id = s.id
WHERE c.start_time >= :start
  AND c.start_time <  :end
  AND r.recovery_score IS NOT NULL
ORDER BY c.start_time
"""

# Human-readable labels for overlay chart
_METRIC_LABELS = {
    "recovery_score":   "Recovery Score",
    "hrv_rmssd":        "HRV",
    "resting_heart_rate": "Resting HR",
    "spo2_pct":         "SpO2",
    "respiratory_rate": "Breathing Rate",
    "skin_temp_f":      "Skin Temp",
}


def _line(df: pd.DataFrame, x: str, y: str, y_title: str, domain: list | None = None) -> alt.Chart:
    scale = alt.Scale(domainMin=0) if domain is None else alt.Scale(domain=domain)
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%b %d")),
            y=alt.Y(f"{y}:Q", title=y_title, scale=scale),
            tooltip=[
                alt.Tooltip(f"{x}:T", title="Date", format="%b %d"),
                alt.Tooltip(f"{y}:Q", title=y_title, format=".1f"),
            ],
        )

        .properties(height=220)
    )


@st.cache_data(ttl=300)
def _load(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY), conn, params={"start": start, "end": end})
    df["cycle_date"] = pd.to_datetime(df["cycle_date"]).dt.date
    df["skin_temp_f"] = df["skin_temp_celsius"] * 9 / 5 + 32
    return df


def render(start_date: date, end_date: date) -> None:
    st.title("Recovery")

    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    df = _load(start_date.isoformat(), end_exclusive)

    if df.empty:
        st.warning("No recovery data for the selected date range.")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None

    def _delta(field: str, invert: bool = False) -> tuple[str | None, str]:
        if prev is None or pd.isna(latest[field]) or pd.isna(prev[field]):
            return None, "normal"
        d = round(latest[field] - prev[field], 1)
        return f"{d:+.1f}", "inverse" if invert else "normal"

    # ── Top metrics: two rows of three ────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        d, _ = _delta("recovery_score")
        st.metric("Recovery Score", f"{latest['recovery_score']:.0f}%", delta=f"{d}%" if d else None)
    with col2:
        d, _ = _delta("hrv_rmssd")
        st.metric("HRV", f"{latest['hrv_rmssd']:.1f} ms" if pd.notna(latest["hrv_rmssd"]) else "—", delta=d)
    with col3:
        d, color = _delta("resting_heart_rate", invert=True)
        st.metric("Resting HR", f"{latest['resting_heart_rate']:.0f} bpm" if pd.notna(latest["resting_heart_rate"]) else "—", delta=d, delta_color=color)

    col4, col5, col6 = st.columns(3)
    with col4:
        d, _ = _delta("spo2_pct")
        st.metric("SpO2", f"{latest['spo2_pct']:.1f}%" if pd.notna(latest["spo2_pct"]) else "—", delta=d)
    with col5:
        d, _ = _delta("respiratory_rate")
        st.metric("Breathing Rate", f"{latest['respiratory_rate']:.1f} rpm" if pd.notna(latest["respiratory_rate"]) else "—", delta=d)
    with col6:
        d, _ = _delta("skin_temp_f")
        st.metric("Skin Temp", f"{latest['skin_temp_f']:.1f} °F" if pd.notna(latest["skin_temp_f"]) else "—", delta=d)

    st.divider()

    # ── Individual charts ─────────────────────────────────────────────────
    st.subheader("Recovery Score")
    st.altair_chart(_line(df, "cycle_date", "recovery_score", "Recovery %", domain=[0, 100]), use_container_width=True)

    st.subheader("HRV (RMSSD)")
    hrv_df = df.dropna(subset=["hrv_rmssd"])
    if not hrv_df.empty:
        st.altair_chart(_line(hrv_df, "cycle_date", "hrv_rmssd", "HRV (ms)"), use_container_width=True)

    st.subheader("Resting Heart Rate")
    rhr_df = df.dropna(subset=["resting_heart_rate"])
    if not rhr_df.empty:
        st.altair_chart(_line(rhr_df, "cycle_date", "resting_heart_rate", "RHR (bpm)"), use_container_width=True)

    st.subheader("SpO2")
    spo2_df = df.dropna(subset=["spo2_pct"])
    if not spo2_df.empty:
        st.altair_chart(_line(spo2_df, "cycle_date", "spo2_pct", "SpO2 %"), use_container_width=True)

    st.subheader("Breathing Rate")
    br_df = df.dropna(subset=["respiratory_rate"])
    if not br_df.empty:
        st.altair_chart(_line(br_df, "cycle_date", "respiratory_rate", "Breaths / min"), use_container_width=True)

    st.subheader("Skin Temperature")
    temp_df = df.dropna(subset=["skin_temp_f"])
    if not temp_df.empty:
        st.altair_chart(_line(temp_df, "cycle_date", "skin_temp_f", "Skin Temp (°F)"), use_container_width=True)

    st.divider()

    # ── Overlay: all metrics on their own scale ────────────────────────────
    st.subheader("All Metrics Overlaid")
    st.caption("Hover a day to see all readings. Each metric on its own scale — Y axis intentionally unlabelled.")

    overlay_cols = list(_METRIC_LABELS.keys())
    valid_cols = [c for c in overlay_cols if df[c].notna().any()]

    if not valid_cols:
        st.info("Not enough data to render overlay for the selected range.")
    else:
        # Wide format: one row per date, one column per metric (for tooltip)
        label_map = {col: _METRIC_LABELS[col] for col in valid_cols}
        wide = df[["cycle_date"] + valid_cols].rename(columns=label_map)
        label_cols = list(label_map.values())

        # Melted format: one row per (date, metric) — used for drawing colored lines
        melted = wide.melt(id_vars="cycle_date", var_name="metric", value_name="value")
        melted = melted.dropna(subset=["value"])

        # Lines: raw values, Y axis shape kept but numbers hidden
        lines = (
            alt.Chart(melted)
            .mark_line(point=True)
            .encode(
                x=alt.X("cycle_date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y(
                    "value:Q",
                    title=None,
                    axis=alt.Axis(labels=False, ticks=False, domain=False, grid=False),
                ),
                color=alt.Color("metric:N", title="Metric"),
            )
    
            .properties(height=320)
        )

        # Invisible full-height rules at each date — fire a tooltip with every metric
        tooltip = [alt.Tooltip("cycle_date:T", title="Date", format="%b %d")] + [
            alt.Tooltip(f"{lbl}:Q", title=lbl, format=".1f") for lbl in label_cols
        ]
        hover = (
            alt.Chart(wide)
            .mark_rule(opacity=0, strokeWidth=20)
            .encode(
                x=alt.X("cycle_date:T"),
                tooltip=tooltip,
            )
        )

        st.altair_chart(lines + hover, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)
