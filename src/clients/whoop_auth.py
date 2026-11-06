import asyncio
import json
import logging
import secrets
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from src.database.models import TokenStore

logger = logging.getLogger(__name__)

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

SCOPES = [
    "read:recovery",
    "read:cycles",
    "read:workout",
    "read:sleep",
    "read:body_measurement",
    "read:profile",
    "offline",
]

# Refresh the token this many seconds before it actually expires
TOKEN_EXPIRY_BUFFER_SECONDS = 300


# Serialises token refreshes across the scheduler thread (its own event loop via
# asyncio.run) and the FastAPI loop. Must be a threading.Lock: an asyncio.Lock is
# bound to one loop. Whoop rotates refresh tokens, so two concurrent refreshes
# with the same token would make the second one fail and revoke the grant.
_REFRESH_LOCK = threading.Lock()
_REFRESH_LOCK_TIMEOUT_S = 30


class WhoopAuthError(Exception):
    """Raised when an OAuth operation fails."""


class WhoopReauthRequired(WhoopAuthError):
    """Raised when Whoop rejects the stored grant; the user must reconnect Whoop."""


def _service_key(user_id: str | None) -> str:
    return f"whoop_{user_id}" if user_id else "whoop"


def _auth_error_from_json(raw: str | None) -> str | None:
    """Extract the persisted ``auth_error`` from a ``token_data_json`` value.

    NULL, non-JSON and non-object values mean "no error".
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    err = data.get("auth_error")
    return err if isinstance(err, str) and err else None


def whoop_auth_error(user_id: str | None, db: Session) -> str | None:
    """Return the persisted re-auth message for the user's Whoop token, if any."""
    record = db.get(TokenStore, _service_key(user_id))
    if record is None:
        return None
    return _auth_error_from_json(record.token_data_json)


def set_whoop_auth_error(user_id: str | None, message: str | None, db: Session) -> None:
    """Set (or, with ``None``, clear) ``auth_error`` in the token row's JSON.

    No token row means no-op. The message must never contain token values.
    """
    record = db.get(TokenStore, _service_key(user_id))
    if record is None:
        return
    try:
        data = json.loads(record.token_data_json) if record.token_data_json else {}
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if message is None:
        data.pop("auth_error", None)
    else:
        data["auth_error"] = message
    record.token_data_json = json.dumps(data)
    db.commit()


