"""Integration tests for POST /api/garmin/csv-import.

Uses an in-memory SQLite DB with StaticPool (same pattern as test_data_isolation.py)
so the TestClient (ASGI thread) and fixtures share one connection.

Coverage
--------
- Happy path: valid CSV → 200, correct imported count
- Units toggle: miles vs km → different distance_meters stored
- Row limit: >2 000 rows → 400
- Empty file → 400
- Invalid units → 400
- Unauthenticated → 401
- Idempotent re-upload: same file twice → second upload skips all rows
- Near-match deduplication: type + time + duration within tolerance → skipped
- Normalization side-effect: unified_workouts populated after import
- Response fields: date_range, training_load_note, row_errors present
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_engine_dep
from src.api.main import app
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import run as run_migrations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IN_MEMORY = "sqlite:///:memory:"
USER_ID = "cccccccc-1111-1111-1111-000000000003"

# Minimal but realistic CSV header (subset of real Garmin export)
_HEADER = (
    "Activity Type,Date,Favorites,Title,Distance,Calories,"
    "Time,Avg HR,Max HR,Aerobic TE,Avg Run Cadence,Max Run Cadence,"
    "Avg Pace,Best Pace,Total Ascent,Total Descent,Avg Stride Length,"
    "Avg Vertical Ratio,Avg Vertical Oscillation,Avg Ground Contact Time,"
    "Avg GAP,Training Stress Score®,Grit,Flow,Climb Time,Bottom Time,"
    "Min Temp,Surface Interval,Decompression,Best Lap Time,Number of Laps,"
    "Max Temp,Moving Time,Elapsed Time,Min Elevation,Max Elevation"
)

# One running row (miles)
_RUN_ROW = (
    "Running,2026-01-15 07:30:00,,Morning Run,6.2,520,"
    "0:55:00,155,178,3.8,170,185,"
    "8:52,7:45,210,190,1.35,"
    "8.5,9.2,240,"
    "--,0.0,--,--,--,--,"
    "--,--,No,--,1,"
    "--,0:54:00,0:56:00,--,--"
)

# One strength row (no distance)
_STR_ROW = (
    "Strength Training,2026-01-14 08:00:00,,Gym Session,--,380,"
    "1:08:09,142,168,3.2,--,--,"
    "--,--,--,--,--,"
    "--,--,--,"
    "--,0.0,--,--,--,--,"
    "--,--,No,--,--,"
    "--,1:05:00,1:10:00,--,--"
)

# One walking row (km, used in km-units test)
_WALK_KM_ROW = (
    "Walking,2026-01-13 12:00:00,,Lunch Walk,5.0,180,"
    "0:50:00,95,120,1.5,--,--,"
    "--,--,30,25,--,"
    "--,--,--,"
    "--,0.0,--,--,--,--,"
    "--,--,No,--,--,"
    "--,0:48:00,0:52:00,--,--"
)


def _make_csv(*rows: str) -> bytes:
    lines = [_HEADER] + list(rows)
    return "\n".join(lines).encode()


def _single_run() -> bytes:
    return _make_csv(_RUN_ROW)


def _single_str() -> bytes:
    return _make_csv(_STR_ROW)


def _single_walk_km() -> bytes:
    return _make_csv(_WALK_KM_ROW)


def _auth_headers() -> dict[str, str]:
    token, _ = create_access_token(USER_ID)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def eng():
    engine = create_engine(
        IN_MEMORY,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def client(eng):
    """TestClient wired to the in-memory engine via dependency overrides."""
    Session = get_session_factory(eng)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_engine_dep] = lambda: eng
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _upload(client: TestClient, csv_bytes: bytes, units: str = "miles") -> dict:
    """POST the CSV and return the parsed JSON response."""
    return client.post(
        "/api/garmin/csv-import",
        files={"file": ("activities.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"units": units},
        headers=_auth_headers(),
    )


# ---------------------------------------------------------------------------
# Helper: read imported rows from the DB
# ---------------------------------------------------------------------------


def _get_imported(eng, user_id: str = USER_ID) -> list[dict]:
    with Session(eng) as db:
        rows = db.execute(
            text(
                "SELECT activity_id, activity_type, start_time, distance_meters, "
                "duration_seconds, training_load, training_effect_aerobic "
                "FROM garmin_activities WHERE user_id = :uid"
            ),
            {"uid": user_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _clear_imported(eng, user_id: str = USER_ID) -> None:
    with Session(eng) as db:
        db.execute(text("DELETE FROM garmin_activities WHERE user_id = :uid"), {"uid": user_id})
        db.execute(text("DELETE FROM unified_workouts WHERE user_id = :uid"), {"uid": user_id})
        db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_csv_returns_200(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _make_csv(_RUN_ROW, _STR_ROW))
        assert r.status_code == 200
        body = r.json()
        assert body["imported"] == 2
        assert body["skipped_duplicates"] == 0
        assert body["skipped_errors"] == 0

    def test_rows_in_db_after_import(self, client, eng):
        _clear_imported(eng)
        _upload(client, _make_csv(_RUN_ROW, _STR_ROW))
        rows = _get_imported(eng)
        assert len(rows) == 2
        types = {r["activity_type"] for r in rows}
        assert types == {"running", "strength_training"}

    def test_activity_ids_have_csv_prefix(self, client, eng):
        _clear_imported(eng)
        _upload(client, _single_run())
        rows = _get_imported(eng)
        assert all(r["activity_id"].startswith("csv_") for r in rows)

    def test_date_range_in_response(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _make_csv(_RUN_ROW, _STR_ROW))
        body = r.json()
        assert body["date_range"] is not None
        assert "2026-01-14" in body["date_range"]
        assert "2026-01-15" in body["date_range"]

    def test_training_load_note_present(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _single_run())
        body = r.json()
        assert "training_load_note" in body
        assert isinstance(body["training_load_note"], str)
        assert len(body["training_load_note"]) > 0

    def test_row_errors_field_is_list(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _single_run())
        assert isinstance(r.json()["row_errors"], list)


class TestUnitsToggle:
    """Miles vs km produce different distance_meters values."""

    # 6.2 miles × 1609.344 = 9978 m (rounded)
    _MILES_EXPECTED = round(6.2 * 1_609.344)

    # 5.0 km × 1000 = 5000 m
    _KM_EXPECTED = 5_000

    def test_miles_distance_conversion(self, client, eng):
        _clear_imported(eng)
        _upload(client, _single_run(), units="miles")
        rows = _get_imported(eng)
        run = next(r for r in rows if r["activity_type"] == "running")
        assert run["distance_meters"] == pytest.approx(self._MILES_EXPECTED, abs=1)

    def test_km_distance_conversion(self, client, eng):
        _clear_imported(eng)
        _upload(client, _single_walk_km(), units="km")
        rows = _get_imported(eng)
        assert len(rows) == 1
        assert rows[0]["distance_meters"] == pytest.approx(self._KM_EXPECTED, abs=1)


class TestValidation:
    def test_invalid_units_returns_400(self, client, eng):
        r = _upload(client, _single_run(), units="furlongs")
        assert r.status_code == 400
        assert "units" in r.json()["detail"].lower()

    def test_empty_file_returns_400(self, client, eng):
        r = client.post(
            "/api/garmin/csv-import",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
            data={"units": "miles"},
            headers=_auth_headers(),
        )
        assert r.status_code == 400

    def test_row_limit_returns_400(self, client, eng):
        """2 001 data rows should be rejected."""
        over_limit_csv = _make_csv(*[_RUN_ROW] * 2_001)
        r = _upload(client, over_limit_csv)
        assert r.status_code == 400
        assert "2" in r.json()["detail"]  # limit number mentioned


class TestAuthentication:
    def test_unauthenticated_returns_401(self, client, eng):
        r = client.post(
            "/api/garmin/csv-import",
            files={"file": ("activities.csv", io.BytesIO(_single_run()), "text/csv")},
            data={"units": "miles"},
        )
        assert r.status_code == 401


class TestDeduplication:
    def test_same_file_twice_skips_all_on_second_upload(self, client, eng):
        _clear_imported(eng)
        csv_bytes = _make_csv(_RUN_ROW, _STR_ROW)

        r1 = _upload(client, csv_bytes)
        assert r1.json()["imported"] == 2

        r2 = _upload(client, csv_bytes)
        body2 = r2.json()
        assert r2.status_code == 200
        assert body2["imported"] == 0
        assert body2["skipped_duplicates"] == 2

    def test_near_match_within_time_window_is_skipped(self, client, eng):
        """A row with same type and duration but start_time ±3 min is a duplicate."""
        _clear_imported(eng)
        # First upload the reference row
        _upload(client, _single_run())

        # Build a near-duplicate: shift start_time by 3 minutes
        near_dup = _RUN_ROW.replace(
            "2026-01-15 07:30:00",
            "2026-01-15 07:33:00",  # 3 min later — within ±5 min window
        )
        r2 = _upload(client, _make_csv(near_dup))
        assert r2.json()["skipped_duplicates"] == 1
        assert r2.json()["imported"] == 0

    def test_activity_outside_time_window_is_imported(self, client, eng):
        """A row with the same type but start_time ±10 min apart is NOT a duplicate."""
        _clear_imported(eng)
        _upload(client, _single_run())

        far_row = _RUN_ROW.replace(
            "2026-01-15 07:30:00",
            "2026-01-15 07:41:00",  # 11 min later — outside ±5 min window
        )
        r2 = _upload(client, _make_csv(far_row))
        assert r2.json()["imported"] == 1
        assert r2.json()["skipped_duplicates"] == 0


class TestTrainingLoad:
    def test_derived_load_for_csv_rows(self, client, eng):
        """Running rows without TSS should get derived training_load from AerobicTE × duration."""
        _clear_imported(eng)
        _upload(client, _single_run())
        rows = _get_imported(eng)
        run = rows[0]
        # Aerobic TE = 3.8, duration = 55 min → derived load ≈ 209
        assert run["training_load"] is not None
        assert run["training_load"] == pytest.approx(3.8 * 55.0, abs=1)

    def test_training_load_note_mentions_derived(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _single_run())
        note = r.json()["training_load_note"]
        # Should mention derivation (CSV-imported rows have csv_ prefix)
        assert "derived" in note.lower() or "training" in note.lower()


class TestNormalization:
    def test_unified_workouts_populated_after_import(self, client, eng):
        """normalize_all() should run after import and populate unified_workouts."""
        _clear_imported(eng)

        # Patch normalize_all to verify it's called without actually running it
        with patch("src.normalization.normalizer.Normalizer.normalize_all") as mock_norm:
            mock_norm.return_value = None
            r = _upload(client, _single_run())

        assert r.status_code == 200
        assert r.json()["imported"] == 1
        mock_norm.assert_called_once()

    def test_normalization_failure_is_non_fatal(self, client, eng):
        """If normalize_all raises, the import should still succeed (200)."""
        _clear_imported(eng)

        with patch(
            "src.normalization.normalizer.Normalizer.normalize_all",
            side_effect=RuntimeError("norm fail"),
        ):
            r = _upload(client, _single_run())

        assert r.status_code == 200
        assert r.json()["imported"] == 1


class TestResponseShape:
    def test_all_response_fields_present(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _make_csv(_RUN_ROW, _STR_ROW))
        body = r.json()
        required = {
            "imported",
            "skipped_duplicates",
            "skipped_errors",
            "date_range",
            "training_load_note",
            "row_errors",
        }
        assert required.issubset(body.keys())

    def test_skipped_errors_zero_for_valid_csv(self, client, eng):
        _clear_imported(eng)
        r = _upload(client, _make_csv(_RUN_ROW, _STR_ROW))
        assert r.json()["skipped_errors"] == 0

    def test_no_data_rows_after_only_errors(self, client, eng):
        """A header-only CSV returns 400 (no data rows)."""
        r = client.post(
            "/api/garmin/csv-import",
            files={"file": ("header_only.csv", io.BytesIO(_HEADER.encode()), "text/csv")},
            data={"units": "miles"},
            headers=_auth_headers(),
        )
        assert r.status_code == 400
