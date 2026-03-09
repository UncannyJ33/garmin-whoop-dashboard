"""Data Sources page — sync log and source status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import text

from frontend.db import get_engine

_QUERY_LAST_SYNC = """
SELECT source, MAX(completed_at) AS last_success, SUM(records_stored) AS total_stored
FROM sync_log
WHERE status = 'success'
GROUP BY source
"""

_QUERY_RECENT = """
SELECT id, source, sync_type, started_at, completed_at,
       records_fetched, records_stored, status, error_message
FROM sync_log
ORDER BY id DESC
LIMIT 50
"""


@st.cache_data(ttl=60)
def _load() -> tuple[pd.DataFrame, pd.DataFrame]:
    with get_engine().connect() as conn:
        last_sync = pd.read_sql(text(_QUERY_LAST_SYNC), conn)
        recent = pd.read_sql(text(_QUERY_RECENT), conn)
    return last_sync, recent


def render() -> None:
    st.title("Data Sources")

    try:
        _render_body()
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Failed to load data source info. This may be a temporary database issue. "
            f"Details: `{exc}`"
        )


def _render_body() -> None:
    last_sync, recent = _load()

    # ── Last Successful Sync ───────────────────────────────────────────────
    st.subheader("Last Successful Sync")
    col1, col2, col3 = st.columns(3)
    sources = ["whoop", "garmin", "csv_import"]
    labels = ["Whoop", "Garmin", "CSV Import"]
    cols = [col1, col2, col3]

    sync_map = last_sync.set_index("source").to_dict("index") if not last_sync.empty else {}

    for col, source, label in zip(cols, sources, labels):
        with col:
            row = sync_map.get(source)
            if row and row["last_success"]:
                ts = pd.to_datetime(row["last_success"]).strftime("%b %d %H:%M")
                total = int(row["total_stored"]) if pd.notna(row["total_stored"]) else 0
                st.metric(label, ts, delta=f"{total:,} records total", delta_color="off")
            else:
                st.metric(label, "Never")

    st.divider()

    # ── Errors ────────────────────────────────────────────────────────────
    st.subheader("Sync Errors")
    errors = recent[recent["status"] == "error"] if not recent.empty else pd.DataFrame()
    if errors.empty:
        st.success("No sync errors.")
    else:
        for _, row in errors.iterrows():
            st.error(
                f"**{row['source']}** ({row['sync_type']}) at {row['started_at']}: "
                f"{row['error_message'] or 'Unknown error'}"
            )

    st.divider()

    # ── Recent Syncs ──────────────────────────────────────────────────────
    st.subheader("Recent Syncs")
    if recent.empty:
        st.info("No sync history found.")
    else:
        st.dataframe(recent, width='stretch')
