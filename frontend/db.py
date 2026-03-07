"""Shared database connection helper for the Streamlit frontend."""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from sqlalchemy import Engine, text

from src.database.connection import get_engine as _get_engine


@st.cache_resource
def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the dashboard."""
    return _get_engine()


@st.cache_data(ttl=30)
def get_last_sync_info() -> dict[str, dict]:
    """Return last successful sync info and staleness flags for each source.

    Returns a dict keyed by source name with keys:
        last_sync_at (str), age_minutes (float), is_stale (bool).
    """
    try:
        with get_engine().connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT source, MAX(completed_at) AS last_sync"
                        " FROM sync_log WHERE status = 'success'"
                        " GROUP BY source"
                    )
                )
                .mappings()
                .all()
            )
    except Exception:  # noqa: BLE001
        return {}

    now = datetime.now(UTC)
    result: dict[str, dict] = {}
    for row in rows:
        raw = row["last_sync"]
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age_min = (now - dt).total_seconds() / 60
            result[row["source"]] = {
                "last_sync_at": raw,
                "age_minutes": age_min,
                "is_stale": age_min > 30,
            }
        except (ValueError, TypeError):
            continue
    return result


def render_sync_status() -> None:
    """Render a compact sync-status line in the Streamlit sidebar.

    Shows how long ago each source last synced, with a warning icon when
    the data is stale (> 30 minutes old).
    """
    info = get_last_sync_info()
    if not info:
        return

    parts: list[str] = []
    for src in ("whoop", "garmin"):
        if src not in info:
            continue
        age = info[src]["age_minutes"]
        label = f"{age:.0f}m ago" if age < 60 else f"{age / 60:.1f}h ago"
        stale_mark = " ⚠" if info[src]["is_stale"] else ""
        parts.append(f"{src.title()}: {label}{stale_mark}")

    if parts:
        st.sidebar.caption("Last synced — " + " · ".join(parts))
