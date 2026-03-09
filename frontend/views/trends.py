"""Trends analysis view — rolling metrics, anomalies, and week-over-week comparison.

Sections:
  1. Weekly Summary Card — 6 key metrics with WoW % change
  2. Metric Explorer — selector + trend chart (raw dots + 7d avg + 30d avg + anomaly markers)
  3. Anomaly Log — recent flagged days across all tracked metrics
  4. Metric Correlations — Pearson r heatmap between key daily metrics
"""

import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from frontend.db import get_engine  # noqa: E402
from src.analytics.trends import (  # noqa: E402
    get_metric_series,
    get_metric_trend,
    get_weekly_summary,
)

# Dropdown label → internal metric key
_METRIC_OPTIONS: dict[str, str] = {
    "Recovery Score": "recovery",
    "HRV": "hrv",
    "Resting HR": "resting_hr",
    "Strain (Daily)": "strain",
    "Body Battery": "body_battery",
    "Sleep Duration": "sleep_duration",
    "Deep Sleep": "deep_sleep",
    "Readiness": "readiness",
    "Training Load": "training_load",
}

# (display_label, unit_suffix, lower_is_better)
_METRIC_META: dict[str, tuple[str, str, bool]] = {
    "recovery": ("Recovery Score", "", False),
    "hrv": ("HRV", " ms", False),
    "resting_hr": ("Resting HR", " bpm", True),
    "strain": ("Daily Strain", "", False),
    "body_battery": ("Body Battery", "", False),
    "sleep_duration": ("Sleep Duration (min)", "", False),
    "deep_sleep": ("Deep Sleep (min)", "", False),
    "readiness": ("Readiness", "", False),
    "training_load": ("Training Load", "", False),
}

# Metrics included in the anomaly log (excludes slow computed metrics)
_ANOMALY_METRIC_KEYS: dict[str, str] = {
    "Recovery Score": "recovery",
    "HRV": "hrv",
    "Resting HR": "resting_hr",
    "Strain (Daily)": "strain",
    "Body Battery": "body_battery",
    "Sleep Duration": "sleep_duration",
    "Deep Sleep": "deep_sleep",
}

# Notable-anomaly metric names from get_weekly_summary → nice label
_WEEKLY_ANOM_LABELS: dict[str, str] = {
    "recovery_score": "Recovery",
    "hrv": "HRV",
    "resting_hr": "Resting HR",
    "body_battery": "Body Battery",
}

_DEFAULT_DAYS = 60


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_weekly(end: str) -> dict:
    return get_weekly_summary(get_engine(), date.fromisoformat(end))


@st.cache_data(ttl=300)
def _load_trend(metric: str, start: str, end: str) -> dict:
    t = get_metric_trend(get_engine(), metric, date.fromisoformat(start), date.fromisoformat(end))
    return {
        "dates": t.dates,
        "values": t.values,
        "rolling_avg_7d": t.rolling_avg_7d,
        "rolling_avg_30d": t.rolling_avg_30d,
        "anomalies": t.anomalies,
        "trend_direction": t.trend_direction,
    }


@st.cache_data(ttl=300)
def _load_anomaly_log(start: str, end: str) -> list[dict]:
    engine = get_engine()
    rows: list[dict] = []
    for label, key in _ANOMALY_METRIC_KEYS.items():
        try:
            t = get_metric_trend(engine, key, date.fromisoformat(start), date.fromisoformat(end))
            for a in t.anomalies:
                rows.append(
                    {
                        "Date": a["date"],
                        "Metric": label,
                        "Value": round(a["value"], 1),
                        "Direction": a["direction"].title(),
                        "Severity (σ)": round(abs(a["severity"]), 2),
                    }
                )
        except Exception:  # noqa: BLE001
            continue
    return sorted(rows, key=lambda x: x["Date"], reverse=True)


@st.cache_data(ttl=300)
def _load_corr_series(start: str, end: str) -> dict[str, dict[str, float | None]]:
    engine = get_engine()
    corr_metrics = {
        "Recovery": "recovery",
        "HRV": "hrv",
        "Resting HR": "resting_hr",
        "Strain": "strain",
        "Body Battery": "body_battery",
        "Sleep (h)": "sleep_duration",
    }
    out: dict[str, dict[str, float | None]] = {}
    for label, key in corr_metrics.items():
        try:
            pts = get_metric_series(engine, key, date.fromisoformat(start), date.fromisoformat(end))
            # Convert sleep_duration from minutes to hours for display
            scale = 1 / 60 if key == "sleep_duration" else 1.0
            out[label] = {p.date: (p.value * scale if p.value is not None else None) for p in pts}
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    ss_x = sum((x - mx) ** 2 for x in xs)
    ss_y = sum((y - my) ** 2 for y in ys)
    if ss_x == 0 or ss_y == 0:
        return None
    return num / math.sqrt(ss_x * ss_y)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render(start_date: date, end_date: date) -> None:
    st.title("Trends")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load trends data. This may be a temporary database issue. Details: `{exc}`"
        )


