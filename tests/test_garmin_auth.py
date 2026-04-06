"""Tests for the Garmin authentication module."""

from unittest.mock import MagicMock, patch

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from src.clients.garmin_auth import GarminAuth, GarminAuthError, _extract_status_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_garmin_client() -> MagicMock:
    """Return a mock Garmin client that reports a valid session."""
    client = MagicMock()
    client.get_full_name.return_value = "Test User"
    client.client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# _extract_status_code helper
# ---------------------------------------------------------------------------


def test_extract_status_code_auth_error():
    exc = GarminConnectAuthenticationError("auth failed")
    assert _extract_status_code(exc) == 401


def test_extract_status_code_rate_limit():
    exc = GarminConnectTooManyRequestsError("too many requests")
    assert _extract_status_code(exc) == 429


def test_extract_status_code_connection_error_with_code():
    exc = GarminConnectConnectionError("server error 403")
    assert _extract_status_code(exc) == 403


def test_extract_status_code_connection_error_no_code():
    exc = GarminConnectConnectionError("network timeout")
    assert _extract_status_code(exc) is None


def test_extract_status_code_generic_exception():
    exc = RuntimeError("something broke")
    assert _extract_status_code(exc) is None


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
            c.login.side_effect = GarminConnectAuthenticationError("tokens expired")
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

    mock_client.client.dump.assert_called_once_with(str(nonexistent))


# ---------------------------------------------------------------------------
# Re-auth on 401
# ---------------------------------------------------------------------------


def test_get_client_reauthenticates_on_401(tmp_path):
    """When a cached session probe returns 401, get_client should re-authenticate."""
    mock_fresh_client = _make_garmin_client()

    # Stale client: session probe raises 401, but is injected directly (not via factory)
    mock_stale_client = MagicMock()
    mock_stale_client.get_full_name.side_effect = GarminConnectAuthenticationError("session expired")

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
    ("exc_class", "expected_fragment"),
    [
        (GarminConnectAuthenticationError, "invalid or the session expired"),
        (GarminConnectTooManyRequestsError, "rate limit"),
    ],
)
def test_raises_descriptive_error_for_specific_exception_types(tmp_path, exc_class, expected_fragment):
    """Password login failures should raise GarminAuthError with a helpful message."""
    nonexistent = tmp_path / "no_tokens"
    mock_client = MagicMock()
    mock_client.login.side_effect = exc_class("error")

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


def test_raises_descriptive_error_for_403(tmp_path):
    """A 403 connection error should mention account lock."""
    nonexistent = tmp_path / "no_tokens"
    mock_client = MagicMock()
    mock_client.login.side_effect = GarminConnectConnectionError("HTTP 403 forbidden")

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "u@example.com"
        mock_settings.garmin_password = "p"

        auth = GarminAuth()
        with pytest.raises(GarminAuthError, match="locked or access is forbidden"):
            auth.get_client()


def test_raises_generic_error_for_connection_failure(tmp_path):
    """A generic connection error should wrap in GarminAuthError."""
    nonexistent = tmp_path / "no_tokens"
    mock_client = MagicMock()
    mock_client.login.side_effect = GarminConnectConnectionError("network timeout")

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(nonexistent)
        mock_settings.garmin_email = "u@example.com"
        mock_settings.garmin_password = "p"

        auth = GarminAuth()
        with pytest.raises(GarminAuthError, match="connection error"):
            auth.get_client()


# ---------------------------------------------------------------------------
# Old garth-format token detection
# ---------------------------------------------------------------------------


def test_old_garth_tokens_are_deleted_on_filesystem(tmp_path):
    """When old garth-format token files exist, they should be deleted and re-auth triggered."""
    # Create old-format garth files
    (tmp_path / "oauth1_token.json").write_text('{"token": "old"}')
    (tmp_path / "oauth2_token.json").write_text('{"token": "old"}')

    mock_client = _make_garmin_client()

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client) as MockGarmin,
    ):
        mock_settings.garmin_token_dir = str(tmp_path)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "pass"

        auth = GarminAuth()
        client = auth.get_client()

    # Should have fallen through to password login
    MockGarmin.assert_called_once_with(email="user@example.com", password="pass")
    assert client is mock_client
    # Old files should be deleted
    assert not (tmp_path / "oauth1_token.json").exists()
    assert not (tmp_path / "oauth2_token.json").exists()


def test_rate_limit_on_token_load_raises_immediately(tmp_path):
    """A 429 during token load should NOT fall back to password — raise immediately."""
    mock_client = MagicMock()
    mock_client.login.side_effect = GarminConnectTooManyRequestsError("429 rate limit")

    with (
        patch("src.clients.garmin_auth.settings") as mock_settings,
        patch("src.clients.garmin_auth.Garmin", return_value=mock_client),
    ):
        mock_settings.garmin_token_dir = str(tmp_path)
        mock_settings.garmin_email = "user@example.com"
        mock_settings.garmin_password = "pass"

        auth = GarminAuth()
        with pytest.raises(GarminAuthError, match="rate limit"):
            auth.get_client()
