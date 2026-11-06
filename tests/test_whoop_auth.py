"""Tests for the Whoop OAuth 2.0 module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.clients.whoop_auth import (
    SCOPES,
    WHOOP_AUTH_URL,
    WhoopAuth,
    WhoopAuthError,
    WhoopReauthRequired,
    is_token_expired,
    set_whoop_auth_error,
    whoop_auth_error,
)
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import TokenStore

IN_MEMORY = "sqlite:///:memory:"


@pytest.fixture
def engine():
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = get_session_factory(engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def auth():
    return WhoopAuth()


# ---------------------------------------------------------------------------
# Authorization URL generation
# ---------------------------------------------------------------------------


def test_get_authorization_url_base(auth):
    """URL must point to the Whoop authorization endpoint."""
    url, _ = auth.get_authorization_url()
    assert url.startswith(WHOOP_AUTH_URL)


def test_get_authorization_url_required_params(auth):
    """URL must include all required OAuth query parameters."""
    url, state = auth.get_authorization_url()
    params = parse_qs(urlparse(url).query, keep_blank_values=True)

    assert params["response_type"] == ["code"]
    assert params["state"] == [state]
    assert "client_id" in params
    assert "redirect_uri" in params
    assert "scope" in params


def test_get_authorization_url_all_scopes(auth):
    """All required Whoop scopes must be present in the URL."""
    url, _ = auth.get_authorization_url()
    params = parse_qs(urlparse(url).query)
    scope_str = params["scope"][0]

    for scope in SCOPES:
        assert scope in scope_str


def test_get_authorization_url_unique_state(auth):
    """Each call must produce a different CSRF state token."""
    _, state1 = auth.get_authorization_url()
    _, state2 = auth.get_authorization_url()
    assert state1 != state2


def test_get_authorization_url_state_length(auth):
    """State token must be long enough to be unguessable (>= 32 chars)."""
    _, state = auth.get_authorization_url()
    assert len(state) >= 32


# ---------------------------------------------------------------------------
# Token expiry detection
# ---------------------------------------------------------------------------


def _make_token(expires_at: datetime) -> TokenStore:
    record = TokenStore(
        service="whoop",
        access_token="tok",
        expires_at=expires_at.isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    return record


def test_is_token_expired_past(auth):
    """Token with expires_at in the past is expired."""
    record = _make_token(datetime.now(tz=UTC) - timedelta(hours=2))
    assert is_token_expired(record) is True


def test_is_token_not_expired_future(auth):
    """Token expiring well into the future is valid."""
    record = _make_token(datetime.now(tz=UTC) + timedelta(hours=1))
    assert is_token_expired(record) is False


def test_is_token_expired_within_buffer(auth):
    """Token expiring within the 5-minute buffer window is treated as expired."""
    record = _make_token(datetime.now(tz=UTC) + timedelta(minutes=3))
    assert is_token_expired(record) is True


def test_is_token_expired_no_expires_at(auth):
    """Missing expires_at is treated as expired."""
    record = TokenStore(
        service="whoop",
        access_token="tok",
        expires_at=None,
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    assert is_token_expired(record) is True


# ---------------------------------------------------------------------------
# Token exchange (mocked HTTP)
# ---------------------------------------------------------------------------


def _mock_token_response(access_token: str = "access-123") -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "access_token": access_token,
        "refresh_token": "refresh-xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
async def test_exchange_code_stores_tokens(auth, db):
    """exchange_code must persist access and refresh tokens to the DB."""
    mock_response = _mock_token_response("access-from-exchange")

    with patch("src.clients.whoop_auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value.post = AsyncMock(return_value=mock_response)

        record = await auth.exchange_code("auth-code-abc", db)

    assert record.access_token == "access-from-exchange"
    assert record.refresh_token == "refresh-xyz"
    assert record.expires_at is not None
    assert db.get(TokenStore, "whoop") is not None


@pytest.mark.asyncio
async def test_exchange_code_raises_on_http_error(auth, db):
    """exchange_code must raise WhoopAuthError on a non-2xx response."""
    import httpx

    with patch("src.clients.whoop_auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        error_response = MagicMock()
        error_response.status_code = 401
        MockClient.return_value.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=error_response
            )
        )

        with pytest.raises(WhoopAuthError, match="401"):
            await auth.exchange_code("bad-code", db)


# ---------------------------------------------------------------------------
# Token refresh (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_updates_access_token(auth, db):
    """refresh_access_token must update the stored access token."""
    # Seed an existing expired token
    expired = TokenStore(
        service="whoop",
        access_token="old-access",
        refresh_token="valid-refresh",
        expires_at=(datetime.now(tz=UTC) - timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(expired)
    db.commit()

    mock_response = _mock_token_response("new-access-token")

    with patch("src.clients.whoop_auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value.post = AsyncMock(return_value=mock_response)

        record = await auth.refresh_access_token(db)

    assert record.access_token == "new-access-token"


@pytest.mark.asyncio
async def test_refresh_token_raises_when_no_token(auth, db):
    """refresh_access_token must raise WhoopAuthError when no token exists."""
    with pytest.raises(WhoopAuthError, match="OAuth flow"):
        await auth.refresh_access_token(db)


# ---------------------------------------------------------------------------
# get_valid_token auto-refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_valid_token_returns_unexpired(auth, db):
    """get_valid_token returns the stored token without refreshing if valid."""
    fresh = TokenStore(
        service="whoop",
        access_token="still-valid",
        refresh_token="refresh-xyz",
        expires_at=(datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(fresh)
    db.commit()

    with patch.object(auth, "refresh_access_token") as mock_refresh:
        token = await auth.get_valid_token(db)

    assert token == "still-valid"
    mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_get_valid_token_auto_refreshes_expired(auth, db):
    """get_valid_token triggers a refresh when the stored token is expired."""
    expired = TokenStore(
        service="whoop",
        access_token="old-access",
        refresh_token="valid-refresh",
        expires_at=(datetime.now(tz=UTC) - timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(expired)
    db.commit()

    refreshed = TokenStore(
        service="whoop",
        access_token="refreshed-access",
        refresh_token="valid-refresh",
        expires_at=(datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    with patch.object(auth, "refresh_access_token", return_value=refreshed) as mock_refresh:
        token = await auth.get_valid_token(db)

    assert token == "refreshed-access"
    mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_get_valid_token_raises_when_not_authenticated(auth, db):
    """get_valid_token raises WhoopAuthError when no token row exists."""
    with pytest.raises(WhoopAuthError, match="Not authenticated"):
        await auth.get_valid_token(db)


# ---------------------------------------------------------------------------
# _store_tokens edge cases
# ---------------------------------------------------------------------------

from src.clients.whoop_auth import _store_tokens  # noqa: E402


def test_store_tokens_creates_new_record(db):
    """_store_tokens creates a TokenStore row when none exists yet."""
    token_data = {
        "access_token": "acc-new",
        "refresh_token": "ref-new",
        "expires_in": 3600,
    }
    record = _store_tokens(token_data, db)
    assert record.access_token == "acc-new"
    assert record.refresh_token == "ref-new"
    assert record.expires_at is not None
    assert db.get(TokenStore, "whoop") is not None


def test_store_tokens_updates_existing_record(db):
    """_store_tokens overwrites an existing token row with new values."""
    existing = TokenStore(
        service="whoop",
        access_token="old-acc",
        refresh_token="old-ref",
        expires_at=(datetime.now(tz=UTC) - timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(existing)
    db.commit()

    token_data = {
        "access_token": "new-acc",
        "refresh_token": "new-ref",
        "expires_in": 3600,
    }
    record = _store_tokens(token_data, db)
    assert record.access_token == "new-acc"
    assert record.refresh_token == "new-ref"


def test_store_tokens_preserves_refresh_token_when_absent(db):
    """When the server omits refresh_token (refresh flow), the stored value is kept."""
    existing = TokenStore(
        service="whoop",
        access_token="old-acc",
        refresh_token="keep-this-refresh",
        expires_at=(datetime.now(tz=UTC) - timedelta(hours=1)).isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(existing)
    db.commit()

    # Refresh response — no refresh_token field
    token_data = {"access_token": "refreshed-acc", "expires_in": 3600}
    record = _store_tokens(token_data, db)

    assert record.access_token == "refreshed-acc"
    assert record.refresh_token == "keep-this-refresh"


def test_store_tokens_custom_expires_in(db):
    """expires_in value from server is used to compute expires_at correctly."""
    before = datetime.now(tz=UTC)
    token_data = {"access_token": "tok", "expires_in": 7200}
    record = _store_tokens(token_data, db)
    after = datetime.now(tz=UTC)

    expires_at = datetime.fromisoformat(record.expires_at)
    assert (expires_at - before).total_seconds() >= 7200
    assert (expires_at - after).total_seconds() <= 7200


# ---------------------------------------------------------------------------
# is_token_expired — naive datetime handling
# ---------------------------------------------------------------------------


def test_is_token_expired_naive_datetime():
    """A naive (no tzinfo) expires_at string is treated as UTC and not expired."""
    future_naive = (datetime.now(tz=UTC) + timedelta(hours=1)).replace(tzinfo=None)
    record = TokenStore(
        service="whoop",
        access_token="tok",
        expires_at=future_naive.isoformat(),
        updated_at=datetime.now(tz=UTC).isoformat(),
    )
    assert is_token_expired(record) is False


# ---------------------------------------------------------------------------
# Refresh hardening: lock, force, rotation, re-auth state
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402

import httpx  # noqa: E402

from src.clients import whoop_auth as whoop_auth_mod  # noqa: E402

_RealAsyncClient = httpx.AsyncClient


def _seed(db, *, expired: bool, refresh_token: str = "stored-refresh") -> None:
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    db.add(
        TokenStore(
            service="whoop",
            access_token="old-access",
            refresh_token=refresh_token,
            expires_at=(datetime.now(tz=UTC) + delta).isoformat(),
            updated_at=datetime.now(tz=UTC).isoformat(),
        )
    )
    db.commit()


def _transport_client(handler):
    """Patch whoop_auth's AsyncClient to a real client over a MockTransport."""
    return patch(
        "src.clients.whoop_auth.httpx.AsyncClient",
        side_effect=lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_concurrent_refresh_single_post(auth, db):
    """Two get_valid_token calls on an expired row cause exactly one refresh POST."""
    _seed(db, expired=True)
    posts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.content.decode())
        await asyncio.sleep(0)
        return httpx.Response(
            200, json={"access_token": "new-access", "refresh_token": "r2", "expires_in": 3600}
        )

    with _transport_client(handler):
        tokens = await asyncio.gather(auth.get_valid_token(db), auth.get_valid_token(db))

    assert len(posts) == 1
    assert tokens == ["new-access", "new-access"]


