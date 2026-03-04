"""Recovery / Readiness page."""

import json
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
    whoop_recovery_score,
    whoop_hrv_rmssd,
    whoop_rhr,
    whoop_spo2,
    whoop_skin_temp,
    whoop_respiratory_rate,
    garmin_body_battery_high,
    garmin_body_battery_low,
    garmin_avg_stress,
    data_sources
FROM unified_daily
WHERE date >= :start AND date < :end
  AND (whoop_recovery_score IS NOT NULL OR garmin_body_battery_high IS NOT NULL)
ORDER BY date
"""

# Human-readable labels for overlay chart
_METRIC_LABELS = {
    "whoop_recovery_score": "Recovery Score",
    "whoop_hrv_rmssd": "HRV",
    "whoop_rhr": "Resting HR",
    "whoop_spo2": "SpO2",
    "whoop_respiratory_rate": "Breathing Rate",
    "skin_temp_f": "Skin Temp",
    "garmin_body_battery_high": "Body Battery",
    "garmin_avg_stress": "Stress",
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
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["skin_temp_f"] = df["whoop_skin_temp"] * 9 / 5 + 32
    df["sources"] = df["data_sources"].apply(lambda x: json.loads(x) if x else [])
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
        d, _ = _delta("whoop_recovery_score")
        st.metric(
            "Recovery Score",
            f"{latest['whoop_recovery_score']:.0f}%"
            if pd.notna(latest["whoop_recovery_score"])
            else "—",
            delta=f"{d}%" if d else None,
        )
    with col2:
        d, _ = _delta("whoop_hrv_rmssd")
        st.metric(
            "HRV",
            f"{latest['whoop_hrv_rmssd']:.1f} ms" if pd.notna(latest["whoop_hrv_rmssd"]) else "—",
            delta=d,
        )
    with col3:
        d, color = _delta("whoop_rhr", invert=True)
        st.metric(
            "Resting HR",
            f"{latest['whoop_rhr']:.0f} bpm" if pd.notna(latest["whoop_rhr"]) else "—",
            delta=d,
            delta_color=color,
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        d, _ = _delta("whoop_spo2")
        st.metric(
            "SpO2",
            f"{latest['whoop_spo2']:.1f}%" if pd.notna(latest["whoop_spo2"]) else "—",
            delta=d,
        )
    with col5:
        d, _ = _delta("whoop_respiratory_rate")
        st.metric(
            "Breathing Rate",
            f"{latest['whoop_respiratory_rate']:.1f} rpm"
            if pd.notna(latest["whoop_respiratory_rate"])
            else "—",
            delta=d,
        )
    with col6:
        d, _ = _delta("skin_temp_f")
        st.metric(
            "Skin Temp",
            f"{latest['skin_temp_f']:.1f} °F" if pd.notna(latest["skin_temp_f"]) else "—",
            delta=d,
        )

    sources = latest.get("sources", [])
    label = " · ".join(s.capitalize() for s in sources) if sources else "Unknown"
    st.caption(f"Latest day data sources: **{label}**")

    st.divider()

    # ── Individual charts ─────────────────────────────────────────────────
    st.subheader("Recovery Score")
    st.altair_chart(
        _line(df, "date", "whoop_recovery_score", "Recovery %", domain=[0, 100]),
        use_container_width=True,
    )

    st.subheader("HRV (RMSSD)")
    hrv_df = df.dropna(subset=["whoop_hrv_rmssd"])
    if not hrv_df.empty:
        st.altair_chart(
            _line(hrv_df, "date", "whoop_hrv_rmssd", "HRV (ms)"), use_container_width=True
        )

    st.subheader("Resting Heart Rate")
    rhr_df = df.dropna(subset=["whoop_rhr"])
    if not rhr_df.empty:
        st.altair_chart(
            _line(rhr_df, "date", "whoop_rhr", "RHR (bpm)"), use_container_width=True
        )

    st.subheader("SpO2")
    spo2_df = df.dropna(subset=["whoop_spo2"])
    if not spo2_df.empty:
        st.altair_chart(
            _line(spo2_df, "date", "whoop_spo2", "SpO2 %"), use_container_width=True
        )

    st.subheader("Breathing Rate")
    br_df = df.dropna(subset=["whoop_respiratory_rate"])
    if not br_df.empty:
        st.altair_chart(
            _line(br_df, "date", "whoop_respiratory_rate", "Breaths / min"),
            use_container_width=True,
        )

    st.subheader("Skin Temperature")
    temp_df = df.dropna(subset=["skin_temp_f"])
    if not temp_df.empty:
        st.altair_chart(
            _line(temp_df, "date", "skin_temp_f", "Skin Temp (°F)"), use_container_width=True
        )

    # ── Body Battery (Garmin) ──────────────────────────────────────────────
    st.subheader("Body Battery (Garmin)")
    bb_df = df.dropna(subset=["garmin_body_battery_high"])
    if bb_df.empty:
        st.info("No body battery data in range.")
    else:
        bb = bb_df[["date", "garmin_body_battery_high", "garmin_body_battery_low"]].melt(
            id_vars="date", var_name="metric", value_name="value"
        )
        bb["metric"] = bb["metric"].map(
            {"garmin_body_battery_high": "High", "garmin_body_battery_low": "Low"}
        )
        bb_chart = (
            alt.Chart(bb)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("value:Q", title="Body Battery", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("metric:N", title="Level"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("metric:N", title="Level"),
                    alt.Tooltip("value:Q", title="Value", format=".0f"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(bb_chart, use_container_width=True)

    # ── Stress Level (Garmin) ──────────────────────────────────────────────
    st.subheader("Stress Level (Garmin)")
    stress_df = df.dropna(subset=["garmin_avg_stress"])
    if stress_df.empty:
        st.info("No stress data in range.")
    else:
        st.altair_chart(
            _line(stress_df, "date", "garmin_avg_stress", "Stress"), use_container_width=True
        )

    st.divider()

    # ── Overlay: all metrics on their own scale ────────────────────────────
    st.subheader("All Metrics Overlaid")
    st.caption(
        "Hover a day to see all readings. Each metric on its own scale — Y axis intentionally unlabelled."
    )

    overlay_cols = list(_METRIC_LABELS.keys())
    valid_cols = [c for c in overlay_cols if c in df.columns and df[c].notna().any()]

    if not valid_cols:
        st.info("Not enough data to render overlay for the selected range.")
    else:
        label_map = {col: _METRIC_LABELS[col] for col in valid_cols}
        wide = df[["date"] + valid_cols].rename(columns=label_map)
        label_cols = list(label_map.values())

        melted = wide.melt(id_vars="date", var_name="metric", value_name="value")
        melted = melted.dropna(subset=["value"])

        lines = (
            alt.Chart(melted)
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y(
                    "value:Q",
                    title=None,
                    axis=alt.Axis(labels=False, ticks=False, domain=False, grid=False),
                ),
                color=alt.Color("metric:N", title="Metric"),
            )
            .properties(height=320)
        )

        tooltip = [alt.Tooltip("date:T", title="Date", format="%b %d")] + [
            alt.Tooltip(f"{lbl}:Q", title=lbl, format=".1f") for lbl in label_cols
        ]
        hover = (
            alt.Chart(wide)
            .mark_rule(opacity=0, strokeWidth=20)
            .encode(
                x=alt.X("date:T"),
                tooltip=tooltip,
            )
        )

        st.altair_chart(lines + hover, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)