def _render_body(start_date: date, end_date: date) -> None:
    # ── 1. WEEKLY SUMMARY CARD ─────────────────────────────────────────────
    week_start = end_date - timedelta(days=6)
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)

    st.subheader(f"Week of {week_start.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}")

    weekly = _load_weekly(end_date.isoformat())
    comp = weekly.get("comparison", {})

    def _delta(key: str, inverse: bool = False) -> tuple[str | None, str]:
        pct = comp.get(key)
        if pct is None:
            return None, "off"
        return f"{pct:+.1f}%", "inverse" if inverse else "normal"

    w1, w2, w3, w4, w5, w6 = st.columns(6)

    with w1:
        v = weekly.get("avg_readiness")
        d, dc = _delta("avg_readiness")
        st.metric("Readiness", f"{v:.0f}" if v is not None else "—", delta=d, delta_color=dc)

    with w2:
        v = weekly.get("avg_recovery")
        d, dc = _delta("avg_recovery")
        st.metric("Recovery", f"{v:.0f}%" if v is not None else "—", delta=d, delta_color=dc)

    with w3:
        v = weekly.get("avg_hrv")
        d, dc = _delta("avg_hrv")
        st.metric("Avg HRV", f"{v:.1f} ms" if v is not None else "—", delta=d, delta_color=dc)

    with w4:
        v = weekly.get("total_strain")
        d, dc = _delta("total_strain")
        st.metric("Total Strain", f"{v:.1f}" if v is not None else "—", delta=d, delta_color=dc)

    with w5:
        v = weekly.get("avg_sleep_duration")
        d, dc = _delta("avg_sleep_duration")
        st.metric(
            "Avg Sleep",
            f"{v / 60:.1f} h" if v is not None else "—",
            delta=d,
            delta_color=dc,
        )

    with w6:
        v = weekly.get("workout_count", 0)
        d, dc = _delta("workout_count")
        st.metric("Workouts", str(v), delta=d, delta_color=dc)

    st.caption(
        f"vs {prev_week_start.strftime('%b %d')}–{prev_week_end.strftime('%b %d')} · % change"
    )

    notable = weekly.get("notable_anomalies", [])
    if notable:
        flags = ", ".join(
            f"{_WEEKLY_ANOM_LABELS.get(a.get('metric', ''), a.get('metric', '?'))} "
            f"({a.get('direction', '?')})"
            for a in notable[:5]
        )
        st.warning(f"Notable this week: {flags}")

    st.divider()

    # ── 2. METRIC EXPLORER ────────────────────────────────────────────────
    st.subheader("Metric Explorer")

    sel_col, _ = st.columns([1, 3])
    with sel_col:
        metric_label = st.selectbox("Select metric", list(_METRIC_OPTIONS.keys()), index=0)

    metric_key = _METRIC_OPTIONS[metric_label]
    display_label, _unit, lower_is_better = _METRIC_META[metric_key]

    chart_days = min(_DEFAULT_DAYS, (end_date - start_date).days + 1)
    chart_start = end_date - timedelta(days=chart_days - 1)

    trend = _load_trend(metric_key, chart_start.isoformat(), end_date.isoformat())

    df = pd.DataFrame(
        {
            "Date": trend["dates"],
            "Value": trend["values"],
            "7d Avg": trend["rolling_avg_7d"],
            "30d Avg": trend["rolling_avg_30d"],
        }
    )

    raw_pts = (
        alt.Chart(df.dropna(subset=["Value"]))
        .mark_circle(size=25, opacity=0.4, color="#4472CA")
        .encode(
            x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b %d")),
            y=alt.Y("Value:Q", title=display_label, scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", title="Date", format="%b %d"),
                alt.Tooltip("Value:Q", title=display_label, format=".1f"),
            ],
        )
    )
    line_7d = (
        alt.Chart(df.dropna(subset=["7d Avg"]))
        .mark_line(color="#ED7D31", strokeWidth=2.5)
        .encode(
            x="Date:T",
            y=alt.Y("7d Avg:Q", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", format="%b %d"),
                alt.Tooltip("7d Avg:Q", title="7d Avg", format=".1f"),
            ],
        )
    )
    line_30d = (
        alt.Chart(df.dropna(subset=["30d Avg"]))
        .mark_line(color="#9DC3E6", strokeWidth=1.5, strokeDash=[4, 2])
        .encode(
            x="Date:T",
            y=alt.Y("30d Avg:Q", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", format="%b %d"),
                alt.Tooltip("30d Avg:Q", title="30d Avg", format=".1f"),
            ],
        )
    )

    layers = [raw_pts, line_7d, line_30d]

    if trend["anomalies"]:
        adf = pd.DataFrame(trend["anomalies"]).rename(columns={"date": "Date", "value": "Value"})
        layers.append(
            alt.Chart(adf)
            .mark_circle(size=80, color="#DC143C", opacity=0.9)
            .encode(
                x="Date:T",
                y=alt.Y("Value:Q", scale=alt.Scale(zero=False)),
                tooltip=[
                    alt.Tooltip("Date:T", format="%b %d"),
                    alt.Tooltip("Value:Q", title=display_label, format=".1f"),
                    alt.Tooltip("direction:N", title="Direction"),
                    alt.Tooltip("severity:Q", title="Severity (σ)", format=".2f"),
                ],
            )
        )

    st.altair_chart(alt.layer(*layers).properties(height=280), width='stretch')
    st.caption(
        "Blue dots: daily values  ·  Orange: 7d rolling avg  ·  "
        "Dashed blue: 30d rolling avg  ·  Red dots: anomalies (≥ 2σ)"
    )

    # Trend direction sentence
    raw_dir = trend["trend_direction"]
    if lower_is_better and raw_dir != "stable":
        display_dir = "improving" if raw_dir == "declining" else "declining"
    else:
        display_dir = raw_dir

    arrow = {"improving": "↑", "declining": "↓", "stable": "→"}.get(display_dir, "→")
    dcolor = {"improving": "green", "declining": "red", "stable": "gray"}.get(display_dir, "gray")
    st.markdown(
        f"**{display_label}** is "
        f"<span style='color:{dcolor};font-weight:600'>{arrow} {display_dir}</span> "
        f"over the past 7 days.",
        unsafe_allow_html=True,
    )

    st.divider()

    # ── 3. ANOMALY LOG ────────────────────────────────────────────────────
    st.subheader("Anomaly Log")
    st.caption(
        "Days where a metric deviated ≥ 2 standard deviations from its 7-day prior average. "
        "Use this to diagnose what happened on unusual days."
    )

    log_start = end_date - timedelta(days=min(59, (end_date - start_date).days))
    anomaly_rows = _load_anomaly_log(log_start.isoformat(), end_date.isoformat())

    if not anomaly_rows:
        st.info("No anomalies detected in the selected period.")
    else:
        st.dataframe(pd.DataFrame(anomaly_rows), width='stretch', hide_index=True)

    st.divider()

    # ── 4. METRIC CORRELATIONS ─────────────────────────────────────────────
    st.subheader("Metric Correlations")
    st.caption(
        "Pearson r between daily metric values over the last 60 days. "
        "Blue = positive, red = negative, darker = stronger."
    )

    corr_start = end_date - timedelta(days=min(59, (end_date - start_date).days))
    series_data = _load_corr_series(corr_start.isoformat(), end_date.isoformat())

    if len(series_data) < 2:
        st.info("Not enough data to compute correlations.")
    else:
        all_dates = sorted(set().union(*[s.keys() for s in series_data.values()]))
        data_df = pd.DataFrame(
            {lbl: [series_data[lbl].get(d) for d in all_dates] for lbl in series_data},
            index=all_dates,
        )
        labels = list(series_data.keys())

        corr_rows = []
        for a in labels:
            for b in labels:
                if a == b:
                    r = 1.0
                else:
                    pairs = data_df[[a, b]].dropna()
                    r = _pearson(pairs[a].tolist(), pairs[b].tolist()) if len(pairs) >= 5 else None
                corr_rows.append(
                    {
                        "Metric A": a,
                        "Metric B": b,
                        "r": r,
                        "Label": f"{r:.2f}" if r is not None else "—",
                    }
                )

        cdf = pd.DataFrame(corr_rows)
        heatmap = (
            alt.Chart(cdf.dropna(subset=["r"]))
            .mark_rect()
            .encode(
                x=alt.X("Metric A:N", title=None, sort=labels),
                y=alt.Y("Metric B:N", title=None, sort=labels),
                color=alt.Color(
                    "r:Q",
                    scale=alt.Scale(domain=[-1, 0, 1], range=["#D62728", "#F5F5F5", "#1F77B4"]),
                    title="Pearson r",
                ),
                tooltip=[
                    alt.Tooltip("Metric A:N"),
                    alt.Tooltip("Metric B:N"),
                    alt.Tooltip("r:Q", title="Pearson r", format=".3f"),
                ],
            )
        )
        text_marks = (
            alt.Chart(cdf.dropna(subset=["r"]))
            .mark_text(fontSize=12)
            .encode(
                x=alt.X("Metric A:N", sort=labels),
                y=alt.Y("Metric B:N", sort=labels),
                text=alt.Text("Label:N"),
            )
        )
        st.altair_chart((heatmap + text_marks).properties(height=300), width='stretch')
