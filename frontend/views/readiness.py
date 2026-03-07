"""Morning-first readiness dashboard.

Sections (top to bottom):
  1. Today's Readiness — hero score, recommendation, confidence
  2. Contributing Factors — 5-component breakdown with yesterday delta
  3. Readiness Trend — 30-day history, 7d rolling avg, anomalies
  4. Key Metrics Snapshot — HRV, RHR, sleep, strain (2×2 grid)
  5. Weekly Comparison — this week vs last week % changes
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import text  # noqa: E402

from frontend.db import get_engine  # noqa: E402
from src.analytics.readiness_score import compute_readiness, get_readiness_history  # noqa: E402
from src.analytics.trends import (  # noqa: E402
    detect_anomalies,
    get_metric_series,
    get_weekly_summary,
)

# Score → color mapping (checked highest-first)
_SCORE_BANDS: list[tuple[float, str]] = [
    (80, "#2E8B57"),  # green
    (60, "#9ACD32"),  # yellow-green
    (40, "#FF8C00"),  # orange
    (0, "#DC143C"),  # red
]

# How to format each factor's raw_value for the caption line
_FACTOR_RAW_FMT: dict[str, str] = {
    "whoop_recovery": "{:.0f}",
    "hrv_trend": "{:.1f} ms",
    "body_battery": "{:.0f}",
    "sleep_quality": "{:.0f}%",
    "training_load": "{:.1f}",
}

_FACTOR_ORDER = [
    "whoop_recovery",
    "hrv_trend",
    "body_battery",
    "sleep_quality",
    "training_load",
]


# ---------------------------------------------------------------------------
# Cached data loaders (each calls get_engine() internally to avoid
# passing an un-hashable Engine as a cache key)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_readiness(date_str: str) -> dict:
    r = compute_readiness(date.fromisoformat(date_str), get_engine())
    return {
        "score": r.score,
        "recommendation": r.recommendation,
        "confidence": r.confidence,
        "factors": r.contributing_factors,
    }


@st.cache_data(ttl=300)
def _load_history(start: str, end: str) -> list[dict]:
    return get_readiness_history(date.fromisoformat(start), date.fromisoformat(end), get_engine())


@st.cache_data(ttl=300)
def _load_spark(metric: str, start: str, end: str) -> list[dict]:
    pts = get_metric_series(
        get_engine(), metric, date.fromisoformat(start), date.fromisoformat(end)
    )
    return [{"date": p.date, "value": p.value} for p in pts]


@st.cache_data(ttl=300)
def _load_weekly(today: str) -> dict:
    return get_weekly_summary(get_engine(), date.fromisoformat(today))


@st.cache_data(ttl=300)
def _find_latest_data_date(end: str) -> str:
    """Return the most recent date ≤ end that has a whoop_recovery_score."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT MAX(date) FROM unified_daily"
                " WHERE whoop_recovery_score IS NOT NULL AND date <= :end"
            ),
            {"end": end},
        ).fetchone()
    if row and row[0]:
        return row[0]
    # Fall back: most recent date in unified_daily at all
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM unified_daily WHERE date <= :end"),
            {"end": end},
        ).fetchone()
    return row[0] if (row and row[0]) else end


@st.cache_data(ttl=300)
def _load_snapshot(today: str, yesterday: str, week_start: str) -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        td = (
            conn.execute(
                text("SELECT whoop_hrv_rmssd, whoop_rhr FROM unified_daily WHERE date = :d"),
                {"d": today},
            )
            .mappings()
            .fetchone()
        )
        sl = (
            conn.execute(
                text(
                    "SELECT total_sleep_minutes, deep_sleep_minutes"
                    " FROM unified_sleep WHERE date = :d"
                ),
                {"d": today},
            )
            .mappings()
            .fetchone()
        )
        yd = (
            conn.execute(
                text("SELECT whoop_strain FROM unified_daily WHERE date = :d"),
                {"d": yesterday},
            )
            .mappings()
            .fetchone()
        )
        week_strain = conn.execute(
            text("SELECT SUM(whoop_strain) FROM unified_daily WHERE date >= :s AND date <= :e"),
            {"s": week_start, "e": today},
        ).scalar()
    return {
        "hrv": td["whoop_hrv_rmssd"] if td else None,
        "rhr": td["whoop_rhr"] if td else None,
        "sleep_minutes": sl["total_sleep_minutes"] if sl else None,
        "deep_minutes": sl["deep_sleep_minutes"] if sl else None,
        "strain_yesterday": yd["whoop_strain"] if yd else None,
        "strain_week": week_strain,
    }


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


def _score_color(score: float) -> str:
    for threshold, color in _SCORE_BANDS:
        if score >= threshold:
            return color
    return _SCORE_BANDS[-1][1]


def _rolling_7d(values: list) -> list:
    result = []
    for i in range(len(values)):
        win = [values[j] for j in range(max(0, i - 6), i + 1) if values[j] is not None]
        result.append(sum(win) / len(win) if win else None)
    return result


