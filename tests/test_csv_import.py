"""Tests for the Garmin CSV/JSON import tool."""

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime

import pytest

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import GarminActivity, GarminDailySummary, SyncLog
from src.ingestion.csv_import import (
    GarminImporter,
    ImportSummary,
    _coerce_row,
    _detect_format,
    _extract_activities,
    _find_activity_json_files,
    _float_columns,
    _int_columns,
    _known_columns,
    _merge_date_range,
)

IN_MEMORY = "sqlite:///:memory:"
FETCHED = datetime.now(tz=UTC).isoformat()

# ---------------------------------------------------------------------------
# Shared DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    Session = get_session_factory(engine)
    db = Session()
    yield db
    db.rollback()
    db.close()


# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------


def test_detect_format_zip(tmp_path):
    p = tmp_path / "export.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("dummy.json", "[]")
    assert _detect_format(p) == "garmin_zip"


def test_detect_format_json_dir(tmp_path):
    (tmp_path / "activities.json").write_text("[]")
    assert _detect_format(tmp_path) == "json_dir"


def test_detect_format_csv_dir(tmp_path):
    (tmp_path / "garmin_activities.csv").write_text("activity_id\n")
    assert _detect_format(tmp_path) == "csv_dir"


def test_detect_format_csv_file(tmp_path):
    p = tmp_path / "garmin_activities.csv"
    p.write_text("activity_id\n")
    assert _detect_format(p) == "csv_file"


def test_detect_format_json_file(tmp_path):
    p = tmp_path / "activities.json"
    p.write_text("[]")
    assert _detect_format(p) == "json_file"


def test_detect_format_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        _detect_format(tmp_path / "nonexistent.zip")


def test_detect_format_empty_dir(tmp_path):
    with pytest.raises(ValueError, match="neither JSON nor CSV"):
        _detect_format(tmp_path)


# ---------------------------------------------------------------------------
# _extract_activities
# ---------------------------------------------------------------------------

SAMPLE_ACTIVITY = {
    "activityId": 22058725765,
    "activityName": "Morning Run",
    "startTimeLocal": "2026-03-04 07:18:03",
    "startTimeGMT": "2026-03-04 13:18:03",
    "activityType": {"typeKey": "running"},
    "distance": 4612.36,
    "duration": 1966.68,
    "averageHR": 146.0,
    "maxHR": 178.0,
}


def test_extract_activities_from_list():
    data = [SAMPLE_ACTIVITY, {"not": "an_activity"}]
    result = _extract_activities(data)
    assert len(result) == 1
    assert result[0]["activityId"] == 22058725765


def test_extract_activities_from_single_dict():
    result = _extract_activities(SAMPLE_ACTIVITY)
    assert len(result) == 1


def test_extract_activities_from_wrapped():
    wrapped = {"summarizedActivitiesExport": [SAMPLE_ACTIVITY]}
    result = _extract_activities(wrapped)
    assert len(result) == 1


def test_extract_activities_alternative_wrapper():
    wrapped = {"activityList": [SAMPLE_ACTIVITY]}
    result = _extract_activities(wrapped)
    assert len(result) == 1


def test_extract_activities_no_activity_id():
    result = _extract_activities([{"name": "not an activity"}])
    assert result == []


def test_extract_activities_empty_list():
    assert _extract_activities([]) == []


def test_extract_activities_non_dict():
    assert _extract_activities("string") == []
    assert _extract_activities(42) == []


# ---------------------------------------------------------------------------
# _coerce_row
# ---------------------------------------------------------------------------


def _activity_meta() -> tuple[frozenset, frozenset, frozenset]:
    return _int_columns(GarminActivity), _float_columns(GarminActivity), _known_columns(GarminActivity)


def test_coerce_row_int_field():
    int_c, float_c, known = _activity_meta()
    row = {"activity_id": "123", "avg_heart_rate": "146.0"}
    result = _coerce_row(row, int_c, float_c, known)
    assert result["avg_heart_rate"] == 146
    assert isinstance(result["avg_heart_rate"], int)


def test_coerce_row_float_field():
    int_c, float_c, known = _activity_meta()
    row = {"activity_id": "123", "duration_seconds": "1966.68"}
    result = _coerce_row(row, int_c, float_c, known)
    assert result["duration_seconds"] == pytest.approx(1966.68)


