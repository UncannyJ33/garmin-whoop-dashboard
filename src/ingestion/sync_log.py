"""Shared ``SyncLog`` lifecycle helpers for the Whoop and Garmin pipelines."""

import json
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from src.database.models import SyncLog


def start_sync_log(
    db: Session,
    source: str,
    *,
    manual: bool,
    user_id: str | None,
    sync_start: date | datetime,
    sync_end: date | datetime,
) -> SyncLog:
    """Create and commit a ``running`` SyncLog row recording the sync window."""
    log = SyncLog(
        source=source,
        sync_type="manual" if manual else "incremental",
        started_at=datetime.now(tz=UTC).isoformat(),
        status="running",
        user_id=user_id,
        metadata_json=json.dumps(
            {
                "sync_start": sync_start.isoformat(),
                "sync_end": sync_end.isoformat(),
            }
        ),
    )
    db.add(log)
    db.commit()
    return log


def mark_sync_error(log: SyncLog, exc: Exception) -> None:
    """Set the error fields on ``log`` (the caller commits)."""
    log.status = "error"
    log.error_message = str(exc)
    log.completed_at = datetime.now(tz=UTC).isoformat()
