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
    is_token_expired,
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
