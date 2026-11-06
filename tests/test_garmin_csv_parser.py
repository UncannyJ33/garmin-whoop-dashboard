"""Unit tests for src/ingestion/garmin_csv_parser.py.

All tests are pure unit tests — no DB, no network, no filesystem access.
The CSV content is constructed in-memory using the same column names as a
real Garmin Connect activities export.

Coverage
--------
  TestNullHandling          — '--' and empty strings become None
  TestDistanceConversion    — miles and km correctly converted to metres
  TestTimeParser            — HH:MM:SS and HH:MM:SS.f formats
  TestActivityTypeNorm      — known types normalised; unknowns slug-ified
  TestSyntheticId           — deterministic, prefixed with 'csv_'
  TestTrainingLoad          — TSS wins when >0; derived from TE×dur otherwise
  TestColumnMapping         — key columns land in the right output fields
  TestRowErrors             — malformed rows recorded as errors, not crashes
  TestRowLimit              — ValueError when content exceeds MAX_ROWS
  TestBOMHandling           — UTF-8 BOM stripped cleanly
  TestRealWorldSample       — parse a multi-row fixture matching Activities.csv
"""

from __future__ import annotations

import pytest

from src.ingestion.garmin_csv_parser import (
    MAX_ROWS,
    parse_activities_csv,
)

# ---------------------------------------------------------------------------
# CSV construction helpers
# ---------------------------------------------------------------------------

# Full header matching a real Garmin Connect activities export.
_HEADER = (
    "Activity Type,Date,Favorite,Title,Distance,Calories,Time,"
    "Avg HR,Max HR,Aerobic TE,Avg Cadence,Max Cadence,Avg Pace,Best Pace,"
    "Total Ascent,Total Descent,Avg Stride Length,Avg Vertical Ratio,"
    "Avg Vertical Oscillation,Avg Ground Contact Time,Avg GAP,"
    "Normalized Power\u00ae (NP\u00ae),Training Stress Score\u00ae,"
    "Avg Power,Max Power,Steps,Total Reps,Total Sets,"
    "Body Battery Drain,Decompression,Best Lap Time,Number of Laps,"
    "Moving Time,Elapsed Time,Min Elevation,Max Elevation"
)

# Minimal values that produce clean output for a running activity.
_RUN_ROW = (
    'Running,2026-01-10 07:00:00,false,"Morning Run",'
    '"3.10","320","00:30:00","145","165","3.5",'
    '"160","172","9:41","8:55","120","80","0.95","9.2","8.6","285","9:35",'
    '"--","0.0","--","--","5,100","--","--","-12","No","00:10:01","3",'
    '"00:29:58","00:30:00","680","720"'
)

# Strength row — no distance, no cadence/pace/dynamics, TSS always 0.
_STR_ROW = (
    'Strength Training,2026-01-11 08:00:00,false,"Strength",'
    '"0.00","410","01:08:09","115","150","1.6",'
    '"--","--","--","--","--","--","--","--","--","--","--",'
    '"--","0.0","--","--","548","274","29","-10","No","01:08:09","1",'
    '"00:23:27","01:08:09","--","--"'
)

# Walking row with all-null running dynamics and fractional seconds.
_WALK_ROW = (
    'Walking,2026-01-12 09:00:00,false,"Walk",'
    '"0.55","71","00:10:17.5","127","132","0.4",'
    '"124","130","18:41","17:32","--","--","0.69","--","--","--","--",'
    '"--","0.0","--","--","1,282","--","--","-1","No","00:10:17.5","1",'
    '"00:10:08","00:10:17","--","--"'
)


def _make_csv(*rows: str) -> bytes:
    """Return CSV bytes with the standard header followed by the given rows."""
    lines = [_HEADER] + list(rows)
    return "\n".join(lines).encode("utf-8")


def _single(row: str = _RUN_ROW, units: str = "miles", user_id: str = "u1") -> dict:
    """Parse a single-row CSV and return the first (only) result dict."""
    content = _make_csv(row)
    rows, errors = parse_activities_csv(content, units=units, user_id=user_id)
    assert not errors, f"Unexpected parse errors: {errors}"
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# Null handling
# ---------------------------------------------------------------------------


