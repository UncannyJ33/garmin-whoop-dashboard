"""Multi-user data isolation integration tests.

Strategy:
  - Two test users (User A, User B) share one in-memory SQLite DB.
  - User A has data on 2024-01-01..2024-01-07.
  - User B has data on 2024-01-15..2024-01-21.
  - Workouts: User A and User B both have a workout on 2024-01-03 (same date,
    different IDs) — this is the critical overlap case that proves filtering
    is on user_id and not just date.
  - Every data endpoint is called with User A's JWT over a query range that
    spans both users' dates; assertions confirm only User A's data is returned.
  - Negative test: monkeypatches the user_id filter out of the workouts route
    and verifies the isolation test would catch the resulting data leak.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_engine_dep
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    SyncLog,
    UnifiedDaily,
    UnifiedSleep,
    UnifiedWorkout,
    WhoopWorkout,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IN_MEMORY = "sqlite:///:memory:"
NOW_ISO = datetime.now(UTC).isoformat()

USER_A_ID = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B_ID = "bbbbbbbb-0000-0000-0000-000000000002"

# Non-overlapping date ranges (date is PK in unified_daily / unified_sleep)
A_DATES = [f"2024-01-0{i}" for i in range(1, 8)]  # 2024-01-01..07
B_DATES = [f"2024-01-{i}" for i in range(15, 22)]  # 2024-01-15..21

# Query range spanning both users' data
QUERY_START = "2024-01-01"
QUERY_END = "2024-01-21"

# Workout IDs — both on the SAME date to test that date alone is not the filter
A_WORKOUT_ID = "w_a-workout-001"  # 2024-01-03, running, strain=14.0
B_WORKOUT_ID = "w_b-workout-001"  # 2024-01-03, cycling, strain=12.0

# Recovery activity IDs (WhoopWorkout with strain=NULL)
A_RECOVERY_ID = "ww-a-recovery-001"  # sport_name=yoga
B_RECOVERY_ID = "ww-b-recovery-001"  # sport_name=meditation

# Distinct numeric values per user (makes accidental leaks detectable by value)
A_RECOVERY_SCORE = 75.0
B_RECOVERY_SCORE = 90.0  # distinctly different from A


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(user_id: str) -> dict[str, str]:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures — module scope: DB seeded once, shared by all tests in the module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def iso_engine():
    # StaticPool: all connection requests return the same underlying connection,
    # regardless of thread.  Required for in-memory SQLite so that the ASGI
    # worker thread (TestClient) sees the same database as the fixture thread.
    eng = create_engine(
        IN_MEMORY,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def _seed(iso_engine):
    """Insert User A and User B rows into all relevant tables."""
    Session = get_session_factory(iso_engine)
    db = Session()

    # --- unified_daily (date = PK: non-overlapping per user) ---
    for d in A_DATES:
        db.add(
            UnifiedDaily(
                date=d,
                whoop_recovery_score=A_RECOVERY_SCORE,
                whoop_hrv_rmssd=55.0,
                whoop_strain=8.0,
                data_sources='["whoop"]',
                last_updated=NOW_ISO,
                user_id=USER_A_ID,
            )
        )
    for d in B_DATES:
        db.add(
            UnifiedDaily(
                date=d,
                whoop_recovery_score=B_RECOVERY_SCORE,  # distinctly higher
                whoop_hrv_rmssd=70.0,
                whoop_strain=5.0,
                data_sources='["whoop"]',
                last_updated=NOW_ISO,
                user_id=USER_B_ID,
            )
        )

    # --- unified_sleep (date = PK: same non-overlapping dates) ---
    for d in A_DATES:
        db.add(
            UnifiedSleep(
                date=d,
                whoop_performance=80.0,
                total_sleep_minutes=450.0,
                deep_sleep_minutes=90.0,
                primary_source="whoop",
                last_updated=NOW_ISO,
                user_id=USER_A_ID,
            )
        )
    for d in B_DATES:
        db.add(
            UnifiedSleep(
                date=d,
                whoop_performance=95.0,  # distinctly higher
                total_sleep_minutes=540.0,
                deep_sleep_minutes=120.0,
                primary_source="whoop",
                last_updated=NOW_ISO,
                user_id=USER_B_ID,
            )
        )

    # --- unified_workouts (id = PK: same date, different user — critical case) ---
    db.add(
        UnifiedWorkout(
            id=A_WORKOUT_ID,
            date="2024-01-03",
            start_time="2024-01-03T14:00:00Z",
            end_time="2024-01-03T15:00:00Z",
            activity_type="running",
            duration_minutes=60.0,
            whoop_strain=14.0,
            matched=False,
            primary_source="whoop",
            last_updated=NOW_ISO,
            user_id=USER_A_ID,
        )
    )
    db.add(
        UnifiedWorkout(
            id=B_WORKOUT_ID,
            date="2024-01-03",  # SAME date as A's workout — user_id must be the filter
            start_time="2024-01-03T16:00:00Z",
            end_time="2024-01-03T17:00:00Z",
            activity_type="cycling",
            duration_minutes=60.0,
            whoop_strain=12.0,
            matched=False,
            primary_source="whoop",
            last_updated=NOW_ISO,
            user_id=USER_B_ID,
        )
    )

    # --- whoop_workouts with strain=NULL (recovery activities) ---
    db.add(
        WhoopWorkout(
            id=A_RECOVERY_ID,
            start_time="2024-01-04T09:00:00Z",
            end_time="2024-01-04T09:30:00Z",
            sport_name="yoga",
            strain=None,
            fetched_at=NOW_ISO,
            user_id=USER_A_ID,
        )
    )
    db.add(
        WhoopWorkout(
            id=B_RECOVERY_ID,
            start_time="2024-01-17T09:00:00Z",
            end_time="2024-01-17T09:30:00Z",
            sport_name="meditation",
            strain=None,
            fetched_at=NOW_ISO,
            user_id=USER_B_ID,
        )
    )

    # --- sync_log (for /api/sync/stats) ---
    db.add(
        SyncLog(
            source="whoop",
            sync_type="full",
            started_at=NOW_ISO,
            completed_at=NOW_ISO,
            records_fetched=10,
            records_stored=10,
            status="success",
            user_id=USER_A_ID,
        )
    )
    db.add(
        SyncLog(
            source="whoop",
            sync_type="full",
            started_at=NOW_ISO,
            completed_at=NOW_ISO,
            records_fetched=99,  # distinctly different; must not appear in A's stats
            records_stored=99,
            status="success",
            user_id=USER_B_ID,
        )
    )

    db.commit()
    db.close()


@pytest.fixture(scope="module")
def isolation_client(iso_engine, _seed):
    """FastAPI TestClient with DB dependencies overridden to use the isolation test engine."""
    Session = get_session_factory(iso_engine)

    def _engine_override():
        return iso_engine

    def _db_override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # Patch scheduler start/stop so the TestClient lifespan doesn't try to connect
    with (
        patch("src.api.main.start_scheduler"),
        patch("src.api.main.stop_scheduler"),
    ):
        from src.api.main import app  # noqa: PLC0415

        app.dependency_overrides[get_engine_dep] = _engine_override
        app.dependency_overrides[get_db] = _db_override
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Section 1: Workouts endpoints
# ---------------------------------------------------------------------------


def test_list_workouts_excludes_other_user(isolation_client):
    """User A's workout list must not contain User B's workout — even on the same date."""
    r = isolation_client.get(
        f"/api/workouts?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    ids = [w["id"] for w in r.json()]
    assert A_WORKOUT_ID in ids, "User A's own workout must appear"
    assert B_WORKOUT_ID not in ids, "User B's workout on same date must NOT appear"


def test_workout_detail_returns_404_for_other_users_workout(isolation_client):
    """Fetching User B's workout ID while authenticated as User A must return 404."""
    r = isolation_client.get(
        f"/api/workouts/{B_WORKOUT_ID}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 404


def test_workout_summary_counts_only_own_workouts(isolation_client):
    """Type summary counts must reflect only User A's workouts, not User B's."""
    r = isolation_client.get(
        f"/api/workouts/summary?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    summary = {s["activity_type"]: s for s in r.json()}
    # User A has 1 running workout
    assert "running" in summary
    assert summary["running"]["count"] == 1, (
        f"Expected 1 running workout for User A, got {summary['running']['count']}"
    )
    # User B's cycling workout must not appear
    assert "cycling" not in summary, "User B's cycling workout must NOT appear in A's summary"


# ---------------------------------------------------------------------------
# Section 2: Readiness endpoints
# ---------------------------------------------------------------------------


def test_readiness_history_excludes_other_user_dates(isolation_client):
    """Readiness history must contain only User A's date range."""
    r = isolation_client.get(
        f"/api/readiness/history?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    returned_dates = {h["date"] for h in r.json()}
    for d in B_DATES:
        assert d not in returned_dates, f"User B's date {d} leaked into readiness history"


# ---------------------------------------------------------------------------
# Section 3: Sleep endpoints
# ---------------------------------------------------------------------------


def test_sleep_insights_excludes_other_user(isolation_client):
    """Sleep insights must only contain User A's dates and performance values."""
    r = isolation_client.get(
        f"/api/sleep/insights?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    insights = r.json()
    for row in insights:
        assert row["date"] not in B_DATES, f"User B's date {row['date']} leaked into sleep insights"
        perf = row.get("sleep_performance")
        if perf is not None:
            # User B has performance=95; A has performance=80
            assert perf < 90.0, (
                f"sleep_performance={perf} looks like User B's data (95.0) leaked through"
            )


# ---------------------------------------------------------------------------
# Section 4: Trends endpoint
# ---------------------------------------------------------------------------


def test_metric_trend_excludes_other_user_dates(isolation_client):
    """Recovery trend series must not contain User B's values.

    The trend endpoint returns a calendar-filled series (one entry per day in
    the requested range), so B's dates will appear in `dates` with None values.
    The assertion is that values at B's dates are None — proving B's data was
    filtered out — not that B's dates are absent from the axis.
    """
    r = isolation_client.get(
        f"/api/trends/recovery?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    trend = r.json()
    date_to_value = dict(zip(trend["dates"], trend["values"]))

    # B's dates may appear in the calendar fill, but their values must be None
    for d in B_DATES:
        if d in date_to_value:
            assert date_to_value[d] is None, (
                f"User B's recovery value {date_to_value[d]} on {d} leaked through. "
                f"Expected None (no data for User A on that date)."
            )

    # Spot-check: no non-None value in the series should equal B's recovery score
    non_null = [v for v in trend["values"] if v is not None]
    for v in non_null:
        assert v < 88.0, (
            f"Recovery value {v} looks like User B's data ({B_RECOVERY_SCORE}) leaked through"
        )


# ---------------------------------------------------------------------------
# Section 5: Recovery activities endpoint
# ---------------------------------------------------------------------------


def test_recovery_activities_excludes_other_user(isolation_client):
    """Recovery activities must not include User B's meditation session."""
    r = isolation_client.get(
        f"/api/recovery?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r.status_code == 200
    activity_names = [a["activity"].lower() for a in r.json()]
    assert "meditation" not in activity_names, (
        "User B's meditation activity must NOT appear in User A's recovery list"
    )


# ---------------------------------------------------------------------------
# Section 6: Sync stats endpoint
# ---------------------------------------------------------------------------


def test_sync_stats_counts_only_own_rows(isolation_client):
    """Data overview must count only User A's rows — not the combined total."""
    r = isolation_client.get("/api/sync/stats", headers=_auth(USER_A_ID))
    assert r.status_code == 200
    stats = r.json()
    # User A: 7 daily rows, 1 workout row
    # If isolation fails, counts would be 14 and 2 respectively
    assert stats["total_days"] == len(A_DATES), (
        f"Expected {len(A_DATES)} daily rows for User A, got {stats['total_days']}. "
        "User B's rows may be leaking through."
    )
    assert stats["total_workouts"] == 1, (
        f"Expected 1 workout for User A, got {stats['total_workouts']}. "
        "User B's workout may be leaking through."
    )


# ---------------------------------------------------------------------------
# Section 7: Unauthenticated requests are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"/api/workouts?start={QUERY_START}&end={QUERY_END}",
        f"/api/readiness/history?start={QUERY_START}&end={QUERY_END}",
        f"/api/sleep/insights?start={QUERY_START}&end={QUERY_END}",
        f"/api/trends/recovery?start={QUERY_START}&end={QUERY_END}",
        "/api/sync/stats",
        f"/api/recovery?start={QUERY_START}&end={QUERY_END}",
    ],
)
def test_unauthenticated_request_is_rejected(isolation_client, path):
    r = isolation_client.get(path)  # no Authorization header
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Section 8: Negative test — confirm the tests CATCH a real data leak
# ---------------------------------------------------------------------------


def test_negative__missing_user_id_filter_leaks_data(isolation_client):
    """If the user_id filter is removed from get_enriched_workouts, User A can see
    User B's workout.  This confirms that test_list_workouts_excludes_other_user
    would catch such a regression in production code.

    Note: passing user_id=None to the analytics function uses `AND user_id IS NULL`,
    not an absent filter.  To simulate a truly missing filter we replace the function
    with one that fetches ALL users' workouts by explicitly querying each known user.
    """
    from src.analytics.workout_analysis import get_enriched_workouts as _real  # noqa: PLC0415

    def _unscoped(engine, start_date, end_date, user_id=None, **kwargs):
        """Simulates a broken WHERE clause — returns every user's workouts."""
        return _real(engine, start_date, end_date, user_id=USER_A_ID) + _real(
            engine, start_date, end_date, user_id=USER_B_ID
        )

    # Patch the name that the workouts route imported
    with patch("src.api.routes.workouts.get_enriched_workouts", side_effect=_unscoped):
        r = isolation_client.get(
            f"/api/workouts?start={QUERY_START}&end={QUERY_END}",
            headers=_auth(USER_A_ID),
        )

    assert r.status_code == 200
    ids = [w["id"] for w in r.json()]

    # With the filter removed, BOTH users' workouts appear
    assert B_WORKOUT_ID in ids, (
        "With user_id filter removed, User B's workout should be visible to User A. "
        "If this assertion fails, the negative test setup is wrong."
    )
    assert A_WORKOUT_ID in ids

    # Verify the correct implementation DOES prevent this (patch is no longer active)
    r_correct = isolation_client.get(
        f"/api/workouts?start={QUERY_START}&end={QUERY_END}",
        headers=_auth(USER_A_ID),
    )
    assert r_correct.status_code == 200
    correct_ids = [w["id"] for w in r_correct.json()]
    assert B_WORKOUT_ID not in correct_ids, (
        "With the real filter restored, B's workout must be invisible again"
    )
