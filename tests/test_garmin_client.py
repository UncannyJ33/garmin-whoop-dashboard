"""Tests for the Garmin API client."""

from datetime import date
from unittest.mock import MagicMock, call, patch

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from src.clients.garmin_client import GarminClient, _fmt_date

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connection_error(status_code: int) -> GarminConnectConnectionError:
    """Build a GarminConnectConnectionError that embeds a status code in the message."""
    return GarminConnectConnectionError(f"Error {status_code}: request failed")


def _make_client(api_mock: MagicMock, request_delay: float = 0.0) -> GarminClient:
    """Build a GarminClient whose auth always returns the given mock Garmin instance."""
    auth = MagicMock()
    auth.get_client.return_value = api_mock
    return GarminClient(auth=auth, request_delay=request_delay)


# ---------------------------------------------------------------------------
# _fmt_date
# ---------------------------------------------------------------------------


def test_fmt_date_from_date_object():
    assert _fmt_date(date(2024, 3, 15)) == "2024-03-15"


def test_fmt_date_from_string_passthrough():
    assert _fmt_date("2024-03-15") == "2024-03-15"


def test_fmt_date_from_datetime():
    from datetime import datetime

    assert _fmt_date(datetime(2024, 3, 15, 10, 30)) == "2024-03-15"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limit_sleeps_between_calls():
    """With a non-zero delay, time.sleep should be called before each API call."""
    api = MagicMock()
    api.get_stats.return_value = {}
    client = _make_client(api, request_delay=1.5)

    with patch("src.clients.garmin_client.time.sleep") as mock_sleep:
        # Force _last_call_time to 0 so elapsed ≈ 0 and the full delay is needed
        client._last_call_time = 0.0
        client.get_daily_summary("2024-03-15")

    # sleep must have been called at least once (once per sub-call in get_daily_summary)
    assert mock_sleep.called
    # Every sleep call should be <= request_delay (never oversleeping)
    for sleep_call in mock_sleep.call_args_list:
        assert sleep_call.args[0] <= 1.5


def test_no_sleep_when_delay_is_zero():
    """With request_delay=0 the sleep should never be called."""
    api = MagicMock()
    api.get_activities_by_date.return_value = []
    client = _make_client(api, request_delay=0.0)

    with patch("src.clients.garmin_client.time.sleep") as mock_sleep:
        client.get_activities("2024-01-01", "2024-01-31")

    mock_sleep.assert_not_called()


def test_rate_limit_not_called_when_enough_time_has_passed():
    """If elapsed >= request_delay, no sleep is needed."""
    api = MagicMock()
    api.get_activities_by_date.return_value = [{"id": 1}]
    client = _make_client(api, request_delay=1.5)

    with patch("src.clients.garmin_client.time.monotonic", return_value=1000.0):
        # _last_call_time = 0 → elapsed = 1000s >> 1.5s → no sleep
        client._last_call_time = 0.0
        with patch("src.clients.garmin_client.time.sleep") as mock_sleep:
            client.get_activities("2024-01-01", "2024-01-31")

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# get_activities
# ---------------------------------------------------------------------------


def test_get_activities_returns_list():
    api = MagicMock()
    api.get_activities_by_date.return_value = [{"activityId": 1}, {"activityId": 2}]
    client = _make_client(api)

    result = client.get_activities("2024-01-01", "2024-01-31")

    assert result == [{"activityId": 1}, {"activityId": 2}]
    api.get_activities_by_date.assert_called_once_with("2024-01-01", "2024-01-31")


def test_get_activities_returns_empty_list_on_404():
    api = MagicMock()
    api.get_activities_by_date.side_effect = _make_connection_error(404)
    client = _make_client(api)

    result = client.get_activities("2024-01-01", "2024-01-31")

    assert result == []


def test_get_activities_returns_empty_list_on_unexpected_error():
    api = MagicMock()
    api.get_activities_by_date.side_effect = RuntimeError("network failure")
    client = _make_client(api)

    result = client.get_activities("2024-01-01", "2024-01-31")

    assert result == []


# ---------------------------------------------------------------------------
# get_activity_detail
# ---------------------------------------------------------------------------


def test_get_activity_detail_returns_dict():
    api = MagicMock()
    api.get_activity.return_value = {"activityId": "123", "distance": 10000}
    client = _make_client(api)

    result = client.get_activity_detail(123)

    assert result == {"activityId": "123", "distance": 10000}
    api.get_activity.assert_called_once_with("123")


def test_get_activity_detail_returns_none_on_404():
    api = MagicMock()
    api.get_activity.side_effect = _make_connection_error(404)
    client = _make_client(api)

    assert client.get_activity_detail("missing") is None


# ---------------------------------------------------------------------------
# get_daily_summary
# ---------------------------------------------------------------------------


def test_get_daily_summary_merges_all_sources():
    api = MagicMock()
    api.get_stats.return_value = {"totalSteps": 8000}
    api.get_heart_rates.return_value = {"restingHeartRate": 55}
    api.get_body_battery.return_value = [{"charged": 80}]
    api.get_stress_data.return_value = {"avgStressLevel": 25}
    client = _make_client(api)

    result = client.get_daily_summary("2024-03-15")

    assert result["totalSteps"] == 8000
    assert result["restingHeartRate"] == 55
    assert result["charged"] == 80
    assert result["avgStressLevel"] == 25