def test_coerce_row_empty_string_becomes_none():
    int_c, float_c, known = _activity_meta()
    row = {"activity_id": "123", "avg_heart_rate": ""}
    result = _coerce_row(row, int_c, float_c, known)
    assert result["avg_heart_rate"] is None


def test_coerce_row_null_sentinels():
    int_c, float_c, known = _activity_meta()
    for sentinel in ("none", "NULL", "N/A", "na", "-"):
        row = {"activity_id": "123", "duration_seconds": sentinel}
        result = _coerce_row(row, int_c, float_c, known)
        assert result["duration_seconds"] is None, f"Expected None for sentinel '{sentinel}'"


def test_coerce_row_unknown_columns_dropped():
    int_c, float_c, known = _activity_meta()
    row = {"activity_id": "123", "made_up_column": "value"}
    result = _coerce_row(row, int_c, float_c, known)
    assert "made_up_column" not in result


def test_coerce_row_invalid_numeric_becomes_none():
    int_c, float_c, known = _activity_meta()
    row = {"activity_id": "123", "avg_heart_rate": "not_a_number"}
    result = _coerce_row(row, int_c, float_c, known)
    assert result["avg_heart_rate"] is None


# ---------------------------------------------------------------------------
# _find_activity_json_files
# ---------------------------------------------------------------------------


def test_find_files_in_garmin_export_structure(tmp_path):
    """Correctly finds JSON in DI_CONNECT/DI-Connect-Fitness/."""
    fitness = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
    fitness.mkdir(parents=True)
    f1 = fitness / "summarizedActivities.json"
    f1.write_text("[]")
    f2 = fitness / "part_1.json"
    f2.write_text("[]")

    files = _find_activity_json_files(tmp_path)
    assert f1 in files
    assert f2 in files


def test_find_files_with_leading_directory(tmp_path):
    """Handles ZIP exports that unpack into a username directory."""
    user_dir = tmp_path / "user_export_2026"
    fitness = user_dir / "DI_CONNECT" / "DI-Connect-Fitness"
    fitness.mkdir(parents=True)
    f = fitness / "summarizedActivities.json"
    f.write_text("[]")

    files = _find_activity_json_files(tmp_path)
    assert f in files


def test_find_files_fallback_to_all_json(tmp_path):
    """Falls back to all .json files when no Garmin structure found."""
    f = tmp_path / "my_activities.json"
    f.write_text("[]")
    files = _find_activity_json_files(tmp_path)
    assert f in files


def test_find_files_no_duplicates(tmp_path):
    """No file appears twice in the results."""
    fitness = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
    fitness.mkdir(parents=True)
    f = fitness / "summarizedActivities.json"
    f.write_text("[]")
    files = _find_activity_json_files(tmp_path)
    assert files.count(f) == 1


# ---------------------------------------------------------------------------
# _merge_date_range
# ---------------------------------------------------------------------------


def test_merge_date_range_initial():
    s = ImportSummary(source_path="x", format_detected="csv_file")
    _merge_date_range(s, [date(2026, 2, 1), date(2026, 3, 4)])
    assert s.date_range == (date(2026, 2, 1), date(2026, 3, 4))


def test_merge_date_range_expands():
    s = ImportSummary(source_path="x", format_detected="csv_file")
    s.date_range = (date(2026, 2, 10), date(2026, 2, 20))
    _merge_date_range(s, [date(2026, 2, 1), date(2026, 3, 4)])
    assert s.date_range == (date(2026, 2, 1), date(2026, 3, 4))


def test_merge_date_range_empty():
    s = ImportSummary(source_path="x", format_detected="csv_file")
    _merge_date_range(s, [])
    assert s.date_range is None


# ---------------------------------------------------------------------------
# CSV integration tests
# ---------------------------------------------------------------------------


