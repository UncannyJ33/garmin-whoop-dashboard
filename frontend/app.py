"""Main Streamlit app — fitness dashboard entry point.

Run with:
    streamlit run frontend/app.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root and frontend/ are importable
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))  # config/, src/
sys.path.insert(0, str(_root / "frontend"))  # views/

import streamlit as st  # noqa: E402
from views import (  # noqa: E402
    activities,
    data_sources,
    readiness,
    recovery_activities,
    sleep,
    trends,
    workouts,
)

from config.settings import settings  # noqa: E402
from frontend.db import render_sync_status  # noqa: E402
from src.logging_config import configure_logging  # noqa: E402

configure_logging(settings.log_level)

st.set_page_config(
    page_title="Fitness Dashboard",
    page_icon="💪",
    layout="wide",
)

# ── Sidebar ────────────────────────────────────────────────────────────────
st.sidebar.title("Fitness Dashboard")
st.sidebar.caption("Whoop · Garmin")

page = st.sidebar.radio(
    "Page",
    [
        "Recovery",
        "Sleep",
        "Workouts",
        "Recovery Activities",
        "Trends",
        "Activities",
        "Data Sources",
    ],
)

render_sync_status()

st.sidebar.divider()
st.sidebar.subheader("Date Range")

today = date.today()
default_start = today - timedelta(days=30)

start_date: date = st.sidebar.date_input("From", value=default_start, max_value=today)
end_date: date = st.sidebar.date_input("To", value=today, max_value=today)

if start_date > end_date:
    st.sidebar.error("Start date must be before end date.")
    st.stop()

# ── Page routing ───────────────────────────────────────────────────────────
if page == "Recovery":
    readiness.render(start_date, end_date)
elif page == "Sleep":
    sleep.render(start_date, end_date)
elif page == "Workouts":
    workouts.render(start_date, end_date)
elif page == "Recovery Activities":
    recovery_activities.render(start_date, end_date)
elif page == "Trends":
    trends.render(start_date, end_date)
elif page == "Activities":
    activities.render(start_date, end_date)
elif page == "Data Sources":
    data_sources.render()
