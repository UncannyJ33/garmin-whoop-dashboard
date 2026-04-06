"""Migration 013: Create anomaly_cache table for pre-computed anomalies.

Anomalies are computed incrementally after each sync and stored here.
The /api/trends/anomalies endpoint reads from this table instead of
recomputing from scratch on every page load.

Table schema:
  - id: auto-increment PK
  - user_id: TEXT (app user UUID)
  - date: TEXT (YYYY-MM-DD of the anomalous day)
  - metric: TEXT (internal key, e.g. "hrv")
  - metric_label: TEXT (human-readable, e.g. "HRV")
  - value: REAL (raw metric value)
  - direction: TEXT ("high" or "low")
  - severity: REAL (absolute z-score)
  - context_json: TEXT (JSON — training_48h, sleep_prior_night, recovery_trend, co_anomalies)
  - explanation: TEXT (one-sentence natural-language summary)
  - computed_at: TEXT (ISO 8601 timestamp)
  - UNIQUE(user_id, date, metric) — one anomaly per user+date+metric

Idempotent: checks if table exists before creating.
"""

import logging

from sqlalchemy import Engine, inspect, text

from src.database.connection import get_engine

logger = logging.getLogger(__name__)

_TABLE = "anomaly_cache"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS anomaly_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    value REAL NOT NULL,
    direction TEXT NOT NULL,
    severity REAL NOT NULL,
    context_json TEXT,
    explanation TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(user_id, date, metric)
)
"""

_CREATE_SQL_PG = """
CREATE TABLE IF NOT EXISTS anomaly_cache (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    direction TEXT NOT NULL,
    severity DOUBLE PRECISION NOT NULL,
    context_json TEXT,
    explanation TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(user_id, date, metric)
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_anomaly_cache_user_date ON anomaly_cache(user_id, date)",
]


def run(database_url: str | None = None, engine: Engine | None = None) -> None:
    eng = engine or get_engine(database_url)
    db_url = str(eng.url)
    is_pg = "postgresql" in db_url

    existing = inspect(eng).get_table_names()
    if _TABLE in existing:
        logger.info("Migration 013: %s already exists — skipping", _TABLE)
        return

    with eng.begin() as conn:
        conn.execute(text(_CREATE_SQL_PG if is_pg else _CREATE_SQL))
        for idx_sql in _INDEX_SQL:
            conn.execute(text(idx_sql))

    logger.info("Migration 013: %s table created on %s", _TABLE, db_url)
