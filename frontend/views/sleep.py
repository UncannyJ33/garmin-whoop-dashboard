"""Sleep impact analysis view — nightly sleep with training context.

Sections:
  1. Last night's sleep hero — total hours, stage bar, performance, debt
  2. Sleep trends — bar + 7d rolling avg + deep sleep + anomaly flags
  3. Sleep stage distribution — stacked area chart
  4. Sleep consistency — avg bedtime/wake, variability, debt trend
  5. Training ↔ sleep connections — Pearson correlations with narratives
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from frontend.db import get_engine  # noqa: E402
from src.analytics.sleep_analysis import (  # noqa: E402
    SleepInsight,
    get_sleep_consistency,
    get_sleep_insights,
    get_strain_sleep_correlation,
)
from src.analytics.trends import detect_anomalies  # noqa: E402

_STAGE_ORDER = ["Light", "Deep", "REM", "Awake"]
_STAGE_COLORS = ["#5B9BD5", "#2E5C8A", "#7030A0", "#C0504D"]


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_insights(start: str, end: str) -> list[SleepInsight]:
    return get_sleep_insights(get_engine(), date.fromisoformat(start), date.fromisoformat(end))


@st.cache_data(ttl=300)
def _load_correlation(days: int, end: str) -> dict:
    return get_strain_sleep_correlation(get_engine(), days=days, end_date=date.fromisoformat(end))


@st.cache_data(ttl=300)
def _load_consistency(days: int, end: str) -> dict:
    return get_sleep_consistency(get_engine(), days=days, end_date=date.fromisoformat(end))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_time(hours: float | None) -> str:
    """Format fractional hours as HH:MM (handles values ≥ 24)."""
    if hours is None:
        return "—"
    h = int(hours) % 24
    m = round((hours % 1) * 60)
    return f"{h:02d}:{m:02d}"


def _fmt_dur(mins: float | None) -> str:
    if mins is None:
        return "—"
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m"


def _rolling_avg(values: list[float | None], window: int = 7) -> list[float | None]:
    result = []
    for i in range(len(values)):
        chunk = [v for v in values[max(0, i - window + 1) : i + 1] if v is not None]
        result.append(sum(chunk) / len(chunk) if chunk else None)
    return result


def _corr_narrative(key: str, corr: dict) -> str:
    sub = corr[key]
    if not sub["sufficient_data"]:
        return sub.get("message", "Insufficient data.")
    r = sub["r"]
    if r is None:
        return "No correlation calculable (zero variance in data)."
    strength = "strong" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak"
    direction = "positive" if r >= 0 else "negative"
    label_map = {
        "strain_vs_total_sleep": "prior-day training strain and total sleep duration",
        "strain_vs_deep_sleep": "prior-day training strain and deep (SWS) sleep",
        "strain_vs_next_day_recovery": "prior-day strain and next-day Whoop recovery",
    }
    return (
        f"r = {r:+.2f} ({strength} {direction}) — {label_map[key]}. n = {sub['n']} paired nights."
    )


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render(start_date: date, end_date: date) -> None:
    st.title("Sleep")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load sleep data. This may be a temporary database issue. Details: `{exc}`"
        )


def _render_body(start_date: date, end_date: date) -> None:
    insights = _load_insights(start_date.isoformat(), end_date.isoformat())

    if not insights:
        st.warning("No sleep data for the selected date range.")
        return

    n_days = (end_date - start_date).days + 1

    # ── 1. LAST NIGHT'S SLEEP ─────────────────────────────────────────────
    last = insights[-1]
    st.subheader(f"Last Night — {last.date}")

    h1, h2, h3, h4 = st.columns(4)
    with h1:
        hours = last.total_sleep_minutes / 60 if last.total_sleep_minutes is not None else None
        st.metric("Total Sleep", f"{hours:.1f} h" if hours is not None else "—")
    with h2:
        st.metric(
            "Performance",
            f"{last.sleep_performance:.0f}%" if last.sleep_performance is not None else "—",
        )
    with h3:
        st.metric(
            "Efficiency",
            f"{last.sleep_efficiency:.0f}%" if last.sleep_efficiency is not None else "—",
        )
    with h4:
        debt = last.sleep_debt_estimate
        if debt is not None:
            debt_h = abs(debt) / 60
            label = f"{debt_h:.1f} h {'deficit' if debt < 0 else 'surplus'}"
        else:
            label = "—"
        st.metric("7d Sleep Debt", label)

    # Stage breakdown horizontal stacked bar
    stage_data = [
        ("Light", last.light_minutes),
        ("Deep", last.deep_minutes),
        ("REM", last.rem_minutes),
        ("Awake", last.awake_minutes),
    ]
    stage_rows = [
        {"Stage": name, "Hours": mins / 60, "order": i}
        for i, (name, mins) in enumerate(stage_data)
        if mins is not None
    ]
    if stage_rows:
        sdf = pd.DataFrame(stage_rows)
        stage_bar = (
            alt.Chart(sdf)
            .mark_bar()
            .encode(
                x=alt.X(
                    "sum(Hours):Q",
                    stack="zero",
                    title="Hours",
                    axis=alt.Axis(grid=False),
                ),
                color=alt.Color(
                    "Stage:N",
                    scale=alt.Scale(domain=_STAGE_ORDER, range=_STAGE_COLORS),
                    sort=_STAGE_ORDER,
                    legend=alt.Legend(orient="bottom", columns=4),
                ),
                order=alt.Order("order:Q"),
                tooltip=[
                    alt.Tooltip("Stage:N"),
                    alt.Tooltip("Hours:Q", format=".2f"),
                ],
            )
            .properties(height=50)
        )
        st.altair_chart(stage_bar, use_container_width=True)

    st.divider()

    # ── 2. SLEEP TRENDS ───────────────────────────────────────────────────
    st.subheader("Sleep Trends")

    trend_df = pd.DataFrame(
        [
            {
                "Date": i.date,
                "Total Sleep (h)": i.total_sleep_minutes / 60
                if i.total_sleep_minutes is not None
                else None,
                "Deep Sleep (h)": i.deep_minutes / 60 if i.deep_minutes is not None else None,
            }
            for i in insights
        ]
    )

    raw_values = trend_df["Total Sleep (h)"].tolist()
    raw_dates = trend_df["Date"].tolist()
    trend_df["Rolling 7d Avg (h)"] = _rolling_avg(raw_values)

    anomalies = detect_anomalies(raw_values, raw_dates)

    bars = (
        alt.Chart(trend_df)
        .mark_bar(color="#5B9BD5", opacity=0.7)
        .encode(
            x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %d")),
            y=alt.Y("Total Sleep (h):Q", title="Hours", scale=alt.Scale(domainMin=0)),
            tooltip=[
                alt.Tooltip("Date:T", title="Date", format="%b %d"),
                alt.Tooltip("Total Sleep (h):Q", title="Total Sleep (h)", format=".1f"),
            ],
        )
    )
    rolling_line = (
        alt.Chart(trend_df.dropna(subset=["Rolling 7d Avg (h)"]))
        .mark_line(color="#FF8C00", strokeWidth=2)
        .encode(
            x=alt.X("Date:T"),
            y=alt.Y("Rolling 7d Avg (h):Q"),
            tooltip=[
                alt.Tooltip("Date:T", format="%b %d"),
                alt.Tooltip("Rolling 7d Avg (h):Q", format=".1f"),
            ],
        )
    )
    deep_line = (
        alt.Chart(trend_df.dropna(subset=["Deep Sleep (h)"]))
        .mark_line(color="#2E5C8A", strokeDash=[4, 2])
        .encode(
            x=alt.X("Date:T"),
            y=alt.Y("Deep Sleep (h):Q"),
            tooltip=[
                alt.Tooltip("Date:T", format="%b %d"),
                alt.Tooltip("Deep Sleep (h):Q", format=".1f"),
            ],
        )
    )

    layers = [bars, rolling_line, deep_line]

    if anomalies:
        anom_df = pd.DataFrame(anomalies).rename(
            columns={"date": "Date", "value": "Total Sleep (h)"}
        )
        anom_chart = (
            alt.Chart(anom_df)
            .mark_point(shape="triangle-up", size=100, color="#DC143C")
            .encode(
                x=alt.X("Date:T"),
                y=alt.Y("Total Sleep (h):Q"),
                tooltip=[
                    alt.Tooltip("Date:T", format="%b %d"),
                    alt.Tooltip("Total Sleep (h):Q", format=".1f"),
                    alt.Tooltip("direction:N"),
                    alt.Tooltip("severity:Q", format=".1f"),
                ],
            )
        )
        layers.append(anom_chart)

    st.altair_chart(alt.layer(*layers).properties(height=260), use_container_width=True)
    st.caption("Orange line: 7-day rolling average  ·  Blue dashed: deep sleep  ·  Red ▲: anomaly")

    st.divider()

    # ── 3. SLEEP STAGE DISTRIBUTION ───────────────────────────────────────
    st.subheader("Sleep Stage Distribution")

    area_rows = []
    for i in insights:
        for stage, mins in [
            ("Light", i.light_minutes),
            ("Deep", i.deep_minutes),
            ("REM", i.rem_minutes),
            ("Awake", i.awake_minutes),
        ]:
            if mins is not None:
                area_rows.append({"Date": i.date, "Stage": stage, "Hours": mins / 60})

    if area_rows:
        area_df = pd.DataFrame(area_rows)
        area_chart = (
            alt.Chart(area_df)
            .mark_area()
            .encode(
                x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("Hours:Q", stack="zero", title="Hours"),
                color=alt.Color(
                    "Stage:N",
                    scale=alt.Scale(domain=_STAGE_ORDER, range=_STAGE_COLORS),
                    sort=_STAGE_ORDER,
                ),
                order=alt.Order("Stage:N", sort="ascending"),
                tooltip=[
                    alt.Tooltip("Date:T", title="Date", format="%b %d"),
                    alt.Tooltip("Stage:N"),
                    alt.Tooltip("Hours:Q", format=".2f"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(area_chart, use_container_width=True)
    else:
        st.info("No sleep stage data available.")

    st.divider()

    # ── 4. SLEEP CONSISTENCY ──────────────────────────────────────────────
    st.subheader("Sleep Consistency")

    consistency = _load_consistency(n_days, end_date.isoformat())

    if consistency.get("insufficient_data"):
        st.info(consistency.get("message", "Not enough data for consistency analysis."))
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Avg Bedtime", _fmt_time(consistency.get("avg_bedtime_hour")))
            std_bed = consistency.get("bedtime_std_hours")
            if std_bed is not None:
                st.caption(f"±{std_bed * 60:.0f} min variability")
        with c2:
            st.metric("Avg Wake Time", _fmt_time(consistency.get("avg_wake_hour")))
            std_wake = consistency.get("wake_time_std_hours")
            if std_wake is not None:
                st.caption(f"±{std_wake * 60:.0f} min variability")
        with c3:
            st.metric("Avg Total Sleep", _fmt_dur(consistency.get("avg_total_sleep_minutes")))
        with c4:
            trend = consistency.get("sleep_debt_trend", "unknown")
            trend_label = {
                "improving": "↑ Improving",
                "worsening": "↓ Worsening",
                "stable": "→ Stable",
            }.get(trend, "Unknown")
            st.metric("Debt Trend", trend_label)
            slope = consistency.get("sleep_debt_trend_slope_min_per_day")
            if slope is not None:
                st.caption(f"{slope:+.1f} min/day")

    st.divider()

    # ── 5. TRAINING ↔ SLEEP CONNECTIONS ──────────────────────────────────
    st.subheader("Training \u2194 Sleep Connections")

    corr = _load_correlation(n_days, end_date.isoformat())

    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("**Strain → Total Sleep**")
        st.caption(_corr_narrative("strain_vs_total_sleep", corr))
    with t2:
        st.markdown("**Strain → Deep Sleep**")
        st.caption(_corr_narrative("strain_vs_deep_sleep", corr))
    with t3:
        st.markdown("**Strain → Next-Day Recovery**")
        st.caption(_corr_narrative("strain_vs_next_day_recovery", corr))
