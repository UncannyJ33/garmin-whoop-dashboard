"""Recovery Activities dashboard.

Visualises Whoop-tracked recovery modalities (stretching, breathwork,
percussive massage, etc.) and their relationship to next-day recovery score,
HRV, and sleep quality.

Sections (top to bottom):
  1. Summary bar
  2. Weekly activity breakdown (stacked bar by type)
  3. Duration over time
  4. Recovery days vs non-recovery days (next-day recovery comparison)
  5. Duration vs next-day recovery scatter
  6. Next-day recovery by activity type
  7. Next-day sleep performance by activity type
  8. Activity log
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

_QUERY = """
SELECT
    DATE(ww.start_time)                                                   AS date,
    ww.sport_name                                                         AS activity,
    ROUND(
        (strftime('%s', ww.end_time) - strftime('%s', ww.start_time))
        / 60.0, 1)                                                        AS dur_min,
    ud.whoop_recovery_score                                               AS same_day_recovery,
    ud_next.whoop_recovery_score                                          AS next_day_recovery,
    ud_next.whoop_hrv_rmssd                                               AS next_day_hrv,
    us.whoop_performance                                                  AS next_day_sleep_perf,
    us.total_sleep_minutes                                                AS next_day_sleep_min
FROM whoop_workouts ww
LEFT JOIN unified_daily ud
       ON ud.date = DATE(ww.start_time)
LEFT JOIN unified_daily ud_next
       ON ud_next.date = DATE(ww.start_time, '+1 day')
LEFT JOIN unified_sleep us
       ON us.date = DATE(ww.start_time, '+1 day')
WHERE ww.strain IS NULL
  AND ww.end_time IS NOT NULL
  AND ww.start_time >= :start
  AND ww.start_time <  :end
ORDER BY ww.start_time DESC
"""

_ALL_RECOVERY_DATES_QUERY = """
SELECT DISTINCT DATE(start_time) AS date
FROM whoop_workouts
WHERE strain IS NULL AND end_time IS NOT NULL
"""

_DAILY_RECOVERY_QUERY = """
SELECT date, whoop_recovery_score AS next_day_recovery
FROM unified_daily
WHERE date >= :start AND date < :end
  AND whoop_recovery_score IS NOT NULL
