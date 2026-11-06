"""Tests for GarminPersonalAuth (Personal API key -> bearer JWT)."""

import base64
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.clients import garmin_personal_auth as gpa
from src.clients.garmin_personal_auth import (
    KEY_PAGE_URL,
    TOKEN_PATH,
    GarminKeyError,
    GarminPersonalApiError,
    GarminPersonalAuth,
    GarminRateLimitError,
    GarminTransientError,
    get_default_auth,
    reset_default_auth,
)

BASE = "https://example.test"
KEY = "k123"


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def make_jwt(exp: datetime) -> str:
    return f"{_b64({'alg': 'none'})}.{_b64({'exp': int(exp.timestamp())})}."


def make_auth(handler, api_key: str = KEY):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return GarminPersonalAuth(api_key=api_key, base_url=BASE, http=http), calls


def ok(exp_delta: timedelta, pad: str = ""):
    jwt = make_jwt(datetime.now(UTC) + exp_delta)
    return jwt, lambda r: httpx.Response(200, text=pad.format(jwt) if pad else jwt)


def test_exchange_sends_apikey_header():
    _, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h)
    auth.get_token()
    assert len(calls) == 1
    r = calls[0]
    assert r.method == "POST"
    assert str(r.url) == f"{BASE}{TOKEN_PATH}"
    assert r.headers["Authorization"] == "ApiKey k123"
    assert r.content == b""


def test_get_token_returns_plaintext_jwt():
    jwt, h = ok(timedelta(hours=24), pad="  {}\n")
    auth, _ = make_auth(h)
    assert auth.get_token() == jwt
    assert auth.token_expires_at is not None


def test_token_cached_while_more_than_1h_left():
    _, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h)
    auth.get_token()
    auth.get_token()
    assert len(calls) == 1


def test_token_reexchanged_when_under_1h_left():
    _, h = ok(timedelta(minutes=30))
    auth, calls = make_auth(h)
    auth.get_token()
    auth.get_token()
    assert len(calls) == 2


def test_clock_is_patchable(monkeypatch):
    _, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h)
    auth.get_token()
    real = datetime.now(UTC)
    monkeypatch.setattr(gpa, "_now", lambda: real + timedelta(hours=23, minutes=30))
    auth.get_token()
    assert len(calls) == 2


def test_force_refresh_reexchanges():
    _, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h)
    auth.get_token()
    auth.get_token(force_refresh=True)
    assert len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403])
def test_rejected_key_raises(status):
    auth, _ = make_auth(lambda r: httpx.Response(status, text="nope"))
    with pytest.raises(GarminKeyError) as ei:
        auth.get_token()
    assert KEY_PAGE_URL in str(ei.value)
    assert KEY not in str(ei.value)


def test_missing_key_raises():
    _, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h, api_key="")
    with pytest.raises(GarminKeyError) as ei:
        auth.get_token()
    assert not calls
    assert KEY_PAGE_URL in str(ei.value)


def test_malformed_jwt_raises():
    auth, _ = make_auth(lambda r: httpx.Response(200, text="not-a-jwt"))
    with pytest.raises(GarminKeyError):
        auth.get_token()


def test_jwt_without_exp_raises():
    jwt = f"{_b64({'alg': 'none'})}.{_b64({'sub': 'x'})}."
    auth, _ = make_auth(lambda r: httpx.Response(200, text=jwt))
    with pytest.raises(GarminKeyError):
        auth.get_token()


def test_exchange_429_raises_rate_limit():
    auth, _ = make_auth(lambda r: httpx.Response(429))
    with pytest.raises(GarminRateLimitError):
        auth.get_token()


def _boom(request):
    raise httpx.ConnectError("down", request=request)


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(503),
    _boom,
])
def test_exchange_5xx_raises_transient(handler):
    auth, _ = make_auth(handler)
    with pytest.raises(GarminTransientError) as ei:
        auth.get_token()
    assert not isinstance(ei.value, GarminKeyError)
    assert auth.last_error is None


def test_last_error_set_and_cleared():
    state = {"status": 401}
    jwt = make_jwt(datetime.now(UTC) + timedelta(hours=24))

    def h(r):
        if state["status"] == 401:
            return httpx.Response(401)
        return httpx.Response(200, text=jwt)

    auth, _ = make_auth(h)
    with pytest.raises(GarminKeyError) as ei:
        auth.get_token()
    assert auth.last_error == str(ei.value)
    state["status"] = 200
    auth.get_token()
    assert auth.last_error is None


def test_get_default_auth_is_singleton():
    reset_default_auth()
    a = get_default_auth()
    assert get_default_auth() is a
    reset_default_auth()
    assert get_default_auth() is not a
    reset_default_auth()


def test_error_hierarchy():
    for cls in (GarminKeyError, GarminRateLimitError, GarminTransientError):
        assert issubclass(cls, GarminPersonalApiError)


def test_key_never_in_exception_text_or_logs(caplog):
    jwt = make_jwt(datetime.now(UTC) + timedelta(hours=24))
    handlers = [
        lambda r: httpx.Response(400),
        lambda r: httpx.Response(401),
        lambda r: httpx.Response(403),
        lambda r: httpx.Response(429),
        lambda r: httpx.Response(500),
        _boom,
        lambda r: httpx.Response(200, text="not-a-jwt"),
    ]
    with caplog.at_level(logging.DEBUG):
        for h in handlers:
            auth, _ = make_auth(h)
            with pytest.raises(GarminPersonalApiError) as ei:
                auth.get_token()
            assert KEY not in str(ei.value)
        auth, _ = make_auth(lambda r: httpx.Response(200, text=jwt))
        auth.get_token()
        auth, _ = make_auth(lambda r: httpx.Response(200, text=jwt), api_key="")
        with pytest.raises(GarminKeyError) as ei:
            auth.get_token()
        assert KEY not in str(ei.value)
    assert KEY not in caplog.text
    assert jwt not in caplog.text


def test_http_and_base_url_properties():
    _, h = ok(timedelta(hours=24))
    auth, _ = make_auth(h)
    assert isinstance(auth.http, httpx.Client)
    assert auth.base_url == BASE
    client = httpx.Client()
    a2 = GarminPersonalAuth(api_key="x", base_url=BASE + "/", http=client)
    assert a2.http is client
    assert a2.base_url == BASE


def test_force_refresh_race_exchanges_once():
    jwt, h = ok(timedelta(hours=24))
    auth, calls = make_auth(h)
    auth.get_token()
    assert len(calls) == 1
    # Simulate: this caller saw the old token, then another thread refreshed
    # before it got the lock. Emulate by holding the lock while swapping.
    stale = auth._token
    auth._lock.acquire()
    import threading

    result = []
    t = threading.Thread(target=lambda: result.append(auth.get_token(force_refresh=True)))
    # Make the thread's pre-lock snapshot the stale token, then refresh under it.
    t.start()
    import time

    time.sleep(0.1)
    auth._token = gpa.BearerToken(access_token=jwt, expires_at=stale.expires_at + timedelta(hours=1))
    auth._lock.release()
    t.join()
    assert result == [jwt]
    assert len(calls) == 1


def test_huge_exp_raises_key_error():
    tok = f"{_b64({'alg': 'none'})}.{_b64({'exp': 1e17})}."
    with pytest.raises(GarminKeyError):
        gpa.decode_jwt_exp(tok)


def test_reset_default_auth_closes_owned_client():
    reset_default_auth()
    a = get_default_auth()
    assert not a.http.is_closed
    reset_default_auth()
    assert a.http.is_closed