def test_get_daily_summary_tolerates_failed_sub_calls():
    """A 404 on one sub-endpoint should not prevent the others from running."""
    api = MagicMock()
    api.get_stats.return_value = {"totalSteps": 5000}
    api.get_heart_rates.side_effect = _make_connection_error(404)
    api.get_body_battery.side_effect = _make_connection_error(404)
    api.get_stress_data.return_value = {"avgStressLevel": 30}
    client = _make_client(api)

    result = client.get_daily_summary("2024-03-15")

    assert result["totalSteps"] == 5000
    assert result["avgStressLevel"] == 30
    # missing endpoints contribute nothing, not an exception
    assert "restingHeartRate" not in result


def test_get_daily_summary_empty_body_battery_list():
    """Empty body battery list should not crash the merge."""
    api = MagicMock()
    api.get_stats.return_value = {}
    api.get_heart_rates.return_value = {}
    api.get_body_battery.return_value = []
    api.get_stress_data.return_value = {}
    client = _make_client(api)

    result = client.get_daily_summary("2024-03-15")
    assert result == {}


# ---------------------------------------------------------------------------
# get_sleep / get_hrv
# ---------------------------------------------------------------------------


def test_get_sleep_returns_dict():
    api = MagicMock()
    api.get_sleep_data.return_value = {"dailySleepDTO": {"sleepTimeSeconds": 28800}}
    client = _make_client(api)

    result = client.get_sleep("2024-03-15")

    assert result["dailySleepDTO"]["sleepTimeSeconds"] == 28800
    api.get_sleep_data.assert_called_once_with("2024-03-15")


def test_get_sleep_returns_none_on_400():
    api = MagicMock()
    api.get_sleep_data.side_effect = _make_connection_error(400)
    client = _make_client(api)

    assert client.get_sleep("2024-03-15") is None


def test_get_hrv_returns_dict():
    api = MagicMock()
    api.get_hrv_data.return_value = {"hrvSummary": {"lastNight": 62}}
    client = _make_client(api)

    result = client.get_hrv("2024-03-15")

    assert result["hrvSummary"]["lastNight"] == 62


def test_get_hrv_returns_none_on_404():
    api = MagicMock()
    api.get_hrv_data.side_effect = _make_connection_error(404)
    client = _make_client(api)

    assert client.get_hrv("2024-03-15") is None


# ---------------------------------------------------------------------------
# 401 retry — re-auth then retry once
# ---------------------------------------------------------------------------


def test_401_triggers_reauth_and_retries():
    """On a 401, the client should clear auth, then retry the call once."""
    api_stale = MagicMock()
    api_stale.get_activities_by_date.side_effect = GarminConnectAuthenticationError("session expired")

    api_fresh = MagicMock()
    api_fresh.get_activities_by_date.return_value = [{"activityId": 99}]

    auth = MagicMock()
    auth.get_client.side_effect = [api_stale, api_fresh]

    client = GarminClient(auth=auth, request_delay=0.0)
    result = client.get_activities("2024-01-01", "2024-01-31")

    assert result == [{"activityId": 99}]
    # Auth client was cleared to force rebuild
    assert auth._client is None or auth.get_client.call_count == 2


def test_401_does_not_retry_twice():
    """If the retry also returns 401, return None rather than looping."""
    api = MagicMock()
    api.get_activities_by_date.side_effect = GarminConnectAuthenticationError("still expired")

    auth = MagicMock()
    auth.get_client.return_value = api

    client = GarminClient(auth=auth, request_delay=0.0)
    result = client.get_activities("2024-01-01", "2024-01-31")

    assert result == []
    assert auth.get_client.call_count == 2


# ---------------------------------------------------------------------------
# 429 retry — sleep 60s then retry once
# ---------------------------------------------------------------------------


def test_429_sleeps_60s_and_retries():
    """On a 429, client should sleep 60 seconds then retry once."""
    api_first = MagicMock()
    api_first.get_stats.side_effect = GarminConnectTooManyRequestsError("rate limited")

    api_retry = MagicMock()
    api_retry.get_stats.return_value = {"totalSteps": 9000}
    api_retry.get_heart_rates.return_value = {}
    api_retry.get_body_battery.return_value = []
    api_retry.get_stress_data.return_value = {}

    auth = MagicMock()
    auth.get_client.side_effect = [api_first, api_retry, api_retry, api_retry]

    client = GarminClient(auth=auth, request_delay=0.0)

    with patch("src.clients.garmin_client.time.sleep") as mock_sleep:
        result = client.get_daily_summary("2024-03-15")

    # 60-second sleep must have been triggered for the 429
    assert call(60.0) in mock_sleep.call_args_list
    assert result["totalSteps"] == 9000


def test_429_does_not_retry_twice():
    """If the retry also returns 429, return None rather than looping."""
    api = MagicMock()
    api.get_sleep_data.side_effect = GarminConnectTooManyRequestsError("rate limited")

    auth = MagicMock()
    auth.get_client.return_value = api

    client = GarminClient(auth=auth, request_delay=0.0)

    with patch("src.clients.garmin_client.time.sleep"):
        result = client.get_sleep("2024-03-15")

    assert result is None
    assert auth.get_client.call_count == 2
