"""Incremental anomaly computation and storage.

After each sync, ``refresh_anomalies`` recomputes anomalies for the synced
date range and upserts them into the ``anomaly_cache`` table. The API reads
from this table instead of recomputing on every page load.

Public API
----------
refresh_anomalies(engine, user_id, start_date, end_date)
    Recompute and store anomalies for the given range.

get_cached_anomalies(engine, user_id, start_date, end_date)
    Read pre-computed anomalies from the cache.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

from sqlalchemy import Engine, text

from src.analytics.trends import (
    _ENRICHED_ANOMALY_METRICS,
    _ENRICHED_METRIC_LABELS,
    _batch_fetch_recovery_ctx,
    _batch_fetch_sleep_ctx,
    _batch_fetch_training_ctx,
    _build_enriched_explanation,
    get_batch_metric_trends,
)

logger = logging.getLogger(__name__)


def refresh_anomalies(
    engine: Engine,
    user_id: str,
    start_date: date,
    end_date: date,
) -> int:
    """Recompute anomalies for [start_date, end_date] and upsert into anomaly_cache.

    Deletes existing entries in the range before inserting fresh ones so
    that resolved anomalies disappear.

    Args:
        engine: SQLAlchemy engine.
        user_id: App user UUID.
        start_date: First date (inclusive).
        end_date: Last date (inclusive).

    Returns:
        Number of anomalies stored.
    """
    # 1. Batch-fetch all metric trends
    try:
        trends = get_batch_metric_trends(
            engine, list(_ENRICHED_ANOMALY_METRICS), start_date, end_date, user_id
        )
    except Exception:  # noqa: BLE001
        logger.warning("refresh_anomalies: batch trend fetch failed for user %s", user_id)
        return 0

    # 2. Collect raw anomalies
    raw_pairs: list[tuple[str, dict]] = []
    for metric in _ENRICHED_ANOMALY_METRICS:
        trend = trends.get(metric)
        if trend is None:
            continue
        for a in trend.anomalies:
            raw_pairs.append((metric, a))

    if not raw_pairs:
        # Clear stale anomalies in this range
        _delete_range(engine, user_id, start_date, end_date)
        return 0

    # 3. Build co-anomaly map
    co_map: dict[str, list[str]] = {}
    for metric, a in raw_pairs:
        lbl = _ENRICHED_METRIC_LABELS.get(metric, metric)
        co_map.setdefault(a["date"], []).append(lbl)

    # 4. Batch-fetch context
    anomaly_dates = sorted({date.fromisoformat(a["date"]) for _, a in raw_pairs})
    training_cache = _batch_fetch_training_ctx(engine, user_id, anomaly_dates)
    sleep_cache = _batch_fetch_sleep_ctx(engine, user_id, anomaly_dates)
    recovery_cache = _batch_fetch_recovery_ctx(engine, user_id, anomaly_dates)

    # 5. Build rows
    now_iso = datetime.now(tz=UTC).isoformat()
    rows: list[dict] = []
    for metric, a in raw_pairs:
        d_iso = a["date"]
        metric_label = _ENRICHED_METRIC_LABELS.get(metric, metric)
        severity = abs(a["severity"])
        same_day = co_map.get(d_iso, [])
        co_anomalies = [lbl for lbl in same_day if lbl != metric_label]

        context = {
            "training_48h": training_cache.get(d_iso, {"total_strain": None, "workout_count": 0}),
            "sleep_prior_night": sleep_cache.get(
                d_iso, {"duration_hours": None, "quality_pct": None, "deep_pct": None}
            ),
            "recovery_trend": recovery_cache.get(d_iso, "stable"),
            "co_anomalies": co_anomalies,
        }
        explanation = _build_enriched_explanation(
            metric, metric_label, a["value"], a["direction"], severity, context
        )
        rows.append(
            {
                "user_id": user_id,
                "date": d_iso,
                "metric": metric,
                "metric_label": metric_label,
                "value": a["value"],
                "direction": a["direction"],
                "severity": round(severity, 2),
                "context_json": json.dumps(context),
                "explanation": explanation,
                "computed_at": now_iso,
            }
        )

    # 6. Delete old + insert new (within a transaction)
    _delete_range(engine, user_id, start_date, end_date)
    if rows:
        _insert_rows(engine, rows)

    logger.info(
        "refresh_anomalies: stored %d anomalies for user %s (%s → %s)",
        len(rows),
        user_id,
        start_date,
        end_date,
    )
    return len(rows)


def get_cached_anomalies(
    engine: Engine,
    user_id: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Read pre-computed anomalies from the cache.

    Returns a list of dicts matching the AnomalyItem response shape:
    {date, metric, value, direction, severity}.

    Falls back to empty list if the table doesn't exist yet.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT date, metric_label, value, direction, severity"
                    " FROM anomaly_cache"
                    " WHERE user_id = :uid AND date >= :s AND date <= :e"
                    " ORDER BY date DESC, severity DESC"
                ),
                {"uid": user_id, "s": start_date.isoformat(), "e": end_date.isoformat()},
            ).fetchall()
        return [
            {
                "date": r[0],
                "metric": r[1],
                "value": float(r[2]),
                "direction": r[3],
                "severity": float(r[4]),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        # Table may not exist yet (pre-migration)
        return []


def get_cached_enriched_anomalies(
    engine: Engine,
    user_id: str,
    start_date: date,
    end_date: date,
    limit: int = 20,
) -> list[dict]:
    """Read pre-computed enriched anomalies from the cache.

    Returns dicts with all enriched fields including context and explanation.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT date, metric, metric_label, value, direction, severity,"
                    " context_json, explanation"
                    " FROM anomaly_cache"
                    " WHERE user_id = :uid AND date >= :s AND date <= :e"
                    " ORDER BY date DESC, severity DESC"
                    " LIMIT :lim"
                ),
                {
                    "uid": user_id,
                    "s": start_date.isoformat(),
                    "e": end_date.isoformat(),
                    "lim": limit,
                },
            ).fetchall()
        return [
            {
                "date": r[0],
                "metric": r[1],
                "metric_label": r[2],
                "value": float(r[3]),
                "direction": r[4],
                "severity": float(r[5]),
                "context": json.loads(r[6]) if r[6] else {},
                "explanation": r[7] or "",
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def _delete_range(engine: Engine, user_id: str, start: date, end: date) -> None:
    """Delete cached anomalies for a user in a date range."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM anomaly_cache WHERE user_id = :uid AND date >= :s AND date <= :e"
                ),
                {"uid": user_id, "s": start.isoformat(), "e": end.isoformat()},
            )
    except Exception:  # noqa: BLE001
        pass  # Table may not exist yet


def _insert_rows(engine: Engine, rows: list[dict]) -> None:
    """Batch-insert anomaly rows."""
    with engine.begin() as conn:
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO anomaly_cache"
                    " (user_id, date, metric, metric_label, value, direction,"
                    "  severity, context_json, explanation, computed_at)"
                    " VALUES (:user_id, :date, :metric, :metric_label, :value,"
                    "  :direction, :severity, :context_json, :explanation, :computed_at)"
                    " ON CONFLICT (user_id, date, metric) DO UPDATE SET"
                    "  value = EXCLUDED.value, direction = EXCLUDED.direction,"
                    "  severity = EXCLUDED.severity, context_json = EXCLUDED.context_json,"
                    "  explanation = EXCLUDED.explanation, computed_at = EXCLUDED.computed_at"
                ),
                r,
            )
