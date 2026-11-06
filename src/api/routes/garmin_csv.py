"""POST /api/garmin/csv-import — Garmin Connect activities CSV upload.

Provides a credential-free fallback for users who do not want to store their
Garmin email/password in PulseEngine.  The user exports their activities from
Garmin Connect (Activities page → Export CSV) and uploads the file here.

Behaviour
---------
- Accepts ``multipart/form-data`` with ``file`` (CSV) and ``units``
  (``"miles"`` | ``"km"``; default ``"miles"``).
- Hard limit: 2 000 rows per upload (matches Garmin's own per-export ceiling).
  Users with more history export in date-range batches; the deduplication
  logic makes re-uploads idempotent.
- Deduplicates against existing ``garmin_activities`` rows for the same user:
  same activity_type + start_time within ±5 min + duration within ±10 %.
  The CSV-import path is designed for users without API sync, so duplicates
  are rare, but handled correctly when they occur.
- After upserting, runs ``Normalizer.normalize_all()`` over the date span of
  the imported rows so that ``unified_workouts`` is populated immediately.
- Training load for non-power-meter activities is derived from
  ``Aerobic TE × duration_minutes`` (Garmin only populates TSS for
  power-metered cycling).  The API response includes a note about this.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_engine_dep
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.ingestion.garmin_csv_parser import MAX_ROWS, parse_activities_csv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/garmin", tags=["garmin-csv"])

# ---------------------------------------------------------------------------
# Deduplication constants
# ---------------------------------------------------------------------------

_DUP_TIME_WINDOW = timedelta(minutes=5)
_DUP_DURATION_TOLERANCE = 0.10  # ±10 % of the longer duration


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class CSVImportResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    skipped_errors: int
    date_range: str | None
    training_load_note: str
    row_errors: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(val: str | None) -> datetime | None:
    """Parse an ISO-ish datetime string; returns None on failure."""
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val[:19], fmt)
        except ValueError:
            continue
    return None


def _is_duplicate(
    new_start: datetime,
    new_duration: float | None,
    new_type: str,
    existing: list[dict],
) -> bool:
    """Return True if *any* existing row is a near-match for the candidate row."""
    for ex in existing:
        if ex["activity_type"] != new_type:
            continue
        ex_start = _parse_dt(ex["start_time"])
        if ex_start is None:
            continue
        if abs(new_start - ex_start) > _DUP_TIME_WINDOW:
            continue
        # Start times match — check duration
        ex_dur = ex["duration_seconds"]
        if new_duration is None or ex_dur is None:
            return True  # type + time match is enough
        longer = max(new_duration, float(ex_dur))
        if longer == 0 or abs(new_duration - float(ex_dur)) / longer <= _DUP_DURATION_TOLERANCE:
            return True
    return False


def _fetch_existing(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Load existing garmin_activities rows for the user in the date window."""
    rows = (
        db.execute(
            text(
                """
            SELECT activity_type, start_time, duration_seconds
            FROM garmin_activities
            WHERE user_id = :uid
              AND start_time >= :lo
              AND start_time <= :hi
            """
            ),
            {
                "uid": user_id,
                "lo": start_date.isoformat(),
                "hi": (end_date + timedelta(days=1)).isoformat(),
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/csv-import",
    response_model=CSVImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Import Garmin Connect activities from a CSV export",
)
async def garmin_csv_import(
    file: UploadFile = File(..., description="Garmin Connect Activities CSV export"),
    units: str = Form(default="miles", description='"miles" or "km"'),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    engine: Engine = Depends(get_engine_dep),
) -> CSVImportResponse:
    """Upload a Garmin Connect activities CSV and import into the database.

    **How to export from Garmin Connect:**
    1. Open [connect.garmin.com](https://connect.garmin.com) → Activities
    2. Click the export icon → "Export to CSV"
    3. Upload the downloaded file here

    **Units:** Match the distance unit shown in your Garmin Connect settings
    (Activity Settings → Units).  Defaults to miles.

    **Row limit:** {MAX_ROWS} rows per upload.  For larger histories, filter
    by date range in Garmin Connect before exporting and upload in batches.
    Re-uploads are idempotent — duplicates are detected and skipped.
    """.replace("{MAX_ROWS}", str(MAX_ROWS))

    # Validate units
    if units not in ("miles", "km"):
        raise HTTPException(status_code=400, detail='units must be "miles" or "km"')

    # Read file
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Parse
    try:
        parsed_rows, parse_errors = parse_activities_csv(
            content, units=units, user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File encoding not recognised. Save the file as UTF-8 and try again.",
        )

    if not parsed_rows and not parse_errors:
        raise HTTPException(status_code=400, detail="CSV file contains no data rows")

    # Determine date range across all parsed rows
    dates: list[date] = []
    for row in parsed_rows:
        dt = _parse_dt(row["start_time"])
        if dt:
            dates.append(dt.date())

    if not dates:
        return CSVImportResponse(
            imported=0,
            skipped_duplicates=0,
            skipped_errors=len(parse_errors),
            date_range=None,
            training_load_note=_training_load_note(parsed_rows),
            row_errors=[repr(e) for e in parse_errors[:20]],
        )

    span_start = min(dates)
    span_end = max(dates)

    # Load existing activities in that window for deduplication
    existing = _fetch_existing(db, current_user.id, span_start, span_end)

    # Upsert non-duplicate rows
    imported = 0
    skipped_dup = 0
    now_iso = datetime.now(UTC).isoformat()

    for row in parsed_rows:
        new_start = _parse_dt(row["start_time"])
        if new_start is None:
            continue

        if _is_duplicate(new_start, row.get("duration_seconds"), row["activity_type"], existing):
            skipped_dup += 1
            logger.debug(
                "CSV import: skipped duplicate %s at %s for user %s",
                row["activity_type"],
                row["start_time"],
                current_user.id,
            )
            continue

        # Build INSERT OR REPLACE (SQLite) / ON CONFLICT DO UPDATE (PostgreSQL)
        # via a simple merge using SQLAlchemy ORM
        from src.database.models import GarminActivity  # local import avoids circularity

        obj = GarminActivity(
            activity_id=row["activity_id"],
            activity_type=row["activity_type"],
            activity_name=row["activity_name"],
            start_time=row["start_time"],
            start_time_gmt=row["start_time_gmt"],
            duration_seconds=row["duration_seconds"],
            elapsed_seconds=row["elapsed_seconds"],
            distance_meters=row["distance_meters"],
            avg_heart_rate=row["avg_heart_rate"],
            max_heart_rate=row["max_heart_rate"],
            avg_running_cadence=row["avg_running_cadence"],
            max_running_cadence=row["max_running_cadence"],
            calories=row["calories"],
            avg_speed=row["avg_speed"],
            max_speed=row["max_speed"],
            elevation_gain=row["elevation_gain"],
            elevation_loss=row["elevation_loss"],
            avg_stride_length=row["avg_stride_length"],
            vo2_max=row["vo2_max"],
            training_effect_aerobic=row["training_effect_aerobic"],
            training_effect_anaerobic=row["training_effect_anaerobic"],
            training_load=row["training_load"],
            avg_ground_contact_time=row["avg_ground_contact_time"],
            avg_vertical_oscillation=row["avg_vertical_oscillation"],
            avg_vertical_ratio=row["avg_vertical_ratio"],
            avg_ground_contact_balance=row["avg_ground_contact_balance"],
            fetched_at=now_iso,
            raw_json=None,
            user_id=current_user.id,
        )
        db.merge(obj)
        imported += 1

    if imported > 0:
        db.commit()
        logger.info(
            "CSV import: %d rows imported, %d duplicates skipped for user %s (%s → %s)",
            imported,
            skipped_dup,
            current_user.id,
            span_start,
            span_end,
        )

        # Run normalization over the imported date span so unified_workouts is
        # populated immediately and the Training / Today pages reflect the data.
        try:
            from src.normalization.normalizer import Normalizer

            with Session(engine) as norm_db:
                n = Normalizer(norm_db, user_id=current_user.id)
                n.normalize_all(span_start, span_end)
        except Exception as exc:  # noqa: BLE001
            # Normalization failure is non-fatal — data is in garmin_activities,
            # the next scheduled normalize pass will catch it.
            logger.warning("CSV import: normalization failed (non-fatal): %s", exc)
    else:
        db.rollback()

    return CSVImportResponse(
        imported=imported,
        skipped_duplicates=skipped_dup,
        skipped_errors=len(parse_errors),
        date_range=f"{span_start} → {span_end}" if dates else None,
        training_load_note=_training_load_note(parsed_rows),
        row_errors=[repr(e) for e in parse_errors[:20]],
    )


def _training_load_note(rows: list[dict]) -> str:
    derived = sum(
        1
        for r in rows
        if r.get("training_load") is not None and r.get("activity_id", "").startswith("csv_")
    )
    if derived:
        return (
            "Training load values are derived for CSV imports "
            "(Aerobic Training Effect × duration). Garmin only includes "
            "true Training Stress Score in CSV exports for power-metered cycling."
        )
    return "No training load data found in this file."
