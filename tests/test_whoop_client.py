"""Tests for the Whoop API client — pagination, retries, and error handling."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.whoop_client import WhoopAPIError, WhoopClient

START = "2024-03-01T00:00:00Z"
END = "2024-03-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(status_code: int, json_data: dict) -> MagicMock:
    """Build a mock httpx response."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.text = str(json_data)
    return r


def make_page(records: list, next_token: str | None = None) -> dict:
    """Build a Whoop-style paginated response body."""
    return {"records": records, "next_token": next_token}


@contextmanager
def mock_http(*responses):
    """Patch httpx.AsyncClient so sequential .get() calls return the given responses."""
    mock_instance = MagicMock()
    mock_instance.get = AsyncMock(side_effect=list(responses))
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    with patch("src.clients.whoop_client.httpx.AsyncClient", return_value=mock_instance):
        yield mock_instance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth():
    """WhoopAuth stub that always returns a valid token."""
    auth = MagicMock()
    auth.get_valid_token = AsyncMock(return_value="test-token")
    auth.refresh_access_token = AsyncMock()
    return auth


@pytest.fixture
def client(mock_auth):
    """WhoopClient wired to the mock auth (no real DB needed for these tests)."""
    return WhoopClient(db=MagicMock(), auth=mock_auth)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_page_returns_all_records(client):
    """A response with no next_token returns its records directly."""
    page = make_page([{"id": "c1"}, {"id": "c2"}])
    with mock_http(make_response(200, page)):
        result = await client.get_cycles(START, END)
    assert result == [{"id": "c1"}, {"id": "c2"}]


@pytest.mark.asyncio
async def test_multi_page_collects_all_records(client):
    """Records from all pages are combined into a single list."""
    page1 = make_page([{"id": "c1"}, {"id": "c2"}], next_token="tok-abc")
    page2 = make_page([{"id": "c3"}], next_token=None)
    with mock_http(make_response(200, page1), make_response(200, page2)):
        result = await client.get_cycles(START, END)
    assert result == [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]


@pytest.mark.asyncio
async def test_next_token_passed_to_subsequent_request(client):
    """The next_token from page 1 must appear as nextToken on page 2's request."""
    page1 = make_page([{"id": "c1"}], next_token="cursor-xyz")
    page2 = make_page([{"id": "c2"}])
    with mock_http(make_response(200, page1), make_response(200, page2)) as mock_instance:
        await client.get_cycles(START, END)

    second_call_kwargs = mock_instance.get.call_args_list[1].kwargs
    assert second_call_kwargs["params"]["nextToken"] == "cursor-xyz"


@pytest.mark.asyncio
async def test_empty_records_list(client):
    """An empty records array returns an empty list without error."""
    with mock_http(make_response(200, make_page([]))):
        result = await client.get_workouts(START, END)
    assert result == []


# ---------------------------------------------------------------------------
# Rate limit retry (429)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_retries_and_succeeds(client):
    """A single 429 followed by 200 returns data after one backoff."""
    data = {"id": "profile-1", "email": "test@example.com"}
    with mock_http(make_response(429, {}), make_response(200, data)):
        with patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client.get_profile()
    assert result == data
    mock_sleep.assert_awaited_once_with(1.0)   # first backoff: 1 * 2^0 = 1s


@pytest.mark.asyncio
async def test_429_backoff_doubles_each_retry(client):
    """Backoff delay doubles on each successive 429."""
    responses = [make_response(429, {})] * 3 + [make_response(200, {"id": "x"})]
    with mock_http(*responses):
        with patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client.get_profile()
    delays = [call.args[0] for call in mock_sleep.await_args_list]
    assert delays == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_429_raises_after_max_retries(client):
    """Exhausting all 429 retries raises WhoopAPIError."""
    responses = [make_response(429, {})] * 6   # 1 initial + 5 retries
    with mock_http(*responses):
        with patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(WhoopAPIError, match="Rate limited"):
                await client.get_profile()


# ---------------------------------------------------------------------------
# Token refresh on 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_401_triggers_token_refresh_and_retries(client, mock_auth):
    """A 401 triggers refresh_access_token and then retries the request."""
    data = {"id": "profile-1"}
    with mock_http(make_response(401, {}), make_response(200, data)):
        result = await client.get_profile()
    assert result == data
    mock_auth.refresh_access_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_401_after_refresh_raises(client, mock_auth):
    """If a 401 recurs after refresh, WhoopAPIError is raised immediately."""
    with mock_http(make_response(401, {}), make_response(401, {})):
        with pytest.raises(WhoopAPIError, match="401"):
            await client.get_profile()
    mock_auth.refresh_access_token.assert_awaited_once()


# ---------------------------------------------------------------------------
# Server error retry (5xx)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_500_retries_and_succeeds(client):
    """A 500 followed by 200 returns data after backoff."""
    data = {"records": [{"id": "s1"}], "next_token": None}
    with mock_http(make_response(500, {}), make_response(200, data)):
        with patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_sleep(START, END)
    assert result == [{"id": "s1"}]


@pytest.mark.asyncio
async def test_500_raises_after_max_server_retries(client):
    """Exhausting all 5xx retries raises WhoopAPIError."""
    responses = [make_response(500, {})] * 4   # 1 initial + 3 retries
    with mock_http(*responses):
        with patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(WhoopAPIError, match="500"):
                await client.get_sleep(START, END)


# ---------------------------------------------------------------------------
# Non-retryable errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_400_raises_immediately(client):
    """A 400 raises WhoopAPIError without retrying."""
    with mock_http(make_response(400, {})) as mock_instance:
        with pytest.raises(WhoopAPIError, match="400"):
            await client.get_profile()
    assert mock_instance.get.await_count == 1


# ---------------------------------------------------------------------------
# All public methods return correct structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cycles_returns_list(client):
    with mock_http(make_response(200, make_page([{"id": "cy1"}]))):
        result = await client.get_cycles(START, END)
    assert isinstance(result, list)
    assert result[0]["id"] == "cy1"


@pytest.mark.asyncio
async def test_get_recovery_returns_list(client):
    with mock_http(make_response(200, make_page([{"recovery_score": 78.0}]))):
        result = await client.get_recovery(START, END)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_sleep_returns_list(client):
    with mock_http(make_response(200, make_page([{"id": "sl1", "nap": False}]))):
        result = await client.get_sleep(START, END)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_workouts_returns_list(client):
    with mock_http(make_response(200, make_page([{"id": "w1", "sport_name": "Running"}]))):
        result = await client.get_workouts(START, END)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_body_measurements_returns_dict(client):
    body = {"height_meter": 1.78, "weight_kilogram": 75.0, "max_heart_rate": 190}
    with mock_http(make_response(200, body)):
        result = await client.get_body_measurements()
    assert isinstance(result, dict)
    assert result["max_heart_rate"] == 190


@pytest.mark.asyncio
async def test_get_profile_returns_dict(client):
    profile = {"user_id": 12345, "email": "user@example.com", "first_name": "Test"}
    with mock_http(make_response(200, profile)):
        result = await client.get_profile()
    assert isinstance(result, dict)
    assert result["user_id"] == 12345
