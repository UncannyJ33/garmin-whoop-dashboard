"""Tests for normalization mapper functions and the Normalizer class."""

import json
from datetime import UTC, date, datetime

import pytest

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminDailySummary,
    UnifiedDaily,
    UnifiedSleep,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
)
from src.normalization.garmin_mapper import (
    mps_to_pace,
    normalize_garmin_sport,
    seconds_to_minutes,
)
from src.normalization.normalizer import Normalizer
from src.normalization.whoop_mapper import (
    kj_to_kcal,
    ms_to_minutes,
    normalize_whoop_sport,
    parse_zone_durations,
)

IN_MEMORY = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_MAPPING = {
    "sport_type_mapping": {
        "strength_training": {"whoop": "weightlifting", "garmin": "strength_training"},
        "running": {"whoop": "running", "garmin": "running"},
        "spin": {"whoop": "spin", "garmin": "indoor_cycling"},
    }
}


@pytest.fixture(scope="module")
def engine():
    """Shared in-memory engine for integration tests."""
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Fresh session per test; rolls back on teardown."""
    Session = get_session_factory(engine)
    db = Session()
    yield db
    db.rollback()
    db.close()


@pytest.fixture
def mappings_path(tmp_path):
    """Write a minimal field_mappings.yaml to a tmp file."""
    p = tmp_path / "field_mappings.yaml"
    import yaml

    p.write_text(yaml.dump(SAMPLE_MAPPING))
    return p


# ---------------------------------------------------------------------------
# Unit tests — pure helper functions
# ---------------------------------------------------------------------------


def test_ms_to_minutes():
    assert ms_to_minutes(60_000) == pytest.approx(1.0)
    assert ms_to_minutes(90_000) == pytest.approx(1.5)
    assert ms_to_minutes(0) == pytest.approx(0.0)


def test_ms_to_minutes_none():
    assert ms_to_minutes(None) is None


def test_seconds_to_minutes():
    assert seconds_to_minutes(120.0) == pytest.approx(2.0)
    assert seconds_to_minutes(0.0) == pytest.approx(0.0)
    assert seconds_to_minutes(None) is None


def test_kj_to_kcal():
    assert kj_to_kcal(100.0) == pytest.approx(23.9)
    assert kj_to_kcal(None) is None


def test_mps_to_pace():
    # 3.0 m/s → 1000 / (3.0 × 60) = 5.5555… min/km
    assert mps_to_pace(3.0) == pytest.approx(5.5555, rel=1e-3)


def test_mps_to_pace_zero():
    assert mps_to_pace(0) is None


def test_mps_to_pace_none():
    assert mps_to_pace(None) is None


def test_parse_zone_durations_valid():
    # 6-element array: zone0 = 0, zone1 = 60000ms, …, zone5 = 300000ms
    zones_json = json.dumps([0, 60_000, 120_000, 180_000, 240_000, 300_000])
    result = parse_zone_durations(zones_json)
    assert result["zone_1"] == pytest.approx(1.0)
    assert result["zone_2"] == pytest.approx(2.0)
    assert result["zone_3"] == pytest.approx(3.0)
    assert result["zone_4"] == pytest.approx(4.0)
    assert result["zone_5"] == pytest.approx(5.0)


def test_parse_zone_durations_none():
    result = parse_zone_durations(None)
    assert all(v is None for v in result.values())


def test_parse_zone_durations_invalid():
    result = parse_zone_durations("not-valid-json{")
    assert all(v is None for v in result.values())


def test_normalize_whoop_sport():
    canonical = normalize_whoop_sport("weightlifting", SAMPLE_MAPPING)
    assert canonical == "strength_training"


def test_normalize_garmin_sport():
    canonical = normalize_garmin_sport("indoor_cycling", SAMPLE_MAPPING)
    assert canonical == "spin"


def test_normalize_sport_unknown():
    # Unknown sport falls back to the original value
    assert normalize_whoop_sport("underwater_hockey", SAMPLE_MAPPING) == "underwater_hockey"
    assert normalize_garmin_sport("pickleball", SAMPLE_MAPPING) == "pickleball"


def test_normalize_sport_none():
    assert normalize_whoop_sport(None, SAMPLE_MAPPING) is None
    assert normalize_garmin_sport(None, SAMPLE_MAPPING) is None


# ---------------------------------------------------------------------------
# Integration tests — Normalizer with in-memory DB
# ---------------------------------------------------------------------------

FETCHED = datetime.now(tz=UTC).isoformat()
DATE_STR = "2026-02-10"
TARGET_DATE = date(2026, 2, 10)


def _make_cycle(date_str: str = DATE_STR, strain: float = 12.5) -> WhoopCycle:
    return WhoopCycle(
        id=f"cycle_{date_str}",
        user_id=1,
        start_time=f"{date_str}T12:00:00Z",
        end_time=f"{date_str}T23:59:00Z",
        strain=strain,
        fetched_at=FETCHED,
    )


def _make_recovery(cycle_id: str, sleep_id: str | None = None) -> WhoopRecovery:
    return WhoopRecovery(
        id=cycle_id,
        cycle_id=cycle_id,
        sleep_id=sleep_id,
        recovery_score=78.5,
        resting_heart_rate=58.0,
        hrv_rmssd=42.1,
        spo2_pct=97.2,
        skin_temp_celsius=33.8,
        fetched_at=FETCHED,
    )


def _make_garmin_summary(date_str: str = DATE_STR) -> GarminDailySummary:
    return GarminDailySummary(
        date=date_str,
        total_steps=9500,
        resting_heart_rate=55,
        body_battery_high=85,
        body_battery_low=20,
        avg_stress_level=30,
        fetched_at=FETCHED,
    )


def test_normalize_daily_whoop_only(session, mappings_path):
    cycle = _make_cycle()
    recovery = _make_recovery(cycle.id)
    session.add_all([cycle, recovery])
    session.commit()

    n = Normalizer(session, mappings_path)
    result = n.normalize_daily(TARGET_DATE)

    assert result == 1
    row = session.get(UnifiedDaily, DATE_STR)
    assert row is not None
    assert row.whoop_recovery_score == pytest.approx(78.5)
    assert row.whoop_strain == pytest.approx(12.5)
    sources = json.loads(row.data_sources)
    assert sources == ["whoop"]
    assert row.garmin_total_steps is None


def test_normalize_daily_garmin_only(session, mappings_path):
    date_str = "2026-02-11"
    target = date(2026, 2, 11)
    session.add(_make_garmin_summary(date_str))
    session.commit()

    n = Normalizer(session, mappings_path)
    result = n.normalize_daily(target)

    assert result == 1
    row = session.get(UnifiedDaily, date_str)
    assert row is not None
    sources = json.loads(row.data_sources)
    assert sources == ["garmin"]
    assert row.garmin_total_steps == 9500
    assert row.whoop_recovery_score is None


def test_normalize_daily_both(session, mappings_path):
    date_str = "2026-02-12"
    target = date(2026, 2, 12)
    cycle = _make_cycle(date_str)
    recovery = _make_recovery(cycle.id)
    session.add_all([cycle, recovery, _make_garmin_summary(date_str)])
    session.commit()

    n = Normalizer(session, mappings_path)
    n.normalize_daily(target)

    row = session.get(UnifiedDaily, date_str)
    assert row is not None
    sources = json.loads(row.data_sources)
    assert set(sources) == {"whoop", "garmin"}
    assert row.whoop_recovery_score is not None
    assert row.garmin_total_steps is not None


def test_normalize_daily_no_data(session, mappings_path):
    date_str = "2026-02-13"
    target = date(2026, 2, 13)

    n = Normalizer(session, mappings_path)
    result = n.normalize_daily(target)

    assert result == 0
    assert session.get(UnifiedDaily, date_str) is None


def test_normalize_sleep_excludes_naps(session, mappings_path):
    date_str = "2026-02-14"
    target = date(2026, 2, 14)
    # Only a nap on this date
    nap = WhoopSleep(
        id=f"nap_{date_str}",
        cycle_id=None,
        start_time=f"{date_str}T13:00:00Z",
        end_time=f"{date_str}T14:00:00Z",
        nap=1,
        total_in_bed_ms=3_600_000,
        fetched_at=FETCHED,
    )
    session.add(nap)
    session.commit()

    n = Normalizer(session, mappings_path)
    result = n.normalize_sleep(target)

    assert result == 0
    assert session.get(UnifiedSleep, date_str) is None


def test_normalize_sleep_whoop_primary(session, mappings_path):
    date_str = "2026-02-15"
    target = date(2026, 2, 15)
    sleep = WhoopSleep(
        id=f"sleep_{date_str}",
        cycle_id=None,
        start_time="2026-02-14T22:00:00Z",
        end_time=f"{date_str}T06:30:00Z",
        nap=0,
        total_in_bed_ms=30_600_000,  # 510 min
        total_sws_ms=5_400_000,  # 90 min
        total_light_ms=12_600_000,  # 210 min
        total_rem_ms=7_800_000,  # 130 min
        total_awake_ms=1_800_000,  # 30 min
        sleep_performance=85.0,
        sleep_consistency=75.0,
        sleep_efficiency=90.0,
        respiratory_rate=14.2,
        fetched_at=FETCHED,
    )
    session.add(sleep)
    session.commit()

    n = Normalizer(session, mappings_path)
    result = n.normalize_sleep(target)

    assert result == 1
    row = session.get(UnifiedSleep, date_str)
    assert row is not None
    assert row.primary_source == "whoop"
    assert row.whoop_performance == pytest.approx(85.0)
    assert row.total_sleep_minutes == pytest.approx(510.0)
    assert row.deep_sleep_minutes == pytest.approx(90.0)
    # Garmin fields should be None (no Garmin sleep on this date)
    assert row.garmin_sleep_score is None
    assert row.garmin_avg_spo2_sleep is None
