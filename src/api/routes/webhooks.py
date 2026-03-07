"""Whoop webhook receiver.

Whoop sends a POST to this endpoint whenever a resource (cycle, recovery,
sleep, workout) is created or updated.  We acknowledge immediately with 200,
then fetch the updated record from the Whoop API and upsert it in a
FastAPI BackgroundTask so Whoop never waits on our DB operations.

Event types handled
-------------------
  cycle.updated    → GET /cycle/{id}               → upsert WhoopCycle
  recovery.updated → GET /recovery/{id}            → upsert WhoopRecovery
  sleep.updated    → GET /activity/sleep/{id}      → upsert WhoopSleep
  workout.updated  → GET /activity/workout/{id}    → upsert WhoopWorkout

All four paths call normalize_all() on a ±1-day window around the affected
date so the unified tables stay current immediately.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import Engine

from src.api.dependencies import get_engine_dep
from src.clients.whoop_client import WhoopClient
from src.database.connection import get_session_factory
from src.database.models import SyncLog, WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout
from src.ingestion.whoop_pipeline import (
    transform_cycle,
    transform_recovery,
    transform_sleep,
    transform_workout,
)
from src.normalization.normalizer import Normalizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECOGNIZED_TYPES: frozenset[str] = frozenset(
    {"cycle.updated", "recovery.updated", "sleep.updated", "workout.updated"}
)

# event_type → (api_path_template, ORM model class, transform function)
_DISPATCH: dict[str, tuple] = {
    "cycle.updated": ("/cycle/{id}", WhoopCycle, transform_cycle),
    "recovery.updated": ("/recovery/{id}", WhoopRecovery, transform_recovery),
    "sleep.updated": ("/activity/sleep/{id}", WhoopSleep, transform_sleep),
    "workout.updated": ("/activity/workout/{id}", WhoopWorkout, transform_workout),
}


# ---------------------------------------------------------------------------
# Pydantic request model
# ---------------------------------------------------------------------------


class WhoopWebhookEvent(BaseModel):
    """Payload Whoop sends on every resource change."""

    user_id: int
    id: str  # resource ID — cycle/sleep/workout int or UUID, always stringified
    type: str  # e.g. "recovery.updated"
    trace_id: str  # Whoop-generated correlation ID for debugging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_date(event_type: str, record: dict) -> date:
    """Pull the calendar date that should be re-normalized from a fetched record."""
    # Sleep: use wake-up time (end), not bedtime
    time_str = record.get("end") if event_type == "sleep.updated" else record.get("start")
    if time_str:
        try:
            return datetime.fromisoformat(time_str[:10]).date()
        except ValueError:
            pass
    return date.today()


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------


async def _process_webhook(event: WhoopWebhookEvent, engine: Engine) -> None:
    """Fetch the updated resource, upsert it, re-normalize, log result.

    Runs as a FastAPI BackgroundTask after the 200 response has been sent.
    All exceptions are caught and recorded in sync_log so a failure here
    never surfaces as an unhandled error in the worker.
    """
    api_path_tmpl, orm_model, transform_fn = _DISPATCH[event.type]
    api_path = api_path_tmpl.format(id=event.id)
    fetched_at = datetime.now(UTC).isoformat()

    SessionFactory = get_session_factory(engine)
    db = SessionFactory()
    log = SyncLog(
        source="whoop_webhook",
        sync_type="webhook",
        started_at=fetched_at,
        status="running",
    )
    db.add(log)
    db.commit()

    try:
        # Fetch the single updated resource
        client = WhoopClient(db)
        record = await client._request(api_path)  # noqa: SLF001

        # Transform → upsert (idempotent: merge by PK)
        data = transform_fn(record, fetched_at)
        existing = db.get(orm_model, data["id"])
        if existing is None:
            db.add(orm_model(**data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        db.commit()

        # Re-normalize a ±1-day window around the affected date
        event_date = _extract_date(event.type, record)
        normalizer = Normalizer(db)
        normalizer.normalize_all(event_date - timedelta(days=1), event_date + timedelta(days=1))

        log.status = "success"
        log.records_fetched = 1
        log.records_stored = 1
        log.completed_at = datetime.now(UTC).isoformat()
        db.commit()

        logger.info(
            "Webhook OK — type=%s id=%s trace=%s date=%s",
            event.type,
            event.id,
            event.trace_id,
            event_date,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Webhook failed — type=%s id=%s trace=%s: %s",
            event.type,
            event.id,
            event.trace_id,
            exc,
        )
        try:
            log.status = "error"
            log.error_message = str(exc)
            log.completed_at = datetime.now(UTC).isoformat()
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints — GET /test before POST / to avoid path shadowing
# ---------------------------------------------------------------------------


@router.get(
    "/whoop/test",
    summary="Webhook health check",
    description="Returns 200. Used by Whoop's Developer Dashboard to verify the endpoint.",
)
async def whoop_webhook_test() -> dict:
    return {"status": "ok"}


@router.post(
    "/whoop",
    status_code=200,
    summary="Receive a Whoop webhook event",
    description=(
        "Called by Whoop when a cycle, recovery, sleep, or workout record changes. "
        "Responds immediately with 200; data fetch and upsert run in the background."
    ),
)
async def whoop_webhook(
    event: WhoopWebhookEvent,
    background_tasks: BackgroundTasks,
    engine: Engine = Depends(get_engine_dep),
) -> dict:
    if event.type not in _RECOGNIZED_TYPES:
        # Return 200 anyway — Whoop must not retry unknown types indefinitely
        logger.warning("Ignored unrecognized webhook type=%s id=%s", event.type, event.id)
        return {"status": "ignored", "reason": f"unrecognized type '{event.type}'"}

    background_tasks.add_task(_process_webhook, event, engine)
    logger.info("Webhook accepted — type=%s id=%s trace=%s", event.type, event.id, event.trace_id)
    return {"status": "accepted", "type": event.type, "id": event.id}
