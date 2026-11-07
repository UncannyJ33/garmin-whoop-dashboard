"""Strength routes: set-level history plus Personal API exercise summaries."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_engine_dep
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminActivity,
    GarminExerciseSet,
    GarminExerciseSummary,
    UnifiedWorkout,
)

NOW_ISO = datetime.now(UTC).isoformat()
USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _auth(user_id: str) -> dict[str, str]:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine=eng)
    # Only the owner (A) has a users row; B keeps data rows only.
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES (:id, 'a@example.test', 'x', '2026-01-01T00:00:00', 1)"
            ),
            {"id": USER_A},
        )
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def db(engine):
    s = get_session_factory(engine)()
    yield s
    s.close()


@pytest.fixture(scope="module")
def client(engine):
    Session = get_session_factory(engine)

    def _engine_override():
        return engine

    def _db_override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    with patch("src.api.main.start_scheduler"), patch("src.api.main.stop_scheduler"):
        from src.api.main import app  # noqa: PLC0415

        app.dependency_overrides[get_engine_dep] = _engine_override
        app.dependency_overrides[get_db] = _db_override
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()


def _activity(db, aid: str, day: str, user: str = USER_A) -> str:
    """Seed a garmin activity and its unified workout; return the workout id."""
    db.add(GarminActivity(activity_id=aid, fetched_at=NOW_ISO, user_id=user))
    db.flush()
    wid = f"g_{aid}"
    db.add(
        UnifiedWorkout(
            id=wid,
            date=day,
            start_time=f"{day}T10:00:00Z",
            garmin_activity_id=aid,
            last_updated=NOW_ISO,
            user_id=user,
        )
    )
    db.commit()
    return wid


def _sets(db, aid: str, name: str, weights_reps: list[tuple[float, int]], user: str = USER_A):
    for i, (w, r) in enumerate(weights_reps):
        db.add(
            GarminExerciseSet(
                activity_id=aid,
                set_order=i,
                set_type="ACTIVE",
                exercise_category="BENCH_PRESS",
                exercise_name=name,
                repetition_count=r,
                weight_kg=w,
                fetched_at=NOW_ISO,
                user_id=user,
            )
        )
    db.commit()


def _summary(db, aid: str, name: str, volume: float, max_w: float, user: str = USER_A):
    db.add(
        GarminExerciseSummary(
            activity_id=aid,
            exercise_category="BENCH_PRESS",
            exercise_name=name,
            set_count=3,
            repetition_count=24,
            volume_kg=volume,
            max_weight_kg=max_w,
            duration_seconds=120.0,
            fetched_at=NOW_ISO,
            user_id=user,
        )
    )
    db.commit()


def _volume(client, day: str) -> list[dict]:
    r = client.get(f"/api/workouts/strength-volume?start={day}&end={day}", headers=_auth(USER_A))
    assert r.status_code == 200
    return r.json()


def test_volume_from_summaries_only(client, db):
    _activity(db, "s1", "2025-01-01")
    _summary(db, "s1", "BARBELL_BENCH_PRESS", 1000.0, 80.0)
    _summary(db, "s1", "SQUAT", 500.0, 100.0)
    assert _volume(client, "2025-01-01") == [{"date": "2025-01-01", "total_volume_kg": 1500.0}]


def test_volume_prefers_sets_over_summaries(client, db):
    _activity(db, "b1", "2025-01-02")
    _sets(db, "b1", "BENCH_PRESS", [(50.0, 10), (60.0, 5)])  # 500 + 300
    _summary(db, "b1", "BENCH_PRESS", 9999.0, 999.0)
    assert _volume(client, "2025-01-02") == [{"date": "2025-01-02", "total_volume_kg": 800.0}]


def test_volume_same_date_mixed_sources_one_row(client, db):
    _activity(db, "m1", "2025-01-03")
    _activity(db, "m2", "2025-01-03")
    _sets(db, "m1", "BENCH_PRESS", [(50.0, 10)])  # 500
    _summary(db, "m2", "SQUAT", 700.0, 100.0)
    assert _volume(client, "2025-01-03") == [{"date": "2025-01-03", "total_volume_kg": 1200.0}]


def test_max_weight_includes_legacy_sets(client, db):
    _activity(db, "l1", "2025-01-04")
    _activity(db, "n1", "2025-01-05")
    _sets(db, "l1", "BENCH_PRESS", [(50.0, 10), (70.0, 3)])
    _summary(db, "n1", "BARBELL_BENCH_PRESS", 1000.0, 85.0)
    r = client.get(
        "/api/workouts/strength-max-weight?start=2025-01-04&end=2025-01-05",
        headers=_auth(USER_A),
    )
    assert r.status_code == 200
    assert r.json() == [
        {"date": "2025-01-04", "exercise_name": "BENCH_PRESS", "max_weight_kg": 70.0},
        {"date": "2025-01-05", "exercise_name": "BARBELL_BENCH_PRESS", "max_weight_kg": 85.0},
    ]


def test_aggregates_scoped_to_user(client, db):
    _activity(db, "u1", "2025-01-06", user=USER_B)
    _summary(db, "u1", "SQUAT", 400.0, 90.0, user=USER_B)
    assert _volume(client, "2025-01-06") == []
    r = client.get(
        "/api/workouts/strength-max-weight?start=2025-01-06&end=2025-01-06",
        headers=_auth(USER_A),
    )
    assert r.json() == []


def test_exercise_summary_endpoint_returns_rows(client, db):
    wid = _activity(db, "e1", "2025-01-07")
    _summary(db, "e1", "SQUAT", 500.0, 100.0)
    r = client.get(f"/api/workouts/{wid}/exercise-summary", headers=_auth(USER_A))
    assert r.status_code == 200
    assert r.json() == [
        {
            "exercise_category": "BENCH_PRESS",
            "exercise_name": "SQUAT",
            "set_count": 3,
            "repetition_count": 24,
            "volume_kg": 500.0,
            "max_weight_kg": 100.0,
            "duration_seconds": 120.0,
        }
    ]


def test_exercise_summary_endpoint_scoped_to_user(client, db):
    wid = _activity(db, "e2", "2025-01-08", user=USER_B)
    _summary(db, "e2", "SQUAT", 500.0, 100.0, user=USER_B)
    r = client.get(f"/api/workouts/{wid}/exercise-summary", headers=_auth(USER_A))
    assert r.status_code == 200
    assert r.json() == []