def _make_activities_csv(rows: list[dict]) -> str:
    """Build a CSV string from a list of dicts."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


SAMPLE_CSV_ACTIVITY = {
    "activity_id": "22058725765",
    "activity_type": "running",
    "activity_name": "Morning Run",
    "start_time": "2026-03-04 07:18:03",
    "start_time_gmt": "2026-03-04 13:18:03",
    "duration_seconds": "1966.68",
    "distance_meters": "4612.36",
    "avg_heart_rate": "146",
    "max_heart_rate": "178",
    "elevation_gain": "23.0",
}


def test_csv_import_activities(tmp_path, session):
    """CSV file with valid rows is upserted to garmin_activities."""
    csv_content = _make_activities_csv([SAMPLE_CSV_ACTIVITY])
    csv_path = tmp_path / "garmin_activities.csv"
    csv_path.write_text(csv_content)

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(csv_path)

    assert summary.activities == 1
    assert summary.errors == []
    row = session.get(GarminActivity, "22058725765")
    assert row is not None
    assert row.activity_type == "running"
    assert row.avg_heart_rate == 146
    assert row.duration_seconds == pytest.approx(1966.68)


def test_csv_skips_row_missing_pk(tmp_path, session):
    """Rows without activity_id are skipped with a warning."""
    rows = [
        {"activity_id": "99999", "activity_type": "running", "duration_seconds": "600"},
        {"activity_id": "", "activity_type": "cycling", "duration_seconds": "1200"},
    ]
    csv_path = tmp_path / "garmin_activities.csv"
    csv_path.write_text(_make_activities_csv(rows))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(csv_path)

    assert summary.activities == 1
    assert len(summary.errors) == 1
    assert "missing required 'activity_id'" in summary.errors[0]


def test_csv_unknown_columns_ignored(tmp_path, session):
    """Extra CSV columns not in the schema are silently dropped."""
    row = dict(SAMPLE_CSV_ACTIVITY)
    row["activity_id"] = "11111111"
    row["mystery_column"] = "some_value"
    row["another_extra"] = "123"

    csv_path = tmp_path / "garmin_activities.csv"
    csv_path.write_text(_make_activities_csv([row]))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(csv_path)

    assert summary.activities == 1
    assert summary.errors == []


def test_csv_upserts_existing_row(tmp_path, session):
    """Re-importing the same activity_id updates the existing row."""
    aid = "33333333"
    row1 = dict(SAMPLE_CSV_ACTIVITY, activity_id=aid, activity_name="First")
    row2 = dict(SAMPLE_CSV_ACTIVITY, activity_id=aid, activity_name="Updated")

    for row in (row1, row2):
        csv_path = tmp_path / "garmin_activities.csv"
        csv_path.write_text(_make_activities_csv([row]))
        GarminImporter(session, normalize=False).import_from(csv_path)

    stored = session.get(GarminActivity, aid)
    assert stored.activity_name == "Updated"


def test_csv_daily_summary_import(tmp_path, session):
    """garmin_daily_summary.csv imports into the correct table."""
    row = {
        "date": "2026-03-01",
        "total_steps": "9500",
        "resting_heart_rate": "55",
        "body_battery_high": "88",
        "body_battery_low": "22",
        "avg_stress_level": "28",
    }
    csv_path = tmp_path / "garmin_daily_summary.csv"
    csv_path.write_text(_make_activities_csv([row]))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(csv_path)

    assert summary.daily_summaries == 1
    stored = session.get(GarminDailySummary, "2026-03-01")
    assert stored is not None
    assert stored.total_steps == 9500


def test_csv_unrecognised_filename_skipped(tmp_path, session):
    """CSV files not named garmin_*.csv are ignored."""
    (tmp_path / "my_data.csv").write_text("col\nval\n")
    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(tmp_path)
    assert summary.total_records == 0


def test_csv_creates_sync_log(tmp_path, session):
    """A SyncLog entry is written for every import run."""
    row = dict(SAMPLE_CSV_ACTIVITY, activity_id="44444444")
    csv_path = tmp_path / "garmin_activities.csv"
    csv_path.write_text(_make_activities_csv([row]))

    before = session.query(SyncLog).filter_by(source="csv_import").count()
    GarminImporter(session, normalize=False).import_from(csv_path)
    after = session.query(SyncLog).filter_by(source="csv_import").count()
    assert after == before + 1


# ---------------------------------------------------------------------------
# JSON integration tests
# ---------------------------------------------------------------------------


def test_json_file_import(tmp_path, session):
    """A JSON file containing a list of activities is imported correctly."""
    json_path = tmp_path / "activities.json"
    json_path.write_text(json.dumps([SAMPLE_ACTIVITY]))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(json_path)

    assert summary.activities == 1
    assert summary.errors == []
    row = session.get(GarminActivity, str(SAMPLE_ACTIVITY["activityId"]))
    assert row is not None
    assert row.activity_type == "running"


def test_json_wrapped_format_import(tmp_path, session):
    """JSON with a wrapper key is unwrapped correctly."""
    act = dict(SAMPLE_ACTIVITY, activityId=99887766)
    json_path = tmp_path / "summarizedActivities.json"
    json_path.write_text(json.dumps({"summarizedActivitiesExport": [act]}))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(json_path)

    assert summary.activities == 1
    row = session.get(GarminActivity, "99887766")
    assert row is not None


def test_json_skips_non_activity_records(tmp_path, session):
    """JSON items without activityId are silently ignored."""
    data = [SAMPLE_ACTIVITY, {"name": "not_an_activity"}, {"activityId": None}]
    json_path = tmp_path / "mixed.json"
    json_path.write_text(json.dumps(data))

    # Only one has activityId (None fails KeyError in transform_activity)
    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(json_path)
    assert summary.activities == 1


def test_json_dir_import(tmp_path, session):
    """Directory of JSON files: each file's activities are imported."""
    act2 = dict(SAMPLE_ACTIVITY, activityId=11223344)
    (tmp_path / "part_0.json").write_text(json.dumps([SAMPLE_ACTIVITY]))
    (tmp_path / "part_1.json").write_text(json.dumps([act2]))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(tmp_path)

    assert summary.activities == 2