class TestNullHandling:
    def test_dash_dash_becomes_none_float(self):
        _single(_RUN_ROW)
        # avg_vertical_ratio is '--' in _RUN_ROW (it's '9.2' actually — use walk)
        walk = _single(_WALK_ROW)
        assert walk["avg_vertical_ratio"] is None

    def test_dash_dash_becomes_none_int(self):
        r = _single(_STR_ROW)
        assert r["avg_heart_rate"] == 115  # present
        # max_running_cadence is '--' in strength row
        assert r["avg_running_cadence"] is None

    def test_zero_distance_becomes_none(self):
        # Strength row has Distance "0.00"
        r = _single(_STR_ROW)
        assert r["distance_meters"] is None

    def test_missing_elevation_none(self):
        r = _single(_WALK_ROW)
        # Walk row has '--' for Min/Max Elevation → elevation_gain/loss from Ascent/Descent
        assert r["elevation_gain"] is None  # walk row has '--' for Total Ascent/Descent
        assert r["elevation_loss"] is None

    def test_run_elevation_populated(self):
        r = _single(_RUN_ROW)
        assert r["elevation_gain"] == 120.0
        assert r["elevation_loss"] == 80.0


# ---------------------------------------------------------------------------
# Distance conversion
# ---------------------------------------------------------------------------


class TestDistanceConversion:
    def test_miles_to_metres(self):
        r = _single(_RUN_ROW, units="miles")
        # 3.10 miles × 1609.344 = 4988.97 → rounded to int
        assert r["distance_meters"] == pytest.approx(3.10 * 1609.344, abs=1)

    def test_km_to_metres(self):
        r = _single(_RUN_ROW, units="km")
        # 3.10 km × 1000 = 3100 m
        assert r["distance_meters"] == pytest.approx(3100.0, abs=1)

    def test_zero_distance_is_none(self):
        r = _single(_STR_ROW, units="miles")
        assert r["distance_meters"] is None

    def test_small_distance_miles(self):
        r = _single(_WALK_ROW, units="miles")
        # 0.55 miles → ~885 m
        assert r["distance_meters"] == pytest.approx(0.55 * 1609.344, abs=1)


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


class TestTimeParser:
    def test_hhmmss(self):
        r = _single(_RUN_ROW)
        # "00:30:00" → 1800 s
        assert r["duration_seconds"] == pytest.approx(1800.0)

    def test_hhmmss_with_fraction(self):
        r = _single(_WALK_ROW)
        # "00:10:17.5" → 617.5 s
        assert r["duration_seconds"] == pytest.approx(617.5)

    def test_long_duration(self):
        r = _single(_STR_ROW)
        # "01:08:09" → 4089 s
        assert r["duration_seconds"] == pytest.approx(4089.0)

    def test_elapsed_seconds_parsed(self):
        r = _single(_RUN_ROW)
        # Elapsed Time = "00:30:00" → 1800 s
        assert r["elapsed_seconds"] == pytest.approx(1800.0)


# ---------------------------------------------------------------------------
# Activity type normalisation
# ---------------------------------------------------------------------------


class TestActivityTypeNorm:
    def test_running(self):
        assert _single(_RUN_ROW)["activity_type"] == "running"

    def test_strength_training(self):
        assert _single(_STR_ROW)["activity_type"] == "strength_training"

    def test_walking(self):
        assert _single(_WALK_ROW)["activity_type"] == "walking"

    def test_treadmill_running_normalised_to_running(self):
        row = _RUN_ROW.replace("Running,", "Treadmill Running,", 1)
        assert _single(row)["activity_type"] == "running"

    def test_indoor_cycling_normalised_to_cycling(self):
        row = _RUN_ROW.replace("Running,", "Indoor Cycling,", 1)
        assert _single(row)["activity_type"] == "cycling"

    def test_unknown_type_slugified(self):
        row = _RUN_ROW.replace("Running,", "Badminton,", 1)
        assert _single(row)["activity_type"] == "badminton"

    def test_unknown_multi_word_slugified(self):
        row = _RUN_ROW.replace("Running,", "Beach Volleyball,", 1)
        assert _single(row)["activity_type"] == "beach_volleyball"


# ---------------------------------------------------------------------------
# Synthetic ID
# ---------------------------------------------------------------------------


class TestSyntheticId:
    def test_prefixed_with_csv(self):
        assert _single(_RUN_ROW)["activity_id"].startswith("csv_")

    def test_deterministic_same_input(self):
        r1 = _single(_RUN_ROW)
        r2 = _single(_RUN_ROW)
        assert r1["activity_id"] == r2["activity_id"]

    def test_different_rows_different_ids(self):
        r_run = _single(_RUN_ROW)
        r_str = _single(_STR_ROW)
        assert r_run["activity_id"] != r_str["activity_id"]

    def test_id_length_reasonable(self):
        # "csv_" + 12 hex chars = 16 chars
        aid = _single(_RUN_ROW)["activity_id"]
        assert len(aid) == 16

    def test_reupload_same_id(self):
        """Re-uploading the same CSV produces the same IDs → upsert is idempotent."""
        content = _make_csv(_RUN_ROW, _STR_ROW)
        rows1, _ = parse_activities_csv(content, units="miles")
        rows2, _ = parse_activities_csv(content, units="miles")
        assert [r["activity_id"] for r in rows1] == [r["activity_id"] for r in rows2]


