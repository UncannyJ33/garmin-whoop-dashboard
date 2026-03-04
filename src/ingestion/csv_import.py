"""Garmin data importer: Garmin Connect bulk export (ZIP/JSON) and manual CSV files.

Supports three input formats detected automatically:
  - Garmin Connect bulk export ZIP (downloaded from account settings)
  - Directory of JSON files (extracted ZIP or API dump)
  - Directory of CSV files named garmin_activities.csv, garmin_daily_summary.csv, etc.

After import, upserts into the garmin_* raw tables and triggers normalization.

Usage::

    from src.ingestion.csv_import import GarminImporter
    with Session(engine) as db:
        importer = GarminImporter(db)
        summary = importer.import_from(Path("export.zip"))
        print(summary)
"""

import csv
import json
import logging
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import Float, Integer
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminHRV,
    GarminSleep,
    SyncLog,
)
from src.ingestion.garmin_pipeline import transform_activity
from src.normalization.normalizer import Normalizer

logger = logging.getLogger(__name__)

_M = TypeVar("_M")

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# CSV filename stem → (ORM model, primary-key field name)
_CSV_TABLE_MAP: dict[str, tuple[type, str]] = {
    "garmin_activities": (GarminActivity, "activity_id"),
    "garmin_daily_summary": (GarminDailySummary, "date"),
    "garmin_sleep": (GarminSleep, "date"),
    "garmin_hrv": (GarminHRV, "date"),
}

# Known wrapper keys in Garmin bulk-export JSON that contain the activity list
_JSON_WRAPPER_KEYS = ("summarizedActivitiesExport", "activityList", "activities")


