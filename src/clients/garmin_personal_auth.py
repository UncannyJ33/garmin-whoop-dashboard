"""Garmin Personal API auth: exchange a long-lived API key for a 24 h bearer JWT.

The token is cached in memory only. The key and token are never logged or put in
exception messages.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from jose import JWTError, jwt

from config.settings import settings

logger = logging.getLogger(__name__)

TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
KEY_PAGE_URL = "https://connect.garmin.com/app/settings/personalApiToken"

_REFRESH_MARGIN = timedelta(seconds=3600)


class GarminPersonalApiError(Exception):
    """Base class for Garmin Personal API errors."""


class GarminKeyError(GarminPersonalApiError):
    """The API key is missing, rejected or expired."""


class GarminRateLimitError(GarminPersonalApiError):
    """Garmin answered 429."""


class GarminTransientError(GarminPersonalApiError):
    """5xx or network failure; not a key problem."""


@dataclass(frozen=True)
class BearerToken:
    """A bearer JWT and its expiry."""

    access_token: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def decode_jwt_exp(token: str) -> datetime:
    """Return the ``exp`` claim as an aware UTC datetime (no signature check)."""
    try:
        claims = jwt.get_unverified_claims(token)
        exp = claims["exp"]
        return datetime.fromtimestamp(float(exp), UTC)
    except (JWTError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise GarminKeyError(
            f"Garmin returned an unreadable token; regenerate your key at {KEY_PAGE_URL}"
        ) from exc


class GarminPersonalAuth:
    """Exchanges the Personal API key for a bearer token and caches it."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self._api_key = settings.garmin_personal_api_key if api_key is None else api_key
        self._base_url = (
            settings.garmin_personal_api_base_url if base_url is None else base_url
        ).rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._token: BearerToken | None = None
        self.last_error: str | None = None

    @property
    def http(self) -> httpx.Client:
        """The shared (thread-safe) HTTP client."""
        return self._http

    @property
    def base_url(self) -> str:
        """The Personal API base URL, without a trailing slash."""
        return self._base_url

    def close(self) -> None:
        """Close the HTTP client if this instance created it."""
        if self._owns_http:
            self._http.close()

    @property
    def token_expires_at(self) -> datetime | None:
        """Expiry of the cached token, or None if none is cached."""
        token = self._token
        return token.expires_at if token else None

    def _fresh(self) -> bool:
        token = self._token
        return token is not None and token.expires_at - _now() >= _REFRESH_MARGIN

    def get_token(self, force_refresh: bool = False) -> str:
        """Return a valid bearer JWT, re-exchanging when under 1 h remains."""
        if not force_refresh and self._fresh():
            return self._token.access_token  # type: ignore[union-attr]
        seen = self._token
        with self._lock:
            if self._fresh() and (not force_refresh or self._token is not seen):
                # Fresh, or another thread already refreshed while we waited.
                return self._token.access_token  # type: ignore[union-attr]
            self._token = self._exchange()
            return self._token.access_token

    def _key_error(self, message: str) -> GarminKeyError:
        self.last_error = message
        return GarminKeyError(message)

    def _exchange(self) -> BearerToken:
        if not self._api_key:
            raise self._key_error(
                f"GARMIN_PERSONAL_API_KEY is not set; create a key at {KEY_PAGE_URL}"
            )
        try:
            resp = self._http.post(
                f"{self._base_url}{TOKEN_PATH}",
                headers={"Authorization": f"ApiKey {self._api_key}"},
            )
        except httpx.TransportError as exc:
            raise GarminTransientError(
                f"Garmin token exchange failed: {type(exc).__name__}"
            ) from None
        status = resp.status_code
        if status in (400, 401, 403):
            raise self._key_error(
                f"Garmin rejected the Personal API key (HTTP {status}); "
                f"check or regenerate it at {KEY_PAGE_URL}"
            )
        if status == 429:
            raise GarminRateLimitError("Garmin token exchange rate limited (HTTP 429)")
        if status >= 500:
            raise GarminTransientError(f"Garmin token exchange failed (HTTP {status})")
        if status != 200:
            raise GarminTransientError(f"Unexpected Garmin token response (HTTP {status})")
        access_token = resp.text.strip()
        try:
            expires_at = decode_jwt_exp(access_token)
        except GarminKeyError as exc:
            self.last_error = str(exc)
            raise
        self.last_error = None
        logger.info("Garmin Personal API token obtained; expires_at=%s", expires_at.isoformat())
        return BearerToken(access_token=access_token, expires_at=expires_at)


_default_auth: GarminPersonalAuth | None = None
_default_lock = threading.Lock()


def get_default_auth() -> GarminPersonalAuth:
    """Return the lazily created process-wide auth instance."""
    global _default_auth
    with _default_lock:
        if _default_auth is None:
            _default_auth = GarminPersonalAuth()
        return _default_auth


def reset_default_auth() -> None:
    """Discard the process-wide instance (for tests)."""
    global _default_auth
    with _default_lock:
        old, _default_auth = _default_auth, None
    if old is not None:
        old.close()