class WhoopAuth:
    """Handles Whoop OAuth 2.0 authorization code flow and token lifecycle."""

    def get_authorization_url(self) -> tuple[str, str]:
        """Build the Whoop authorization URL and generate a CSRF state token.

        Returns:
            A tuple of (authorization_url, state) where state must be stored
            by the caller and verified when the callback arrives.
        """
        state = secrets.token_urlsafe(32)
        params = {
            "client_id": settings.whoop_client_id,
            "redirect_uri": settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
        }
        url = f"{WHOOP_AUTH_URL}?{urlencode(params)}"
        return url, state

    async def exchange_code(self, code: str, db: Session, user_id: str | None = None) -> TokenStore:
        """Exchange an authorization code for access and refresh tokens.

        Args:
            code: The authorization code received in the OAuth callback.
            db: Active database session for persisting the token.
            user_id: App user UUID to tag the token row. When provided the
                     service key is ``"whoop_{user_id}"``; otherwise ``"whoop"``.

        Returns:
            The saved TokenStore record.

        Raises:
            WhoopAuthError: If the token exchange request fails.
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    WHOOP_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": settings.whoop_redirect_uri,
                        "client_id": settings.whoop_client_id,
                        "client_secret": settings.whoop_client_secret,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500]
                logger.error(
                    "Whoop token exchange HTTP error %s: %s",
                    e.response.status_code,
                    body,
                )
                raise WhoopAuthError(
                    f"Token exchange failed: {e.response.status_code} — {body}"
                ) from e

        return _store_tokens(response.json(), db, user_id=user_id)

    async def refresh_access_token(
        self, db: Session, user_id: str | None = None, *, force: bool = False
    ) -> TokenStore:
        """Use the stored refresh token to obtain a new access token.

        Serialised by a process-wide lock; after acquiring it the token row is
        re-read so a refresh completed by another caller is reused (not repeated).

        Args:
            db: Active database session for reading and updating the token.
            user_id: App user UUID used to look up the token row. When provided
                     the service key is ``"whoop_{user_id}"``; otherwise ``"whoop"``.
            force: POST even if the (re-read) token is unexpired, e.g. after the
                   API answered 401. Still uses the re-read refresh token.

        Returns:
            The updated TokenStore record.

        Raises:
            WhoopReauthRequired: Whoop rejected the refresh (400/401); the state
                is persisted and the token row kept.
            WhoopAuthError: No refresh token, lock timeout, or a transient failure.
        """
        service_key = _service_key(user_id)
        acquired = await asyncio.to_thread(_REFRESH_LOCK.acquire, True, _REFRESH_LOCK_TIMEOUT_S)
        if not acquired:
            raise WhoopAuthError("Timed out waiting for Whoop token refresh")
        try:
            record = db.get(TokenStore, service_key)
            if record is not None:
                # Force a real SELECT: db.get alone returns the identity-map copy.
                db.expire(record)
                record = db.get(TokenStore, service_key)
            if record is None or not record.refresh_token:
                raise WhoopAuthError("No refresh token available. Complete the OAuth flow first.")
            if not force and not is_token_expired(record):
                return record

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        WHOOP_TOKEN_URL,
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": record.refresh_token,
                            "client_id": settings.whoop_client_id,
                            "client_secret": settings.whoop_client_secret,
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status in (400, 401):
                        msg = f"Whoop rejected the token refresh ({status}); reconnect Whoop"
                        logger.warning("Whoop token refresh rejected: %s", status)
                        set_whoop_auth_error(user_id, msg, db)
                        raise WhoopReauthRequired(msg) from e
                    raise WhoopAuthError(f"Token refresh failed: {status}") from e

            return _store_tokens(response.json(), db, user_id=user_id)
        finally:
            _REFRESH_LOCK.release()

    async def get_valid_token(self, db: Session, user_id: str | None = None) -> str:
        """Return a valid access token, automatically refreshing if expired.

        Args:
            db: Active database session.
            user_id: App user UUID used to look up the token row. When provided
                     the service key is ``"whoop_{user_id}"``; otherwise ``"whoop"``.

        Returns:
            A valid access token string.

        Raises:
            WhoopAuthError: If no token exists or refresh fails.
        """
        service_key = f"whoop_{user_id}" if user_id else "whoop"
        record = db.get(TokenStore, service_key)
        if record is None:
            raise WhoopAuthError("Not authenticated. Visit /api/auth/whoop/url to authorize.")

        if is_token_expired(record):
            record = await self.refresh_access_token(db, user_id=user_id)

        return record.access_token

    @classmethod
    def has_token(cls, user_id: str, db: Session) -> bool:
        """Return True if a Whoop token row exists for the given user.

        Args:
            user_id: App user UUID.
            db: Active database session.

        Returns:
            True if a TokenStore row with service key ``"whoop_{user_id}"`` exists.
        """
        service_key = f"whoop_{user_id}"
        record = db.get(TokenStore, service_key)
        return record is not None


def is_token_expired(record: TokenStore) -> bool:
    """Return True if the access token is expired or expiring within the buffer window.

    Args:
        record: TokenStore row to check.

    Returns:
        True if the token should be refreshed, False if it is still valid.
    """
    if not record.expires_at:
        return True

    expires_at = datetime.fromisoformat(record.expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    refresh_at = expires_at - timedelta(seconds=TOKEN_EXPIRY_BUFFER_SECONDS)
    return datetime.now(tz=UTC) >= refresh_at


def _store_tokens(token_data: dict, db: Session, user_id: str | None = None) -> TokenStore:
    """Upsert token data into the token_store table.

    Args:
        token_data: Parsed JSON response from the Whoop token endpoint.
        db: Active database session.
        user_id: App user UUID. When provided the service key is
                 ``"whoop_{user_id}"``; otherwise ``"whoop"``.

    Returns:
        The saved TokenStore record.
    """
    service_key = f"whoop_{user_id}" if user_id else "whoop"
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(seconds=token_data.get("expires_in", 3600))

    record = db.get(TokenStore, service_key)
    if record is None:
        record = TokenStore(service=service_key)
        db.add(record)

    record.access_token = token_data["access_token"]
    # Whoop rotates refresh tokens: persist a returned one, keep the old one otherwise
    if "refresh_token" in token_data:
        record.refresh_token = token_data["refresh_token"]
    record.expires_at = expires_at.isoformat()
    record.token_data_json = json.dumps(token_data)
    record.updated_at = now.isoformat()
    record.user_id = user_id

    db.commit()
    db.refresh(record)
    return record