@dataclass
class ImportSummary:
    """Results of one import run."""

    source_path: str
    format_detected: str  # garmin_zip | json_dir | json_file | csv_dir | csv_file
    activities: int = 0
    daily_summaries: int = 0
    sleep_records: int = 0
    hrv_records: int = 0
    norm_counts: dict[str, int] = field(default_factory=dict)
    date_range: tuple[date, date] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def total_records(self) -> int:
        return self.activities + self.daily_summaries + self.sleep_records + self.hrv_records

    def __str__(self) -> str:
        lines = [
            f"Format:       {self.format_detected}",
            f"Source:       {self.source_path}",
        ]
        if self.date_range:
            lines.append(f"Date range:   {self.date_range[0]} → {self.date_range[1]}")
        lines += [
            f"Activities:   {self.activities}",
            f"Daily:        {self.daily_summaries}",
            f"Sleep:        {self.sleep_records}",
            f"HRV:          {self.hrv_records}",
        ]
        if self.norm_counts:
            lines.append(f"Normalized:   {self.norm_counts}")
        if self.errors:
            lines.append(f"Warnings:     {len(self.errors)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main importer class
# ---------------------------------------------------------------------------


class GarminImporter:
    """Import Garmin data from bulk export archives or manual CSV files.

    Args:
        db: Active SQLAlchemy session.
        normalize: If True (default), run normalization after import.
        mappings_path: Optional override for field_mappings.yaml path.
    """

    def __init__(
        self,
        db: Session,
        normalize: bool = True,
        mappings_path: Path | None = None,
    ) -> None:
        self._db = db
        self._normalize = normalize
        self._mappings_path = mappings_path

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def import_from(self, path: Path) -> ImportSummary:
        """Auto-detect format and import from path.

        Args:
            path: ZIP file, directory, or CSV/JSON file to import.

        Returns:
            ImportSummary with counts and any warnings.
        """
        fmt = _detect_format(path)
        summary = ImportSummary(source_path=str(path), format_detected=fmt)
        now = datetime.now(tz=UTC)
        fetched_at = now.isoformat()

        log = SyncLog(
            source="csv_import",
            sync_type="manual",
            started_at=now.isoformat(),
            status="running",
            metadata_json=json.dumps({"source_path": str(path), "format": fmt}),
        )
        self._db.add(log)
        self._db.commit()

        try:
            if fmt == "garmin_zip":
                self._import_zip(path, summary, fetched_at)
            elif fmt == "json_dir":
                self._import_json_dir(path, summary, fetched_at)
            elif fmt == "json_file":
                self._import_json_file(path, summary, fetched_at)
            elif fmt == "csv_dir":
                self._import_csv_dir(path, summary, fetched_at)
            else:  # csv_file
                self._import_csv_dir(path.parent, summary, fetched_at, only=path)

            if self._normalize and summary.date_range:
                norm = Normalizer(self._db, self._mappings_path)
                summary.norm_counts = norm.normalize_all(*summary.date_range)
                logger.info("Normalization after import: %s", summary.norm_counts)

            log.status = "success"
            log.records_fetched = summary.total_records
            log.records_stored = summary.total_records
            log.completed_at = datetime.now(tz=UTC).isoformat()
            if summary.date_range:
                meta = json.loads(log.metadata_json)
                meta["sync_start"] = summary.date_range[0].isoformat()
                meta["sync_end"] = summary.date_range[1].isoformat()
                log.metadata_json = json.dumps(meta)
            self._db.commit()

        except Exception as exc:
            log.status = "error"
            log.error_message = str(exc)
            log.completed_at = datetime.now(tz=UTC).isoformat()
            self._db.commit()
            raise

        logger.info("Import complete: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Format-specific import methods
    # ------------------------------------------------------------------

    def _import_zip(self, zip_path: Path, summary: ImportSummary, fetched_at: str) -> None:
        """Extract a Garmin Connect bulk export ZIP and import its contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)
            self._import_json_dir(tmp, summary, fetched_at)

    def _import_json_dir(
        self, dir_path: Path, summary: ImportSummary, fetched_at: str
    ) -> None:
        """Find and import all activity JSON files from a Garmin export directory."""
        all_dates: list[date] = []
        for json_path in _find_activity_json_files(dir_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    raw = json.load(f)
                activities = _extract_activities(raw)
                if not activities:
                    logger.debug("No activities found in %s — skipping", json_path.name)
                    continue
                n, dates = self._store_json_activities(activities, fetched_at, json_path.name)
                summary.activities += n
                all_dates.extend(dates)
                logger.info("Imported %d activities from %s", n, json_path.name)
            except (json.JSONDecodeError, OSError) as exc:
                msg = f"Skipped {json_path.name}: {exc}"
                summary.errors.append(msg)
                logger.warning(msg)
        _merge_date_range(summary, all_dates)

    def _import_json_file(
        self, json_path: Path, summary: ImportSummary, fetched_at: str
    ) -> None:
        """Import a single JSON file."""
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)
        activities = _extract_activities(raw)
        n, dates = self._store_json_activities(activities, fetched_at, json_path.name)
        summary.activities += n
        _merge_date_range(summary, dates)

    def _import_csv_dir(
        self,
        dir_path: Path,
        summary: ImportSummary,
        fetched_at: str,
        only: Path | None = None,
    ) -> None:
        """Import CSV files from a directory.

        Args:
            dir_path: Directory to scan for CSV files.
            summary: Mutated in place.
            fetched_at: Timestamp string for fetched_at column.
            only: If given, import only this single file.
        """
        csv_files = [only] if only else sorted(dir_path.glob("*.csv"))
        all_dates: list[date] = []

        for csv_path in csv_files:
            stem = csv_path.stem.lower()
            if stem not in _CSV_TABLE_MAP:
                logger.debug("Skipping unrecognised CSV: %s", csv_path.name)
                continue
            model_cls, pk_field = _CSV_TABLE_MAP[stem]
            n, dates, errors = self._import_one_csv(csv_path, model_cls, pk_field, fetched_at)
            summary.errors.extend(errors)
            all_dates.extend(dates)
            if stem == "garmin_activities":
                summary.activities += n
            elif stem == "garmin_daily_summary":
                summary.daily_summaries += n
            elif stem == "garmin_sleep":
                summary.sleep_records += n
            elif stem == "garmin_hrv":
                summary.hrv_records += n

        _merge_date_range(summary, all_dates)

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _store_json_activities(
        self, activities: list[dict], fetched_at: str, source_name: str
    ) -> tuple[int, list[date]]:
        """Transform and upsert a list of JSON activity dicts.

        Args:
            activities: List of activity dicts (Garmin API / export format).
            fetched_at: ISO 8601 timestamp string.
            source_name: Filename for warning messages.

        Returns:
            Tuple of (rows_stored, list_of_dates).
        """
        stored = 0
        dates: list[date] = []
        for record in activities:
            try:
                data = transform_activity(record, fetched_at)
                self._upsert(GarminActivity, "activity_id", data)
                stored += 1
                d = _date_from_gmt(data.get("start_time_gmt") or data.get("start_time"))
                if d:
                    dates.append(d)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipped activity in %s: %s", source_name, exc)
        if stored:
            self._db.commit()
        return stored, dates

    def _import_one_csv(
        self,
        csv_path: Path,
        model_cls: type,
        pk_field: str,
        fetched_at: str,
    ) -> tuple[int, list[date], list[str]]:
        """Parse one CSV file and upsert rows into model_cls.

        Args:
            csv_path: Path to the CSV file.
            model_cls: Target SQLAlchemy model.
            pk_field: Name of the primary-key column.
            fetched_at: ISO 8601 timestamp for the fetched_at column.

        Returns:
            Tuple of (rows_stored, list_of_dates, list_of_error_strings).
        """
        int_cols = _int_columns(model_cls)
        float_cols = _float_columns(model_cls)
        known = _known_columns(model_cls)
        stored = 0
        dates: list[date] = []
        errors: list[str] = []

        table_name = model_cls.__tablename__

        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return 0, [], [f"{csv_path.name}: empty file or missing header"]

            for row_num, raw_row in enumerate(reader, start=2):
                # Normalise key casing; strip whitespace from values
                row = {k.lower().strip(): (v or "").strip() for k, v in raw_row.items()}

                if not row.get(pk_field):
                    errors.append(
                        f"{csv_path.name} row {row_num}: missing required '{pk_field}' — skipped"
                    )
                    continue

                data = _coerce_row(row, int_cols, float_cols, known)
                data["fetched_at"] = fetched_at
                data["raw_json"] = json.dumps(row)

                d = _date_from_row(data, table_name)
                if d:
                    dates.append(d)

                try:
                    self._upsert(model_cls, pk_field, data)
                    stored += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{csv_path.name} row {row_num}: {exc}")

        if stored:
            self._db.commit()
        logger.info("CSV %s: %d rows imported", csv_path.name, stored)
        return stored, dates, errors

    def _upsert(self, model_cls: type[_M], pk_field: str, data: dict[str, Any]) -> _M:
        """Insert or update a single row identified by its primary key."""
        pk = data[pk_field]
        row = self._db.get(model_cls, pk)
        if row is None:
            row = model_cls(**data)
            self._db.add(row)
        else:
            for k, v in data.items():
                setattr(row, k, v)
        return row


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _detect_format(path: Path) -> str:
    """Return a format tag for the given path.

    Returns one of: "garmin_zip", "json_dir", "json_file", "csv_dir", "csv_file".

    Raises:
        ValueError: If the path does not exist or cannot be classified.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        return "garmin_zip"
    if path.is_dir():
        if any(path.glob("*.json")) or any(path.rglob("*.json")):
            return "json_dir"
        if any(path.glob("*.csv")):
            return "csv_dir"
        raise ValueError(f"Directory contains neither JSON nor CSV files: {path}")
    if path.suffix.lower() == ".json":
        return "json_file"
    if path.suffix.lower() == ".csv":
        return "csv_file"
    raise ValueError(f"Unrecognised file type: {path}")


def _find_activity_json_files(dir_path: Path) -> list[Path]:
    """Locate JSON files that likely contain Garmin activity data.

    Search order:
      1. ``DI_CONNECT/DI-Connect-Fitness/`` subtree (standard Garmin bulk export)
      2. Same path one level deeper (ZIP with a leading username directory)
      3. Files named ``*activities*.json`` anywhere under dir_path
      4. All ``.json`` files (fallback)

    Args:
        dir_path: Root directory to search.

    Returns:
        Ordered list of unique .json file paths.
    """
    seen: set[Path] = set()
    result: list[Path] = []

    def _add(p: Path) -> None:
        rp = p.resolve()
        if p.is_file() and rp not in seen:
            seen.add(rp)
            result.append(p)

    # Priority 1: standard Garmin bulk export path
    fitness_dir = dir_path / "DI_CONNECT" / "DI-Connect-Fitness"
    if fitness_dir.is_dir():
        for f in sorted(fitness_dir.glob("*.json")):
            _add(f)

    # Priority 2: same path with a leading directory (common when zip has a root folder)
    if not result:
        for sub in sorted(dir_path.iterdir()):
            if sub.is_dir():
                nested = sub / "DI_CONNECT" / "DI-Connect-Fitness"
                if nested.is_dir():
                    for f in sorted(nested.glob("*.json")):
                        _add(f)

    if result:
        return result

    # Fallback 1: files named *activities*.json
    for f in sorted(dir_path.rglob("*activities*.json")):
        _add(f)

    if result:
        return result

    # Fallback 2: all JSON files
    for f in sorted(dir_path.rglob("*.json")):
        _add(f)

    return result


def _extract_activities(data: Any) -> list[dict]:
    """Extract a list of activity dicts from parsed JSON.

    Handles:
      - A JSON array of activity dicts (most common)
      - A single activity dict
      - Wrapped formats: ``{"summarizedActivitiesExport": [...]}`` etc.

    Args:
        data: Parsed JSON value (list, dict, or other).

    Returns:
        List of dicts each containing at least an ``activityId`` key.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("activityId")]
    if isinstance(data, dict):
        for key in _JSON_WRAPPER_KEYS:
            if key in data and isinstance(data[key], list):
                return _extract_activities(data[key])
        if "activityId" in data:
            return [data]
    return []


def _coerce_row(
    row: dict[str, str],
    int_cols: frozenset[str],
    float_cols: frozenset[str],
    known_cols: frozenset[str],
) -> dict[str, Any]:
    """Coerce CSV string values to Python types and drop unknown columns.

    Empty strings and common null sentinels become ``None``.
    Integer columns accept decimal strings like ``"146.0"``.

    Args:
        row: Raw CSV row with lower-cased keys and stripped string values.
        int_cols: Column names that should be cast to ``int``.
        float_cols: Column names that should be cast to ``float``.
        known_cols: Column names that exist on the target model; others are dropped.

    Returns:
        Dict ready for ORM model construction.
    """
    _NULL_STRINGS = {"", "none", "null", "n/a", "na", "-"}
    result: dict[str, Any] = {}
    for key, val in row.items():
        if key not in known_cols:
            continue
        if val.lower() in _NULL_STRINGS:
            result[key] = None
        elif key in int_cols:
            try:
                result[key] = int(float(val))
            except ValueError:
                result[key] = None
        elif key in float_cols:
            try:
                result[key] = float(val)
            except ValueError:
                result[key] = None
        else:
            result[key] = val
    return result


def _int_columns(model_cls: type) -> frozenset[str]:
    """Return the set of Integer column names for a SQLAlchemy model."""
    return frozenset(
        col.key
        for col in sa_inspect(model_cls).column_attrs
        if isinstance(col.columns[0].type, Integer)
    )


def _float_columns(model_cls: type) -> frozenset[str]:
    """Return the set of Float column names for a SQLAlchemy model."""
    return frozenset(
        col.key
        for col in sa_inspect(model_cls).column_attrs
        if isinstance(col.columns[0].type, Float)
    )


def _known_columns(model_cls: type) -> frozenset[str]:
    """Return all column names defined on a SQLAlchemy model."""
    return frozenset(col.key for col in sa_inspect(model_cls).column_attrs)


def _date_from_gmt(dt_str: str | None) -> date | None:
    """Parse the first 10 characters of a datetime string as a date."""
    if dt_str and len(dt_str) >= 10:
        try:
            return date.fromisoformat(dt_str[:10])
        except ValueError:
            pass
    return None


def _date_from_row(data: dict[str, Any], table_name: str) -> date | None:
    """Extract the representative date from a transformed row dict."""
    if table_name == "garmin_activities":
        return _date_from_gmt(data.get("start_time_gmt") or data.get("start_time"))
    return _date_from_gmt(data.get("date"))


def _merge_date_range(summary: ImportSummary, dates: list[date]) -> None:
    """Expand summary.date_range to encompass all dates in the list."""
    if not dates:
        return
    new_start, new_end = min(dates), max(dates)
    if summary.date_range is None:
        summary.date_range = (new_start, new_end)
    else:
        summary.date_range = (
            min(summary.date_range[0], new_start),
            max(summary.date_range[1], new_end),
        )
