"""Shared database connection helper for the Streamlit frontend."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from sqlalchemy import Engine

from src.database.connection import get_engine as _get_engine


@st.cache_resource
def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the dashboard."""
    return _get_engine()