def _sparkline(data: list[dict], color: str = "#4472CA") -> alt.Chart:
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["value"])
    if df.empty:
        return (
            alt.Chart(pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "value": []}))
            .mark_line()
            .encode(x="date:T", y="value:Q")
            .properties(height=50)
        )
    return (
        alt.Chart(df)
        .mark_line(color=color, strokeWidth=2)
        .encode(
            x=alt.X("date:T", axis=None),
            y=alt.Y("value:Q", axis=None, scale=alt.Scale(zero=False)),
        )
        .properties(height=50)
    )


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render(start_date: date, end_date: date) -> None:
    st.title("Readiness")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load readiness data. This may be a temporary database issue. "
            f"Details: `{exc}`"
        )


def _render_body(start_date: date, end_date: date) -> None:
    latest_str = _find_latest_data_date(end_date.isoformat())
    today = date.fromisoformat(latest_str)
    if today < end_date:
        st.info(
            f"No readiness data for {end_date}. "
            f"Showing most recent available: **{today}**. Run a sync to update."
        )

    yesterday = today - timedelta(days=1)
    trend_start = max(start_date, today - timedelta(days=29))
    week_start = today - timedelta(days=6)

    # Load everything upfront
    readiness = _load_readiness(today.isoformat())
    readiness_yday = _load_readiness(yesterday.isoformat())
    history = _load_history(trend_start.isoformat(), today.isoformat())
    weekly = _load_weekly(today.isoformat())
    snapshot = _load_snapshot(today.isoformat(), yesterday.isoformat(), week_start.isoformat())

    score = readiness["score"]
    factors = readiness["factors"]
    factors_yday = readiness_yday["factors"]
    n_sources = sum(1 for f in factors.values() if f["normalized_value"] is not None)

    # ── 1. TODAY'S READINESS ─────────────────────────────────────────────────
    color = _score_color(score)
    _, hero_col, _ = st.columns([1, 2, 1])
    with hero_col:
        st.markdown(
            f"<div style='text-align:center'>"
            f"<span style='font-size:96px;font-weight:700;color:{color};line-height:1.1'>"
            f"{score:.0f}</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='text-align:center;font-size:17px;margin-top:4px'>"
            f"{readiness['recommendation']}</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='text-align:center;color:gray;font-size:13px;margin-top:2px'>"
            f"Based on {n_sources} of 5 data sources</p>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── 2. CONTRIBUTING FACTORS ───────────────────────────────────────────────
    st.subheader("Contributing Factors")

    factor_cols = st.columns(5)
    for col, key in zip(factor_cols, _FACTOR_ORDER):
        f = factors[key]
        norm = f["normalized_value"]
        eff_w = f["effective_weight"]
        raw = f["raw_value"]

        yday_norm = factors_yday[key]["normalized_value"]
        delta = f"{norm - yday_norm:+.1f}" if (norm is not None and yday_norm is not None) else None

        with col:
            st.metric(
                label=f["name"],
                value=f"{norm:.0f}" if norm is not None else "—",
                delta=delta,
            )
            raw_str = _FACTOR_RAW_FMT[key].format(raw) if raw is not None else "No data"
            st.caption(f"{raw_str} · {eff_w:.0%} weight")

    st.divider()

    # ── 3. READINESS TREND ────────────────────────────────────────────────────
    st.subheader("Readiness Trend — Last 30 Days")

    if not history:
        st.info("No readiness history for the selected range.")
    else:
        df_h = pd.DataFrame(history)
        df_h["date"] = pd.to_datetime(df_h["date"])
        # Replace no-data days (confidence=0) with None so they don't show
        df_h["real_score"] = df_h.apply(
            lambda r: r["score"] if r["confidence"] > 0 else None, axis=1
        )
        raw_scores = df_h["real_score"].tolist()
        df_h["rolling_7d"] = _rolling_7d(raw_scores)

        date_strs = df_h["date"].dt.strftime("%Y-%m-%d").tolist()
        anomaly_dates = {a["date"] for a in detect_anomalies(raw_scores, date_strs)}
        df_h["is_anomaly"] = df_h["date"].dt.strftime("%Y-%m-%d").isin(anomaly_dates)
        df_h["is_today"] = df_h["date"].dt.date == today

        df_scores = df_h.dropna(subset=["real_score"]).copy()
        df_rolling = df_h.dropna(subset=["rolling_7d"]).copy()

        # Base score line + dots
        score_line = (
            alt.Chart(df_scores)
            .mark_line(color="#4472CA", strokeWidth=1.5)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y(
                    "real_score:Q",
                    title="Readiness",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("real_score:Q", title="Score", format=".0f"),
                ],
            )
            .properties(height=240)
        )
        score_dots = (
            alt.Chart(df_scores)
            .mark_circle(size=30, color="#4472CA", opacity=0.6)
            .encode(x="date:T", y="real_score:Q")
        )

        # 7-day rolling average overlay
        rolling_line = (
            alt.Chart(df_rolling)
            .mark_line(color="#ED7D31", strokeWidth=2, strokeDash=[5, 3])
            .encode(
                x="date:T",
                y=alt.Y("rolling_7d:Q", scale=alt.Scale(domain=[0, 100])),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%b %d"),
                    alt.Tooltip("rolling_7d:Q", title="7d Avg", format=".1f"),
                ],
            )
        )

        chart = score_line + score_dots + rolling_line

        # Anomaly markers (red)
        df_anom = df_scores[df_scores["is_anomaly"]].copy()
        if not df_anom.empty:
            chart = chart + (
                alt.Chart(df_anom)
                .mark_circle(size=90, color="#DC143C", opacity=0.9)
                .encode(
                    x="date:T",
                    y="real_score:Q",
                    tooltip=[
                        alt.Tooltip("date:T", title="Anomaly", format="%b %d"),
                        alt.Tooltip("real_score:Q", title="Score", format=".0f"),
                    ],
                )
            )

        # Today marker (green)
        df_today_pt = df_scores[df_scores["is_today"]].copy()
        if not df_today_pt.empty:
            chart = chart + (
                alt.Chart(df_today_pt)
                .mark_circle(size=150, color="#00B050")
                .encode(x="date:T", y="real_score:Q")
            )

        st.altair_chart(chart, use_container_width=True)
        st.caption(
            "Blue = daily score · Dashed orange = 7-day rolling avg"
            " · Red dot = anomaly · Green dot = today"
        )

    st.divider()

    # ── 4. KEY METRICS SNAPSHOT ───────────────────────────────────────────────
    st.subheader("Key Metrics")

    spark_start = (today - timedelta(days=6)).isoformat()
    hrv_spark = _load_spark("hrv", spark_start, today.isoformat())
    rhr_spark = _load_spark("resting_hr", spark_start, today.isoformat())

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.markdown("**HRV**")
        hrv = snapshot["hrv"]
        st.metric(
            "HRV",
            f"{hrv:.1f} ms" if hrv is not None else "—",
            label_visibility="collapsed",
        )
        st.altair_chart(_sparkline(hrv_spark, "#4472CA"), use_container_width=True)
        st.caption("7-day trend")

    with k2:
        st.markdown("**Resting HR**")
        rhr = snapshot["rhr"]
        st.metric(
            "RHR",
            f"{rhr:.0f} bpm" if rhr is not None else "—",
            label_visibility="collapsed",
        )
        st.altair_chart(_sparkline(rhr_spark, "#ED7D31"), use_container_width=True)
        st.caption("7-day trend")

    with k3:
        st.markdown("**Sleep Last Night**")
        mins = snapshot["sleep_minutes"]
        deep = snapshot["deep_minutes"]
        hours_str = f"{mins / 60:.1f} h" if mins is not None else "—"
        st.metric("Sleep", hours_str, label_visibility="collapsed")
        if mins and deep and mins > 0:
            st.caption(f"{deep / mins * 100:.0f}% deep sleep")

    with k4:
        st.markdown("**Strain**")
        strain_yd = snapshot["strain_yesterday"]
        strain_wk = snapshot["strain_week"]
        st.metric(
            "Strain",
            f"{strain_yd:.1f}" if strain_yd is not None else "—",
            label_visibility="collapsed",
        )
        if strain_wk is not None:
            st.caption(f"Week total: {strain_wk:.1f}")
        else:
            st.caption("Yesterday's strain")

    st.divider()

    # ── 5. WEEKLY COMPARISON ──────────────────────────────────────────────────
    st.subheader("This Week vs Last Week")

    comparison = weekly.get("comparison", {})

    def _pct_delta(key: str) -> str | None:
        v = comparison.get(key)
        return f"{v:+.1f}%" if v is not None else None

    wk1, wk2, wk3, wk4, wk5 = st.columns(5)

    with wk1:
        v = weekly.get("avg_readiness")
        st.metric(
            "Avg Readiness",
            f"{v:.0f}" if v is not None else "—",
            delta=_pct_delta("avg_readiness"),
        )

    with wk2:
        v = weekly.get("avg_recovery")
        st.metric(
            "Avg Recovery",
            f"{v:.0f}%" if v is not None else "—",
            delta=_pct_delta("avg_recovery"),
        )

    with wk3:
        v = weekly.get("total_strain")
        st.metric(
            "Total Strain",
            f"{v:.1f}" if v is not None else "—",
            delta=_pct_delta("total_strain"),
        )

    with wk4:
        v = weekly.get("avg_sleep_duration")
        st.metric(
            "Avg Sleep",
            f"{v / 60:.1f} h" if v is not None else "—",
            delta=_pct_delta("avg_sleep_duration"),
        )

    with wk5:
        v = weekly.get("workout_count", 0)
        st.metric(
            "Workouts",
            str(v),
            delta=_pct_delta("workout_count"),
        )