"""

_TYPE_COLORS = [
    "#4472CA", "#70AD47", "#FFC000", "#FF7A00", "#DC143C",
    "#9467BD", "#8C564B",
]


@st.cache_data(ttl=300)
def _load(start: str, end: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text(_QUERY), conn, params={"start": start, "end": end})
    df["activity"] = df["activity"].str.replace("-", " ").str.replace("_", " ").str.title()
    return df


@st.cache_data(ttl=300)
def _load_with_without(start: str, end: str) -> pd.DataFrame:
    """Return all days in range with next-day recovery and a flag for whether
    the prior day had a recovery activity."""
    with get_engine().connect() as conn:
        rec_dates = {
            r[0]
            for r in conn.execute(text(_ALL_RECOVERY_DATES_QUERY)).fetchall()
        }
        daily = pd.read_sql(
            text(_DAILY_RECOVERY_QUERY), conn, params={"start": start, "end": end}
        )

    # Each row is a day; we want: did the PREVIOUS day have a recovery activity?
    daily["prev_date"] = (
        pd.to_datetime(daily["date"]) - pd.Timedelta(days=1)
    ).dt.strftime("%Y-%m-%d")
    daily["had_recovery"] = daily["prev_date"].isin(rec_dates)
    return daily


def render(start_date: date, end_date: date) -> None:
    st.title("Recovery Activities")

    try:
        _render_body(start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load recovery activity data. Details: `{exc}`")


def _render_body(start_date: date, end_date: date) -> None:
    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    df = _load(start_date.isoformat(), end_exclusive)

    if df.empty:
        st.warning("No recovery activities found for the selected date range.")
        return

    # ── 1. SUMMARY BAR ───────────────────────────────────────────────────────
    total = len(df)
    most_common = df["activity"].value_counts().idxmax()
    avg_dur = df["dur_min"].mean()
    avg_next = df["next_day_recovery"].mean()

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("Sessions", total)
    with s2:
        st.metric("Most Common", most_common)
    with s3:
        st.metric("Avg Duration", f"{avg_dur:.0f} min" if pd.notna(avg_dur) else "—")
    with s4:
        st.metric(
            "Avg Next-Day Recovery",
            f"{avg_next:.0f}" if pd.notna(avg_next) else "—",
        )

    st.divider()

    # ── 2. WEEKLY BREAKDOWN ───────────────────────────────────────────────────
    st.subheader("Weekly Session Breakdown")

    df["date_dt"] = pd.to_datetime(df["date"])
    df["week"] = df["date_dt"].dt.strftime("%G-W%V")

    weekly = (
        df.groupby(["week", "activity"])
        .size()
        .reset_index(name="sessions")
        .sort_values("week")
    )

    weekly_chart = (
        alt.Chart(weekly)
        .mark_bar()
        .encode(
            x=alt.X("week:O", title="Week", sort=None, axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("sessions:Q", title="Sessions", stack="zero"),
            color=alt.Color(
                "activity:N",
                title="Activity",
                scale=alt.Scale(range=_TYPE_COLORS),
            ),
            tooltip=[
                alt.Tooltip("week:O", title="Week"),
                alt.Tooltip("activity:N", title="Activity"),
                alt.Tooltip("sessions:Q", title="Sessions"),
            ],
        )
        .properties(height=240)
    )
    st.altair_chart(weekly_chart, width="stretch")

    st.divider()

    # ── 3. DURATION OVER TIME ─────────────────────────────────────────────────
    st.subheader("Session Duration Over Time")

    dur_chart = (
        alt.Chart(df)
        .mark_point(filled=True, size=80)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("dur_min:Q", title="Duration (min)", scale=alt.Scale(zero=True)),
            color=alt.Color(
                "activity:N",
                title="Activity",
                scale=alt.Scale(range=_TYPE_COLORS),
            ),
            tooltip=[
                alt.Tooltip("date:T", format="%b %d", title="Date"),
                alt.Tooltip("activity:N", title="Activity"),
                alt.Tooltip("dur_min:Q", format=".0f", title="Duration (min)"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(dur_chart, width="stretch")

    st.divider()

    # ── 4. RECOVERY DAYS VS NON-RECOVERY DAYS ─────────────────────────────────
    st.subheader("Next-Day Recovery: With vs Without Recovery Activity")

    with_without = _load_with_without(start_date.isoformat(), end_exclusive)

    ww_summary = (
        with_without.groupby("had_recovery")["next_day_recovery"]
        .agg(["mean", "count"])
        .reset_index()
    )
    ww_summary["label"] = ww_summary["had_recovery"].map(
        {True: "Recovery activity\nday before", False: "No recovery activity\nday before"}
    )
    ww_summary["mean"] = ww_summary["mean"].round(1)

    if len(ww_summary) == 2:
        with_val = ww_summary.loc[ww_summary["had_recovery"], "mean"].values[0]
        without_val = ww_summary.loc[~ww_summary["had_recovery"], "mean"].values[0]
        diff = with_val - without_val
        direction = "higher" if diff >= 0 else "lower"
        col_stat, col_chart = st.columns([1, 2])
        with col_stat:
            st.metric(
                "With recovery activity",
                f"{with_val:.1f}",
                delta=f"{diff:+.1f} vs without",
            )
            st.caption(
                f"Next-day recovery is **{abs(diff):.1f} points {direction}** "
                f"after a recovery activity day."
            )
        with col_chart:
            ww_bar = (
                alt.Chart(ww_summary)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                .encode(
                    x=alt.X("label:N", title=None, axis=alt.Axis(labelLimit=200)),
                    y=alt.Y(
                        "mean:Q",
                        title="Avg Next-Day Recovery",
                        scale=alt.Scale(domain=[0, 100]),
                    ),
                    color=alt.Color(
                        "had_recovery:N",
                        legend=None,
                        scale=alt.Scale(range=["#4472CA", "#D9D9D9"]),
                    ),
                    tooltip=[
                        alt.Tooltip("label:N", title="Group"),
                        alt.Tooltip("mean:Q", format=".1f", title="Avg Recovery"),
                        alt.Tooltip("count:Q", title="Days"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(ww_bar, width="stretch")
    else:
        st.info("Not enough data to compare recovery vs non-recovery days.")

    st.divider()

    # ── 5. DURATION vs NEXT-DAY RECOVERY SCATTER ─────────────────────────────
    st.subheader("Duration vs Next-Day Recovery")

    scatter_df = df[df["next_day_recovery"].notna()].copy()
    if len(scatter_df) < 3:
        st.info("Not enough paired data for this chart.")
    else:
        scatter = (
            alt.Chart(scatter_df)
            .mark_circle(size=80, opacity=0.8)
            .encode(
                x=alt.X("dur_min:Q", title="Session Duration (min)", scale=alt.Scale(zero=True)),
                y=alt.Y(
                    "next_day_recovery:Q",
                    title="Next-Day Recovery",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                color=alt.Color(
                    "activity:N",
                    title="Activity",
                    scale=alt.Scale(range=_TYPE_COLORS),
                ),
                tooltip=[
                    alt.Tooltip("date:T", format="%b %d", title="Date"),
                    alt.Tooltip("activity:N", title="Activity"),
                    alt.Tooltip("dur_min:Q", format=".0f", title="Duration (min)"),
                    alt.Tooltip("next_day_recovery:Q", format=".0f", title="Next-Day Recovery"),
                    alt.Tooltip("same_day_recovery:Q", format=".0f", title="Same-Day Recovery"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(scatter, width="stretch")
        st.caption(
            "Each dot is one session. Look for an upward trend — longer sessions correlating "
            "with higher next-day recovery."
        )

    st.divider()

    # ── 6. NEXT-DAY RECOVERY BY ACTIVITY TYPE ────────────────────────────────
    st.subheader("Next-Day Recovery by Activity Type")

    type_recovery = (
        df[df["next_day_recovery"].notna()]
        .groupby("activity")["next_day_recovery"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "avg_next_recovery", "count": "n"})
        .sort_values("avg_next_recovery", ascending=False)
    )

    if type_recovery.empty:
        st.info("No next-day recovery data to compare.")
    else:
        type_bar = (
            alt.Chart(type_recovery)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X(
                    "activity:N",
                    sort="-y",
                    title=None,
                    axis=alt.Axis(labelAngle=-20),
                ),
                y=alt.Y(
                    "avg_next_recovery:Q",
                    title="Avg Next-Day Recovery",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                color=alt.Color(
                    "activity:N",
                    legend=None,
                    scale=alt.Scale(range=_TYPE_COLORS),
                ),
                tooltip=[
                    alt.Tooltip("activity:N", title="Activity"),
                    alt.Tooltip("avg_next_recovery:Q", format=".1f", title="Avg Next-Day Recovery"),
                    alt.Tooltip("n:Q", title="Sessions"),
                ],
            )
            .properties(height=240)
        )
        st.altair_chart(type_bar, width="stretch")
        st.caption("Average next-day recovery score following each activity type.")

    st.divider()

    # ── 7. SLEEP PERFORMANCE AFTER RECOVERY ACTIVITY ─────────────────────────
    st.subheader("Next-Day Sleep Performance by Activity Type")

    sleep_df = df[df["next_day_sleep_perf"].notna()].copy()
    if sleep_df.empty:
        st.info("No sleep performance data available for this period.")
    else:
        sleep_summary = (
            sleep_df.groupby("activity")["next_day_sleep_perf"]
            .agg(["mean", "count"])
            .reset_index()
            .rename(columns={"mean": "avg_sleep_perf", "count": "n"})
            .sort_values("avg_sleep_perf", ascending=False)
        )
        sleep_bar = (
            alt.Chart(sleep_summary)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X(
                    "activity:N",
                    sort="-y",
                    title=None,
                    axis=alt.Axis(labelAngle=-20),
                ),
                y=alt.Y(
                    "avg_sleep_perf:Q",
                    title="Avg Sleep Performance (%)",
                    scale=alt.Scale(domain=[0, 100]),
                ),
                color=alt.Color(
                    "activity:N",
                    legend=None,
                    scale=alt.Scale(range=_TYPE_COLORS),
                ),
                tooltip=[
                    alt.Tooltip("activity:N", title="Activity"),
                    alt.Tooltip("avg_sleep_perf:Q", format=".1f", title="Avg Sleep Performance"),
                    alt.Tooltip("n:Q", title="Sessions"),
                ],
            )
            .properties(height=240)
        )
        st.altair_chart(sleep_bar, width="stretch")
        st.caption("Whoop sleep performance score on the night following each activity type.")

    st.divider()

    # ── 8. ACTIVITY LOG ───────────────────────────────────────────────────────
    st.subheader("Activity Log")

    log_df = df[["date", "activity", "dur_min", "same_day_recovery", "next_day_recovery", "next_day_sleep_perf"]].copy()
    log_df.columns = ["Date", "Activity", "Duration (min)", "Same-Day Recovery", "Next-Day Recovery", "Next-Day Sleep %"]
    log_df["Duration (min)"] = log_df["Duration (min)"].round(0).astype("Int64")
    log_df["Same-Day Recovery"] = log_df["Same-Day Recovery"].round(0)
    log_df["Next-Day Recovery"] = log_df["Next-Day Recovery"].round(0)
    log_df["Next-Day Sleep %"] = log_df["Next-Day Sleep %"].round(0)

    st.dataframe(log_df.reset_index(drop=True), width="stretch", hide_index=True)
