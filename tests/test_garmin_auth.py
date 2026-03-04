"""Tests for the Garmin authentication module."""

from unittest.mock import MagicMock, patch

import pytest
from garth.exc import GarthHTTPError
from requests.exceptions import HTTPError as RequestsHTTPError

from src.clients.garmin_auth import GarminAuth, GarminAuthError, _status_code

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_garth_error(status_code: int) -> GarthHTTPError:
    """Build a GarthHTTPError with the given HTTP status code."""
    response = MagicMock()
    response.status_code = status_code
    http_err = RequestsHTTPError(response=response)
    return GarthHTTPError(msg="Error in request", error=http_err)


def _make_garmin_client() -> MagicMock:
    """Return a mock Garmin client that reports a valid session."""
    client = MagicMock()
    client.get_full_name.return_value = "Test User"
    client.garth = MagicMock()
    return client


# ---------------------------------------------------------------------------
# _status_code helper
# ---------------------------------------------------------------------------


def test_status_code_extracts_correctly():
    exc = _make_garth_error(429)
    assert _status_code(exc) == 429


def test_status_code_returns_none_on_missing_response():
    exc = GarthHTTPError(msg="oops", error=RequestsHTTPError())
    assert _status_code(exc) is None


# ---------------------------------------------------------------------------
# Token loading (existing token directory)
# ---------------------------------------------------------------------------


def test_get_client_loads_tokens_when_directory_exists(tmp_path):
    """get_client should use the token directory when it exists and login succeeds."""
    mock_client = _make_garmin_client()

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client) as MockGarmin,
    ):
        mock_settings.garmin_token_dir = str(tmp_path)
        mock_settings.garmin_email = ""
        mock_settings.garmin_password = ""

        auth = GarminAuth()
        client = auth.get_client()

    MockGarmin.assert_called_once_with()
    mock_client.login.assert_called_once_with(str(tmp_path))
    assert client is mock_client


def test_get_client_returns_cached_client_on_second_call(tmp_path):
    """A second call to get_client should not create a new Garmin instance."""
    mock_client = _make_garmin_client()

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(tmp_path)
        mock_settings.garmin_email = ""
        mock_settings.garmin_password = ""

        auth = GarminAuth()
        first = auth.get_client()
        second = auth.get_client()

    assert first is second
    # get_full_name called once to probe liveness on the second get_client call
    mock_client.get_full_name.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback to password login when tokens are missing / invalid
# ---------------------------------------------------------------------------


def test_get_client_falls_back_to_password_when_no_token_dir(tmp_path):
    """When the token directory doesn't exist, should log in with credentials."""
    nonexistent = tmp_path / "no_tokens_here"
    mock_client = _make_garmin_client()

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client) as MockGarmin,
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "s3cret"

        auth = GarminAuth()
        client = auth.get_client()

        # Password login: Garmin(email=..., password=...)
        MockGarmin.assert_called_once_with(email="user@example.com", password="s3cret")
        mock_client.login.assert_called_once_with()
        assert client is mock_client


def test_get_client_falls_back_to_password_when_token_load_fails(tmp_path):
    """When token loading raises, should fall back to email/password login."""
    mock_client = _make_garmin_client()
    call_count = 0

    def garmin_factory(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: tokenstore load attempt (no kwargs)
            c = MagicMock()
            c.login.side_effect = GarthHTTPError(msg="Error in request", error=RequestsHTTPError())
            return c
        # Second call: password login
        return mock_client

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", side_effect=garmin_factory),
    ):
        mock_settings.garmin_token_dir = str(tmp_path)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "s3cret"

        auth = GarminAuth()
        client = auth.get_client()

    assert client is mock_client


def test_get_client_raises_when_credentials_missing(tmp_path):
    """Should raise GarminAuthError when token dir missing and no credentials set."""
    nonexistent = tmp_path / "no_tokens"

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = ""
        mock_settings.garmin_password = ""

        auth = GarminAuth()
        with pytest.raises(GarminAuthError, match="GARMIN_EMAIL"):
            auth.get_client()


# ---------------------------------------------------------------------------
# Token persistence after password login
# ---------------------------------------------------------------------------


def test_tokens_saved_after_password_login(tmp_path):
    """After a successful password login, tokens should be dumped to disk."""
    nonexistent = tmp_path / "tokens"
    mock_client = _make_garmin_client()

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "pass"

        auth = GarminAuth()
        auth.get_client()

    mock_client.garth.dump.assert_called_once_with(str(nonexistent))


# ---------------------------------------------------------------------------
# Re-auth on 401
# ---------------------------------------------------------------------------


def test_get_client_reauthenticates_on_401(tmp_path):
    """When a cached session probe returns 401, get_client should re-authenticate."""
    mock_fresh_client = _make_garmin_client()

    # Stale client: session probe raises 401, but is injected directly (not via factory)
    mock_stale_client = MagicMock()
    mock_stale_client.get_full_name.side_effect = _make_garth_error(401)

    nonexistent = tmp_path / "no_tokens"

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        # The only Garmin() call happens during re-auth password login — return fresh client
        patch("src.clients.garmin_auth.Garmin", return_value=mock_fresh_client),
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "pass"

        auth = GarminAuth()
        auth._client = mock_stale_client  # inject stale session directly

        # get_client detects 401 from the probe, re-authenticates, returns fresh client
        client = auth.get_client()

    assert client is mock_fresh_client


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected_fragment"),
    [
        (401, "invalid or the session expired"),
        (429, "rate limit"),
        (403, "locked or access is forbidden"),
        (500, "HTTP 500"),
    ],
)
def test_raises_descriptive_error_for_known_status_codes(tmp_path, status_code, expected_fragment):
    """Password login failures should raise GarminAuthError with a helpful message."""
    nonexistent = tmp_path / "no_tokens"
    mock_client = MagicMock()
    mock_client.login.side_effect = _make_garth_error(status_code)

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "u@example.com"
        mock_settings.garmin_password = "p"

        auth = GarminAuth()
        with pytest.raises(GarminAuthError, match=expected_fragment):
            auth.get_client()
