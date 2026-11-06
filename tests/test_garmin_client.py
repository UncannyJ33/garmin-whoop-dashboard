"""Tests for the Garmin Personal API client (httpx.MockTransport, stub auth)."""

import json
import logging
from datetime import date
from pathlib import Path

import httpx
import pytest

from src.clients import garmin_client as gc
from src.clients.garmin_client import GarminClient
from src.clients.garmin_personal_auth import (
    GarminKeyError,
    GarminRateLimitError,
    GarminTransientError,
)

FIX = Path(__file__).parent / "fixtures" / "garmin_personal"
BASE = "https://personal.connectapi.garmin.com"


def _fixture(name: str):
    return json.loads((FIX / name).read_text())


class StubAuth:
    """Returns t1, or t2 after a forced refresh."""

    base_url = BASE

    def __init__(self) -> None:
        self.http: httpx.Client | None = None
        self.refreshed = False

    def get_token(self, force_refresh: bool = False) -> str:
        if force_refresh:
            self.refreshed = True
        return "t2" if self.refreshed else "t1"


def make_client(handler, delay: float = 0.0):
    reqs: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        reqs.append(request)
        return handler(request, len(reqs))

    auth = StubAuth()
    auth.http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return GarminClient(auth=auth, request_delay=delay), reqs


def test_requests_use_bearer_and_base_url():
    client, reqs = make_client(lambda r, n: httpx.Response(200, json={"a": 1}))
    client.get_daily_summary("2026-11-01")
    assert str(reqs[0].url).startswith(BASE + "/")
    assert reqs[0].headers["Authorization"] == "Bearer t1"
    assert reqs[0].headers["Accept"] == "application/json"


def test_get_activities_pages_until_short_page():
    def h(r, n):
        return httpx.Response(
            200, json=[{"activityId": n * 1000 + i} for i in range(100 if n == 1 else 3)]
        )

    client, reqs = make_client(h)
    out = client.get_activities("2026-10-01", "2026-10-31")
    assert len(out) == 103
    p = reqs[1].url.params
    assert (p["start"], p["limit"]) == ("100", "100")
    assert (p["startDate"], p["endDate"]) == ("2026-10-01", "2026-10-31")


def test_get_activities_exact_page_stops_on_empty():
    def h(r, n):
        return httpx.Response(200, json=[{"activityId": i} for i in range(100)] if n == 1 else [])

    client, reqs = make_client(h)
    assert len(client.get_activities(date(2026, 10, 1), date(2026, 10, 31))) == 100
    assert len(reqs) == 2


def test_get_activities_fixture_parses():
    client, _ = make_client(lambda r, n: httpx.Response(200, json=_fixture("activities.json")))
    out = client.get_activities("2026-10-01", "2026-10-31")
    assert isinstance(out, list) and isinstance(out[0]["activityId"], int)


def test_get_daily_summary_single_call():
    fx = _fixture("daily_summary.json")
    client, reqs = make_client(lambda r, n: httpx.Response(200, json=fx))
    assert client.get_daily_summary("2026-11-01") == fx
    assert len(reqs) == 1
    assert reqs[0].url.path == "/usersummary-service/usersummary/daily"
    assert reqs[0].url.params["calendarDate"] == "2026-11-01"


def test_get_daily_summary_no_data_returns_empty_dict():
    client, _ = make_client(lambda r, n: httpx.Response(204))
    assert client.get_daily_summary("2026-11-01") == {}


def test_get_sleep_returns_flat_dto():
    client, reqs = make_client(lambda r, n: httpx.Response(200, json=_fixture("sleep.json")))
    result = client.get_sleep("2026-11-01")
    assert "sleepTimeSeconds" in result
    assert "dailySleepDTO" not in result
    assert reqs[0].url.path == "/sleep-service/sleep/dailySleep"
    assert reqs[0].url.params["date"] == "2026-11-01"


def test_get_sleep_all_null_dto_is_none():
    client, _ = make_client(lambda r, n: httpx.Response(200, json=_fixture("sleep_empty.json")))
    assert client.get_sleep("2026-11-01") is None


def test_get_daily_summary_all_null_returns_empty_dict():
    client, _ = make_client(lambda r, n: httpx.Response(200, json={"a": None, "b": {}, "c": []}))
    assert client.get_daily_summary("2026-11-01") == {}


def test_get_user_settings_404_raises():
    client, _ = make_client(lambda r, n: httpx.Response(404))
    with pytest.raises(GarminTransientError):
        client.get_user_settings()


@pytest.mark.parametrize(
    "resp", [httpx.Response(200, json={"a": 1}), httpx.Response(204), httpx.Response(404)]
)
def test_non_list_activities_raises(resp):
    client, _ = make_client(lambda r, n: resp)
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")


def test_page2_400_raises():
    def h(r, n):
        if n == 1:
            return httpx.Response(200, json=[{"activityId": i} for i in range(100)])
        return httpx.Response(400)

    client, _ = make_client(h)
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")


def test_repeated_first_activity_id_raises():
    client, reqs = make_client(
        lambda r, n: httpx.Response(200, json=[{"activityId": i} for i in range(100)])
    )
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")
    assert len(reqs) == 2


def test_oversized_page_raises():
    client, _ = make_client(
        lambda r, n: httpx.Response(200, json=[{"activityId": i} for i in range(101)])
    )
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")


