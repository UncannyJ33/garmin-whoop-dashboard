"""Parse Garmin Connect Activities CSV export into garmin_activities-compatible dicts.

Garmin Connect → Activities page → Export CSV produces a file with one row per
activity. The columns match the schema documented in Activities.csv at the
project root (gitignored — personal data).

Key format details
------------------
- Null / missing values are represented as the literal string ``"--"``.
- Numbers use comma thousands-separators, e.g. ``"1,282"`` steps.
- Times are ``HH:MM:SS`` or ``HH:MM:SS.f`` (fractional seconds).
- Distance is in the user's configured unit (miles or km) — the caller must
  pass ``units`` so we can convert to metres for storage.
- Date is local time with no timezone info: ``"2026-03-19 08:34:47"``.
- Training Stress Score® (TSS) is only populated for power-meter cycling.
  For all other activity types the column is ``"0.0"``.  When TSS is absent,
  a *derived* proxy is computed as ``Aerobic TE × duration_minutes``.
  This is labelled in the UI (via the ``csv_`` prefix on activity_id).

Row limit
---------
Raises ``ValueError`` if the content exceeds ``MAX_ROWS`` (2 000).  This
matches Garmin Connect's own per-export cap for most users and prevents abuse.

Deduplication (caller responsibility)
--------------------------------------
Each parsed row receives a deterministic synthetic ``activity_id`` of the form
``csv_{sha256[:12]}`` derived from ``date + type + duration``.  The endpoint
layer checks for near-duplicate rows already in the DB (same user_id, same
activity_type, start_time within ±5 min, duration within ±10%) before
upserting.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ROWS = 2_000

MILES_TO_M = 1_609.344
KM_TO_M = 1_000.0

# Garmin CSV "Activity Type" → internal activity_type key
_TYPE_MAP: dict[str, str] = {
    "running": "running",
    "treadmill running": "running",
    "trail running": "running",
    "track running": "running",
    "cycling": "cycling",
    "indoor cycling": "cycling",
    "virtual ride": "cycling",
    "road cycling": "cycling",
    "strength training": "strength_training",
    "walking": "walking",
    "hiking": "hiking",
    "swimming": "swimming",
    "pool swimming": "swimming",
    "open water swimming": "swimming",
    "yoga": "yoga",
    "pilates": "pilates",
    "hiit": "hiit",
    "cardio": "indoor_cardio",
    "elliptical": "indoor_cardio",
    "stair stepping": "indoor_cardio",
    "rowing": "rowing",
    "indoor rowing": "rowing",
    "cross country skiing": "skiing",
    "skiing": "skiing",
    "snowboarding": "skiing",
    "tennis": "tennis",
    "basketball": "basketball",
    "soccer": "soccer",
    "golf": "golf",
    "breathwork": "breathwork",
    "meditation": "meditation",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _null(val: str) -> bool:
    """Return True when the CSV value represents a missing/null entry."""
    return not val or val.strip() in {"--", "-", ""}


def _parse_float(val: str) -> float | None:
    if _null(val):
        return None
    try:
        return float(val.replace(",", "").strip())
    except ValueError:
        return None


def _parse_int(val: str) -> int | None:
    f = _parse_float(val)
    return None if f is None else int(round(f))


def _parse_time_to_seconds(val: str) -> float | None:
    """Parse ``HH:MM:SS`` or ``HH:MM:SS.f`` into total seconds."""
    if _null(val):
        return None
    parts = val.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = int(parts[0]), float(parts[1])
            return m * 60 + s
    except (ValueError, IndexError):
        pass
    return None


def _normalize_type(raw: str) -> str:
    key = raw.strip().lower()
    return _TYPE_MAP.get(key, key.replace(" ", "_"))


def _synthetic_id(date_str: str, activity_type: str, duration_s: float | None) -> str:
    """Deterministic synthetic primary key for a CSV-imported row.

    The same row in the same CSV will always produce the same id, so
    re-uploading the same file is idempotent (upsert overwrites in place).
    """
    key = f"{date_str}|{activity_type}|{int(duration_s or 0)}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"csv_{digest}"


def _derive_training_load(aerobic_te: float | None, duration_s: float | None) -> float | None:
    """Proxy training load when Garmin TSS is absent (non-power-meter activities).

    Formula: Aerobic TE (0–5) × duration in minutes.

    This is *not* equivalent to Garmin's internal training-load metric.
    The CSV-import endpoint notes this in the API response and the UI
    signals it via the ``csv_`` prefix on activity_id.
    """
    if aerobic_te is None or not aerobic_te or duration_s is None:
        return None
    return round(aerobic_te * (duration_s / 60.0), 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CSVRowError:
    """A non-fatal parse error on a single row."""

    def __init__(self, row_num: int, message: str) -> None:
        self.row_num = row_num
        self.message = message

    def __repr__(self) -> str:
        return f"Row {self.row_num}: {self.message}"


def parse_activities_csv(
    content: bytes,
    units: str = "miles",
    user_id: str | None = None,
) -> tuple[list[dict], list[CSVRowError]]:
    """Parse a Garmin Connect activities CSV export.

    Args:
        content: Raw file bytes (UTF-8 or UTF-8-BOM).
        units:   Distance unit in the CSV — ``"miles"`` or ``"km"``.
        user_id: App user UUID; written into every output row.

    Returns:
        ``(rows, errors)`` where *rows* are dicts ready for upserting into
        ``garmin_activities`` and *errors* are per-row parse failures.

    Raises:
        ValueError: If the file has more than ``MAX_ROWS`` data rows.
        UnicodeDecodeError: If the file is not UTF-8.
    """
    dist_factor = MILES_TO_M if units == "miles" else KM_TO_M
    text = content.decode("utf-8-sig")  # strip BOM if present
    reader = csv.DictReader(io.StringIO(text))

    rows: list[dict] = []
    errors: list[CSVRowError] = []
    now_iso = datetime.now(UTC).isoformat()

    for row_num, raw in enumerate(reader, start=2):  # row 1 = header
        if len(rows) + len(errors) >= MAX_ROWS:
            raise ValueError(
                f"File exceeds the {MAX_ROWS}-row limit. "
                "Use Garmin Connect's date-range filter to export in smaller batches."
            )

        try:
            date_str = (raw.get("Date") or "").strip()
            if not date_str:
                errors.append(CSVRowError(row_num, "Missing Date"))
                continue

            type_raw = (raw.get("Activity Type") or "").strip()
            if not type_raw:
                errors.append(CSVRowError(row_num, "Missing Activity Type"))
                continue

            activity_type = _normalize_type(type_raw)
            duration_s = _parse_time_to_seconds(raw.get("Time", ""))
            elapsed_s = _parse_time_to_seconds(raw.get("Elapsed Time", ""))

            distance_raw = _parse_float(raw.get("Distance", ""))
            distance_m = round(distance_raw * dist_factor) if distance_raw else None

            aerobic_te = _parse_float(raw.get("Aerobic TE", ""))
            tss_raw = _parse_float(raw.get("Training Stress Score\u00ae", ""))
            # TSS is populated only for power-metered cycling; treat 0 as absent
            tss = tss_raw if (tss_raw is not None and tss_raw > 0) else None
            training_load = tss if tss is not None else _derive_training_load(aerobic_te, duration_s)

            # Derive avg_speed (m/s) from distance + moving time when available
            moving_s = _parse_time_to_seconds(raw.get("Moving Time", "")) or duration_s
            avg_speed: float | None = None
            if distance_m and moving_s:
                avg_speed = round(distance_m / moving_s, 4)

            elevation_gain = _parse_float(raw.get("Total Ascent", ""))
            elevation_loss = _parse_float(raw.get("Total Descent", ""))

            rows.append(
                {
                    "activity_id": _synthetic_id(date_str, activity_type, duration_s),
                    "activity_type": activity_type,
                    "activity_name": (raw.get("Title") or "").strip() or type_raw,
                    "start_time": date_str,
                    "start_time_gmt": date_str,  # CSV has local time; no tz available
                    "duration_seconds": duration_s,
                    "elapsed_seconds": elapsed_s,
                    "distance_meters": float(distance_m) if distance_m else None,
                    "avg_heart_rate": _parse_int(raw.get("Avg HR", "")),
                    "max_heart_rate": _parse_int(raw.get("Max HR", "")),
                    "avg_running_cadence": _parse_float(raw.get("Avg Cadence", "")),
                    "max_running_cadence": _parse_float(raw.get("Max Cadence", "")),
                    "calories": _parse_float(raw.get("Calories", "")),
                    "avg_speed": avg_speed,
                    "max_speed": None,  # not in CSV
                    "elevation_gain": elevation_gain,
                    "elevation_loss": elevation_loss,
                    "avg_stride_length": _parse_float(raw.get("Avg Stride Length", "")),
                    "vo2_max": None,  # not in CSV
                    "training_effect_aerobic": aerobic_te,
                    "training_effect_anaerobic": None,  # not in CSV
                    "training_load": training_load,
                    "avg_ground_contact_time": _parse_float(raw.get("Avg Ground Contact Time", "")),
                    "avg_vertical_oscillation": _parse_float(raw.get("Avg Vertical Oscillation", "")),
                    "avg_vertical_ratio": _parse_float(raw.get("Avg Vertical Ratio", "")),
                    "avg_ground_contact_balance": None,  # not in CSV
                    "fetched_at": now_iso,
                    "raw_json": None,
                    "user_id": user_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            errors.append(CSVRowError(row_num, str(exc)))
            logger.debug("CSV row %d parse error: %s", row_num, exc)

    return rows, errors