# ---------------------------------------------------------------------------
# Training load
# ---------------------------------------------------------------------------


class TestTrainingLoad:
    def test_tss_zero_derives_from_aerobic_te(self):
        # Running row: Aerobic TE=3.5, duration=1800 s → 3.5 × 30 = 105
        r = _single(_RUN_ROW)
        assert r["training_load"] == pytest.approx(105.0, abs=0.5)

    def test_tss_positive_used_directly(self):
        # Replace TSS field with a real value (power-metered cycling scenario)
        row = _RUN_ROW.replace('"0.0"', '"85.5"', 1)  # Training Stress Score® field
        content = _make_csv(row)
        rows, _ = parse_activities_csv(content, units="miles")
        assert rows[0]["training_load"] == pytest.approx(85.5)

    def test_zero_aerobic_te_gives_none_load(self):
        # Replace "3.5" Aerobic TE with "0.0" and TSS stays "0.0"
        row = _RUN_ROW.replace('"3.5"', '"0.0"', 1)
        r = _single(row)
        assert r["training_load"] is None

    def test_strength_training_derived(self):
        # STR_ROW: Aerobic TE=1.6, duration=4089 s → 1.6 × 68.15 ≈ 109
        r = _single(_STR_ROW)
        assert r["training_load"] == pytest.approx(1.6 * (4089 / 60), abs=1)

    def test_aerobic_te_stored(self):
        r = _single(_RUN_ROW)
        assert r["training_effect_aerobic"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------


class TestColumnMapping:
    def test_user_id_propagated(self):
        r = _single(_RUN_ROW, user_id="my-user-uuid")
        assert r["user_id"] == "my-user-uuid"

    def test_avg_hr(self):
        assert _single(_RUN_ROW)["avg_heart_rate"] == 145

    def test_max_hr(self):
        assert _single(_RUN_ROW)["max_heart_rate"] == 165

    def test_calories_float(self):
        assert _single(_RUN_ROW)["calories"] == pytest.approx(320.0)

    def test_cadence_running(self):
        assert _single(_RUN_ROW)["avg_running_cadence"] == pytest.approx(160.0)

    def test_max_cadence(self):
        assert _single(_RUN_ROW)["max_running_cadence"] == pytest.approx(172.0)

    def test_avg_stride_length(self):
        assert _single(_RUN_ROW)["avg_stride_length"] == pytest.approx(95.0)

    def test_avg_vertical_ratio(self):
        assert _single(_RUN_ROW)["avg_vertical_ratio"] == pytest.approx(9.2)

    def test_avg_vertical_oscillation(self):
        assert _single(_RUN_ROW)["avg_vertical_oscillation"] == pytest.approx(8.6)

    def test_avg_ground_contact_time(self):
        assert _single(_RUN_ROW)["avg_ground_contact_time"] == pytest.approx(285.0)

    def test_comma_formatted_steps_ignored_no_crash(self):
        # "5,100" steps — the field isn't stored but should not crash the parser
        r = _single(_RUN_ROW)
        assert r is not None  # parsed cleanly

    def test_avg_speed_derived(self):
        # distance_m / moving_time_s: 3.10 mi = 4988.97 m, moving_time = 1798 s
        r = _single(_RUN_ROW)
        expected = (3.10 * 1609.344) / 1798
        assert r["avg_speed"] == pytest.approx(expected, rel=0.01)

    def test_start_time_preserved(self):
        assert _single(_RUN_ROW)["start_time"] == "2026-01-10 07:00:00"

    def test_activity_name(self):
        assert _single(_RUN_ROW)["activity_name"] == "Morning Run"

    def test_vo2_max_always_none_from_csv(self):
        assert _single(_RUN_ROW)["vo2_max"] is None

    def test_raw_json_none(self):
        assert _single(_RUN_ROW)["raw_json"] is None


# ---------------------------------------------------------------------------
# Row-level errors
# ---------------------------------------------------------------------------


class TestRowErrors:
    def test_missing_date_produces_error(self):
        bad = _RUN_ROW.replace("2026-01-10 07:00:00", "")
        content = _make_csv(bad)
        rows, errors = parse_activities_csv(content)
        assert len(rows) == 0
        assert len(errors) == 1
        assert errors[0].row_num == 2

    def test_missing_activity_type_produces_error(self):
        # Replace the first field with an empty quoted string
        bad = '"",2026-01-10 07:00:00,' + ",".join(_RUN_ROW.split(",")[2:])
        content = _make_csv(bad)
        rows, errors = parse_activities_csv(content)
        assert len(rows) == 0
        assert len(errors) == 1

    def test_good_rows_continue_after_bad_row(self):
        """One bad row should not abort parsing of subsequent rows."""
        bad = _RUN_ROW.replace("2026-01-10 07:00:00", "")  # missing date
        content = _make_csv(bad, _STR_ROW, _WALK_ROW)
        rows, errors = parse_activities_csv(content)
        assert len(errors) == 1
        assert len(rows) == 2  # STR and WALK still parsed

    def test_error_row_num_correct(self):
        content = _make_csv(_RUN_ROW, _RUN_ROW.replace("2026-01-10 07:00:00", ""))
        _, errors = parse_activities_csv(content)
        assert errors[0].row_num == 3  # row 1=header, 2=good, 3=bad


# ---------------------------------------------------------------------------
# Row limit
# ---------------------------------------------------------------------------


class TestRowLimit:
    def test_raises_on_excess_rows(self):
        rows = [_RUN_ROW] * (MAX_ROWS + 1)
        content = _make_csv(*rows)
        with pytest.raises(ValueError, match=str(MAX_ROWS)):
            parse_activities_csv(content)

    def test_exactly_at_limit_is_ok(self):
        rows = [_RUN_ROW] * MAX_ROWS
        content = _make_csv(*rows)
        parsed, errors = parse_activities_csv(content)
        # IDs are all identical (same row), but no error raised
        assert len(parsed) + len(errors) == MAX_ROWS

    def test_below_limit_is_ok(self):
        content = _make_csv(_RUN_ROW, _STR_ROW, _WALK_ROW)
        rows, errors = parse_activities_csv(content)
        assert len(rows) == 3
        assert not errors


# ---------------------------------------------------------------------------
# BOM handling
# ---------------------------------------------------------------------------


class TestBOMHandling:
    def test_utf8_bom_stripped(self):
        content = b"\xef\xbb\xbf" + _make_csv(_RUN_ROW)
        rows, errors = parse_activities_csv(content)
        assert not errors
        assert len(rows) == 1
        assert rows[0]["activity_type"] == "running"


# ---------------------------------------------------------------------------
# Multi-row real-world sample
# ---------------------------------------------------------------------------


class TestRealWorldSample:
    """Parse a representative multi-row fixture and verify aggregate properties."""

    CSV = _make_csv(_RUN_ROW, _STR_ROW, _WALK_ROW)

    def test_all_rows_parsed(self):
        rows, errors = parse_activities_csv(self.CSV, units="miles", user_id="u-test")
        assert not errors
        assert len(rows) == 3

    def test_unique_activity_ids(self):
        rows, _ = parse_activities_csv(self.CSV)
        ids = [r["activity_id"] for r in rows]
        assert len(set(ids)) == 3

    def test_all_rows_have_user_id(self):
        rows, _ = parse_activities_csv(self.CSV, user_id="u-test")
        assert all(r["user_id"] == "u-test" for r in rows)

    def test_all_rows_have_fetched_at(self):
        rows, _ = parse_activities_csv(self.CSV)
        assert all(r["fetched_at"] for r in rows)

    def test_activity_types_correct(self):
        rows, _ = parse_activities_csv(self.CSV)
        types = [r["activity_type"] for r in rows]
        assert types == ["running", "strength_training", "walking"]

    def test_training_load_present_for_all(self):
        rows, _ = parse_activities_csv(self.CSV)
        # All three rows have non-zero Aerobic TE so load should be derived
        assert all(r["training_load"] is not None for r in rows)

    def test_strength_has_no_distance(self):
        rows, _ = parse_activities_csv(self.CSV)
        str_row = next(r for r in rows if r["activity_type"] == "strength_training")
        assert str_row["distance_meters"] is None

    def test_running_has_cadence(self):
        rows, _ = parse_activities_csv(self.CSV)
        run_row = next(r for r in rows if r["activity_type"] == "running")
        assert run_row["avg_running_cadence"] == pytest.approx(160.0)

    def test_walking_has_no_vertical_ratio(self):
        rows, _ = parse_activities_csv(self.CSV)
        walk = next(r for r in rows if r["activity_type"] == "walking")
        assert walk["avg_vertical_ratio"] is None