def test_page_cap_raises(monkeypatch):
    monkeypatch.setattr(gc, "_MAX_PAGES", 3)
    client, reqs = make_client(
        lambda r, n: httpx.Response(200, json=[{"activityId": n * 1000 + i} for i in range(100)])
    )
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")
    assert len(reqs) == 3


@pytest.mark.parametrize("status", [422, 302])
def test_other_non_2xx_raises(status):
    client, _ = make_client(lambda r, n: httpx.Response(status))
    with pytest.raises(GarminTransientError):
        client.get_daily_summary("2026-11-01")


def test_html_200_raises():
    client, _ = make_client(lambda r, n: httpx.Response(200, content=b"<html>"))
    with pytest.raises(GarminTransientError):
        client.get_sleep("2026-11-01")


def test_decoding_error_is_transient():
    def h(r, n):
        raise httpx.DecodingError("bad gzip")

    client, _ = make_client(h)
    with pytest.raises(GarminTransientError):
        client.get_daily_summary("2026-11-01")


def test_get_sleep_empty_returns_none():
    client, _ = make_client(lambda r, n: httpx.Response(200, json={}))
    assert client.get_sleep("2026-11-01") is None


def test_get_hrv_204_returns_none():
    client, reqs = make_client(lambda r, n: httpx.Response(204))
    assert client.get_hrv("2026-11-01") is None
    assert reqs[0].url.path == "/hrv-service/hrv/2026-11-01"


def test_get_hrv_null_summary_returns_none():
    client, _ = make_client(
        lambda r, n: httpx.Response(200, json={"hrvSummary": None, "hrvReadings": []})
    )
    assert client.get_hrv("2026-11-01") is None


def test_get_user_settings():
    fx = _fixture("user_settings.json")
    client, reqs = make_client(lambda r, n: httpx.Response(200, json=fx))
    assert client.get_user_settings() == fx
    assert reqs[0].url.path == "/userprofile-service/userprofile/settings"


def test_401_retries_once_with_forced_refresh():
    def h(r, n):
        return httpx.Response(401 if n == 1 else 200, json={"totalSteps": 1})

    client, reqs = make_client(h)
    assert client.get_daily_summary("2026-11-01") == {"totalSteps": 1}
    assert len(reqs) == 2
    assert reqs[1].headers["Authorization"] == "Bearer t2"


def test_401_twice_raises_key_error():
    client, reqs = make_client(lambda r, n: httpx.Response(401))
    with pytest.raises(GarminKeyError):
        client.get_daily_summary("2026-11-01")
    assert len(reqs) == 2
    assert "rejected the bearer token twice" in client._auth.last_error


def test_403_raises_key_error_without_retry():
    client, reqs = make_client(lambda r, n: httpx.Response(403))
    with pytest.raises(GarminKeyError):
        client.get_daily_summary("2026-11-01")
    assert len(reqs) == 1


def test_429_raises_rate_limit(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", lambda s: slept.append(s))
    client, reqs = make_client(lambda r, n: httpx.Response(429))
    with pytest.raises(GarminRateLimitError):
        client.get_daily_summary("2026-11-01")
    assert len(reqs) == 1
    assert slept == []


def test_404_returns_none_and_logs_warning(caplog):
    client, _ = make_client(lambda r, n: httpx.Response(404))
    with caplog.at_level(logging.WARNING):
        assert client.get_hrv("2026-11-01") is None
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


@pytest.mark.parametrize("failure", [500, 502, "connect"])
def test_5xx_raises_transient(failure):
    def h(r, n):
        if failure == "connect":
            raise httpx.ConnectError("boom")
        return httpx.Response(failure)

    client, reqs = make_client(h)
    with pytest.raises(GarminTransientError):
        client.get_activities("2026-10-01", "2026-10-31")
    assert len(reqs) == 1


def test_request_delay_enforced(monkeypatch):
    now = [100.0]
    slept: list[float] = []
    monkeypatch.setattr(gc.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        gc.time, "sleep", lambda s: (slept.append(s), now.__setitem__(0, now[0] + s))
    )
    client, _ = make_client(lambda r, n: httpx.Response(200, json={"a": 1}), delay=1.0)
    client.get_daily_summary("2026-11-01")
    client.get_daily_summary("2026-11-02")
    assert slept and sum(slept) == pytest.approx(1.0)


def test_default_delay_is_one_second():
    assert GarminClient(auth=StubAuth()).__dict__["_request_delay"] == 1.0


def test_get_daily_summary_metrics_all_null_returns_empty_dict():
    body = {
        "calendarDate": "2026-11-01",
        "userProfileId": 1,
        "displayName": "x",
        "source": "...",
        "includesWellnessData": False,
        "includesActivityData": False,
        "includesCalorieConsumedData": False,
        "totalSteps": None,
        "averageSpo2": None,
        "bodyBatteryHighestValue": None,
    }
    client, _ = make_client(lambda r, n: httpx.Response(200, json=body))
    assert client.get_daily_summary("2026-11-01") == {}


def test_get_daily_summary_single_metric_is_data():
    body = {"calendarDate": "2026-11-01", "totalSteps": 5, "averageSpo2": None}
    client, _ = make_client(lambda r, n: httpx.Response(200, json=body))
    assert client.get_daily_summary("2026-11-01") == body
