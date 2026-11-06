"""POST /api/garmin/upload — unified Garmin data upload endpoint.

Accepts three file formats in one endpoint:
  - **CSV** — Garmin Connect Activities export (same format as /api/garmin/csv-import)
  - **JSON** — Garmin summarized activities JSON from a bulk export
  - **ZIP** — Full Garmin Connect account export (downloaded from Account Settings →
    Export Your Data); the ZIP is unpacked and all recognised JSON/CSV files are imported

Size limit: 50 MB per upload.

Format detection
----------------
Format is detected from the uploaded filename extension:
  ``.csv`` → CSV path (parse_activities_csv + dedup)
  ``.json`` → JSON path (GarminImporter)
  ``.zip`` → ZIP path (GarminImporter, extracts and recurses)
  Any other extension → 400 Unsupported file type

The CSV path applies the same deduplication logic as /api/garmin/csv-import
(same activity_type + start_time ±5 min + duration ±10 %).  The JSON/ZIP paths
use the Garmin activity_id as the natural primary key, so re-uploads are
idempotent via upsert.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_engine_dep
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.ingestion.csv_import import GarminImporter
from src.ingestion.garmin_csv_parser import parse_activities_csv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/garmin", tags=["garmin-upload"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
_SUPPORTED_EXTENSIONS = {".csv", ".json", ".zip"}

_DUP_TIME_WINDOW = timedelta(minutes=5)
_DUP_DURATION_TOLERANCE = 0.10


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    skipped_errors: int
    format_detected: str  # "csv" | "json" | "zip"
    date_range: str | None
    warnings: list[str]
    training_load_note: str | None


# ---------------------------------------------------------------------------
# CSV-path helpers (mirrors garmin_csv.py dedup logic)
# ---------------------------------------------------------------------------


def _parse_dt(val: str | None) -> datetime | None:
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
    for ex in existing:
        if ex["activity_type"] != new_type:
            continue
        ex_start = _parse_dt(str(ex["start_time"]) if ex["start_time"] else None)
        if ex_start is None:
            continue
        if abs(new_start - ex_start) > _DUP_TIME_WINDOW:
            continue
        ex_dur = ex["duration_seconds"]
        if new_duration is None or ex_dur is None:
            return True
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
    rows = db.execute(
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
    ).mappings().all()
    return [dict(r) for r in rows]


def _training_load_note(rows: list[dict]) -> str | None:
    derived = sum(
        1
        for r in rows
        if r.get("training_load") is not None
        and r.get("activity_id", "").startswith("csv_")
    )
    if derived:
        return (
            "Training load values are derived for CSV imports "
            "(Aerobic Training Effect × duration). Garmin only includes "
            "true Training Stress Score in CSV exports for power-metered cycling."
        )
    return None


# ---------------------------------------------------------------------------
# CSV import path (mirrors garmin_csv.py, shared helper)
# ---------------------------------------------------------------------------


def _process_csv(
    content: bytes,
    units: str,
    user_id: str,
    db: Session,
    engine: Engine,
) -> UploadResponse:
    """Parse CSV content, dedup, upsert, normalize. Returns UploadResponse."""
    from src.database.models import GarminActivity  # avoid circularity

    try:
        parsed_rows, parse_errors = parse_activities_csv(content, units=units, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File encoding not recognised. Save the file as UTF-8 and try again.",
        )

    if not parsed_rows and not parse_errors:
        raise HTTPException(status_code=400, detail="CSV file contains no data rows")

    dates: list[date] = []
    for row in parsed_rows:
        dt = _parse_dt(row["start_time"])
        if dt:
            dates.append(dt.date())

    if not dates:
        return UploadResponse(
            imported=0,
            skipped_duplicates=0,
            skipped_errors=len(parse_errors),
            format_detected="csv",
            date_range=None,
            warnings=[repr(e) for e in parse_errors[:20]],
            training_load_note=_training_load_note(parsed_rows),
        )

    span_start, span_end = min(dates), max(dates)
    existing = _fetch_existing(db, user_id, span_start, span_end)

    imported = 0
    skipped_dup = 0
    now_iso = datetime.now(UTC).isoformat()

    for row in parsed_rows:
        new_start = _parse_dt(row["start_time"])
        if new_start is None:
            continue
        if _is_duplicate(new_start, row.get("duration_seconds"), row["activity_type"], existing):
            skipped_dup += 1
            continue

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
            user_id=user_id,
        )
        db.merge(obj)
        imported += 1

    if imported > 0:
        db.commit()
        try:
            from src.normalization.normalizer import Normalizer

            with Session(engine) as norm_db:
                n = Normalizer(norm_db, user_id=user_id)
                n.normalize_all(span_start, span_end)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Upload CSV: normalization failed (non-fatal): %s", exc)
    else:
        db.rollback()

    return UploadResponse(
        imported=imported,
        skipped_duplicates=skipped_dup,
        skipped_errors=len(parse_errors),
        format_detected="csv",
        date_range=f"{span_start} → {span_end}" if dates else None,
        warnings=[repr(e) for e in parse_errors[:20]],
        training_load_note=_training_load_note(parsed_rows),
    )


# ---------------------------------------------------------------------------
# JSON / ZIP import path
# ---------------------------------------------------------------------------


def _process_json_or_zip(
    content: bytes,
    suffix: str,
    user_id: str,
    db: Session,
) -> UploadResponse:
    """Save to temp file, run GarminImporter, return UploadResponse."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        importer = GarminImporter(db, normalize=True, user_id=user_id)
        summary = importer.import_from(tmp_path)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    fmt = "zip" if suffix == ".zip" else "json"
    date_range: str | None = None
    if summary.date_range:
        date_range = f"{summary.date_range[0]} → {summary.date_range[1]}"

    return UploadResponse(
        imported=summary.total_records,
        skipped_duplicates=0,
        skipped_errors=0,
        format_detected=fmt,
        date_range=date_range,
        warnings=summary.errors[:20],
        training_load_note=None,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload Garmin data (CSV, JSON, or ZIP export)",
)
async def garmin_upload(
    file: UploadFile = File(..., description="Garmin export file (.csv, .json, or .zip)"),
    units: str = Form(default="miles", description='Distance unit in CSV files: "miles" or "km"'),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    engine: Engine = Depends(get_engine_dep),
) -> UploadResponse:
    """Upload Garmin data from a CSV, JSON, or ZIP export file.

    **Supported formats:**
    - **CSV** — Garmin Connect Activities page → Export CSV
    - **ZIP** — Account Settings → Export Your Data (full account export)
    - **JSON** — summarizedActivities JSON from a Garmin bulk export

    **Size limit:** 50 MB per upload. Re-uploads are idempotent.
    """
    if units not in ("miles", "km"):
        raise HTTPException(status_code=400, detail='units must be "miles" or "km"')

    # Detect format from filename
    filename = (file.filename or "upload").lower()
    suffix = Path(filename).suffix
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix or '(none)'}'. "
                "Upload a .csv, .json, or .zip file."
            ),
        )

    # Read content with size guard
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(content) > MAX_UPLOAD_BYTES:
        mb = len(content) / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({mb:.1f} MB). Maximum upload size is 50 MB.",
        )

    logger.info(
        "Garmin upload: user=%s format=%s size=%d bytes",
        current_user.id,
        suffix,
        len(content),
    )

    if suffix == ".csv":
        return _process_csv(content, units, current_user.id, db, engine)
    else:
        return _process_json_or_zip(content, suffix, current_user.id, db)