class _SpyLock:
    """threading.Lock wrapper that signals on acquire calls (for deterministic tests)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquires = 0
        self.second_call = threading.Event()
        self.second_returned = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self.acquires += 1
        n = self.acquires
        if n == 2:
            self.second_call.set()
        got = self._lock.acquire(blocking, timeout)
        if n == 2 and got:
            self.second_returned.set()
        return got

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


@pytest.mark.asyncio
async def test_refresh_lock_serialises_across_threads(auth, tmp_path):
    """A refresh on another loop/session blocks on the lock, then re-reads and skips the POST."""
    engine = get_engine(f"sqlite:///{tmp_path / 'tok.db'}")
    run_migrations(engine=engine)
    Session = get_session_factory(engine)
    with Session() as seed_db:
        _seed(seed_db, expired=True)
    posts: list[str] = []
    in_post = threading.Event()
    release_post = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.content.decode())
        in_post.set()
        assert release_post.wait(10)
        return httpx.Response(
            200, json={"access_token": "new-access", "refresh_token": "r2", "expires_in": 3600}
        )

    results: dict[str, str] = {}

    def run(name: str, direct: bool) -> None:
        async def go() -> None:
            with Session() as session:
                if direct:
                    results[name] = (await auth.refresh_access_token(session)).access_token
                else:
                    results[name] = await auth.get_valid_token(session)

        asyncio.run(go())

    spy = _SpyLock()
    with patch.object(whoop_auth_mod, "_REFRESH_LOCK", spy), _transport_client(handler):
        t1 = threading.Thread(target=run, args=("a", False))
        t1.start()
        assert in_post.wait(10)  # t1 holds the lock, mid-POST
        t2 = threading.Thread(target=run, args=("b", True))
        t2.start()
        assert spy.second_call.wait(10)  # t2 reached the lock
        assert not spy.second_returned.is_set()  # ...and is blocked on it
        release_post.set()
        t1.join(10)
        t2.join(10)

    engine.dispose()
    assert spy.acquires == 2
    assert len(posts) == 1
    assert results == {"a": "new-access", "b": "new-access"}


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leak_lock(auth, db):
    _seed(db, expired=True)
    spy = _SpyLock()
    assert spy.acquire()  # holder (call 1)
    with patch.object(whoop_auth_mod, "_REFRESH_LOCK", spy):
        task = asyncio.create_task(auth.refresh_access_token(db))
        assert await asyncio.to_thread(spy.second_call.wait, 10)  # waiter parked in executor
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        spy.release()  # worker now wins the lock after the waiter is gone
        assert await asyncio.to_thread(spy.second_returned.wait, 10)
        for _ in range(200):
            if not spy.locked():
                break
            await asyncio.sleep(0.01)
        assert not spy.locked()


@pytest.mark.asyncio
async def test_stale_rejection_does_not_flag_after_reconnect(auth, engine, db):
    """A 400 for a refresh token rotated by a concurrent reconnect must not set the flag."""
    _seed(db, expired=True, refresh_token="old-refresh")

    def handler(request: httpx.Request) -> httpx.Response:
        with get_session_factory(engine)() as other:  # reconnect lands mid-POST
            row = other.get(TokenStore, "whoop")
            row.refresh_token = "reconnected-refresh"
            other.commit()
        return httpx.Response(400, json={"error": "invalid_grant"})

    with _transport_client(handler):
        with pytest.raises(WhoopAuthError, match="rotated concurrently") as exc_info:
            await auth.refresh_access_token(db)
    assert not isinstance(exc_info.value, WhoopReauthRequired)
    assert whoop_auth_error(None, db) is None
    assert db.get(TokenStore, "whoop").refresh_token == "reconnected-refresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [None, ""])
async def test_row_without_refresh_token_flags_reauth(auth, db, empty):
    _seed(db, expired=True)
    db.get(TokenStore, "whoop").refresh_token = empty
    db.commit()
    with pytest.raises(WhoopReauthRequired):
        await auth.refresh_access_token(db)
    assert whoop_auth_error(None, db) is not None
    assert db.get(TokenStore, "whoop") is not None


@pytest.mark.asyncio
async def test_forced_refresh_posts_even_when_unexpired(auth, db):
    _seed(db, expired=False)
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.content.decode())
        return httpx.Response(200, json={"access_token": "forced-access", "expires_in": 3600})

    with _transport_client(handler):
        record = await auth.refresh_access_token(db, force=True)

    assert len(posts) == 1
    assert "refresh_token=stored-refresh" in posts[0]
    assert record.access_token == "forced-access"


@pytest.mark.asyncio
async def test_unforced_refresh_skips_post_when_row_already_fresh(auth, db):
    _seed(db, expired=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not POST")

    with _transport_client(handler):
        record = await auth.refresh_access_token(db)
    assert record.access_token == "old-access"


@pytest.mark.asyncio
async def test_refresh_rereads_row_changed_by_other_session(auth, engine, db):
    """The refresh uses the re-read refresh_token, not a stale identity-map copy."""
    _seed(db, expired=True, refresh_token="stale-refresh")
    db.get(TokenStore, "whoop")  # populate identity map
    with get_session_factory(engine)() as other:
        row = other.get(TokenStore, "whoop")
        row.refresh_token = "rotated-refresh"
        other.commit()
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.content.decode())
        return httpx.Response(200, json={"access_token": "n", "expires_in": 3600})

    with _transport_client(handler):
        await auth.refresh_access_token(db)
    assert "refresh_token=rotated-refresh" in posts[0]


@pytest.mark.asyncio
async def test_refresh_persists_rotated_refresh_token(auth, db):
    _seed(db, expired=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "n", "refresh_token": "rotated", "expires_in": 3600}
        )

    with _transport_client(handler):
        record = await auth.refresh_access_token(db)
    assert record.refresh_token == "rotated"
    assert db.get(TokenStore, "whoop").refresh_token == "rotated"


@pytest.mark.asyncio
async def test_refresh_400_raises_reauth_and_keeps_row(auth, db):
    _seed(db, expired=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with _transport_client(handler):
        with pytest.raises(WhoopReauthRequired) as exc_info:
            await auth.refresh_access_token(db)
    assert isinstance(exc_info.value, WhoopAuthError)
    assert "stored-refresh" not in str(exc_info.value)
    assert db.get(TokenStore, "whoop") is not None
    assert whoop_auth_error(None, db) == str(exc_info.value)


@pytest.mark.asyncio
async def test_refresh_503_raises_auth_error_without_reauth_state(auth, db):
    _seed(db, expired=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with _transport_client(handler):
        with pytest.raises(WhoopAuthError) as exc_info:
            await auth.refresh_access_token(db)
    assert not isinstance(exc_info.value, WhoopReauthRequired)
    assert whoop_auth_error(None, db) is None


@pytest.mark.asyncio
async def test_successful_refresh_clears_auth_error(auth, db):
    _seed(db, expired=True)
    set_whoop_auth_error(None, "reconnect Whoop", db)
    assert whoop_auth_error(None, db) == "reconnect Whoop"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "n", "expires_in": 3600})

    with _transport_client(handler):
        await auth.refresh_access_token(db)
    assert whoop_auth_error(None, db) is None


@pytest.mark.asyncio
async def test_refresh_lock_timeout_raises(auth, db):
    _seed(db, expired=True)
    with patch.object(whoop_auth_mod, "_REFRESH_LOCK_TIMEOUT_S", 0.05):
        assert whoop_auth_mod._REFRESH_LOCK.acquire(blocking=False)
        try:
            with pytest.raises(WhoopAuthError, match="Timed out"):
                await auth.refresh_access_token(db)
        finally:
            whoop_auth_mod._REFRESH_LOCK.release()


def test_auth_error_helpers_edge_cases(db):
    # no row: no-op / None
    assert whoop_auth_error("u1", db) is None
    set_whoop_auth_error("u1", "x", db)
    assert db.get(TokenStore, "whoop_u1") is None
    # NULL and non-JSON token_data_json read as "no error"
    db.add(
        TokenStore(
            service="whoop_u1",
            access_token="a",
            refresh_token="r",
            expires_at="x",
            updated_at="x",
            user_id="u1",
        )
    )
    db.commit()
    assert whoop_auth_error("u1", db) is None
    db.get(TokenStore, "whoop_u1").token_data_json = "not json"
    db.commit()
    assert whoop_auth_error("u1", db) is None
    # set then clear
    set_whoop_auth_error("u1", "boom", db)
    assert whoop_auth_error("u1", db) == "boom"
    set_whoop_auth_error("u1", None, db)
    assert whoop_auth_error("u1", db) is None
    assert json.loads(db.get(TokenStore, "whoop_u1").token_data_json) == {}