def test_zip_import(tmp_path, session):
    """ZIP archive is extracted and activities imported."""
    # Build a minimal Garmin-export-style ZIP
    zip_path = tmp_path / "garmin_export.zip"
    act = dict(SAMPLE_ACTIVITY, activityId=55667788)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "DI_CONNECT/DI-Connect-Fitness/summarizedActivities.json",
            json.dumps([act]),
        )

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(zip_path)

    assert summary.activities == 1
    assert session.get(GarminActivity, "55667788") is not None


def test_zip_with_leading_directory(tmp_path, session):
    """ZIP where root is a username directory is handled correctly."""
    zip_path = tmp_path / "username_export.zip"
    act = dict(SAMPLE_ACTIVITY, activityId=66778899)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "username_20260304/DI_CONNECT/DI-Connect-Fitness/summarizedActivities.json",
            json.dumps([act]),
        )

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(zip_path)

    assert summary.activities == 1


def test_import_date_range_tracked(tmp_path, session):
    """date_range reflects the earliest and latest activity dates."""
    acts = [
        dict(SAMPLE_ACTIVITY, activityId=1001, startTimeGMT="2026-02-01 10:00:00"),
        dict(SAMPLE_ACTIVITY, activityId=1002, startTimeGMT="2026-03-04 13:00:00"),
    ]
    json_path = tmp_path / "activities.json"
    json_path.write_text(json.dumps(acts))

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(json_path)

    assert summary.date_range is not None
    assert summary.date_range[0] == date(2026, 2, 1)
    assert summary.date_range[1] == date(2026, 3, 4)


def test_import_summary_str(tmp_path, session):
    """ImportSummary.__str__ includes the key fields."""
    row = dict(SAMPLE_CSV_ACTIVITY, activity_id="77777777")
    csv_path = tmp_path / "garmin_activities.csv"
    csv_path.write_text(_make_activities_csv([row]))

    summary = GarminImporter(session, normalize=False).import_from(csv_path)
    text = str(summary)
    assert "csv_file" in text
    assert "Activities" in text


def test_malformed_json_recorded_as_warning(tmp_path, session):
    """A malformed JSON file is skipped with a warning, import continues."""
    good_act = dict(SAMPLE_ACTIVITY, activityId=88990011)
    (tmp_path / "good.json").write_text(json.dumps([good_act]))
    (tmp_path / "bad.json").write_text("{not valid json{{")

    importer = GarminImporter(session, normalize=False)
    summary = importer.import_from(tmp_path)

    assert summary.activities == 1
    assert len(summary.errors) == 1
    assert "bad.json" in summary.errors[0]
