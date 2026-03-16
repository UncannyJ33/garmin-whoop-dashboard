import json
import logging
import secrets
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


class WhoopAuthError(Exception):
    """Raised when an OAuth operation fails."""


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

    async def refresh_access_token(self, db: Session, user_id: str | None = None) -> TokenStore:
        """Use the stored refresh token to obtain a new access token.

        Args:
            db: Active database session for reading and updating the token.
            user_id: App user UUID used to look up the token row. When provided
                     the service key is ``"whoop_{user_id}"``; otherwise ``"whoop"``.

        Returns:
            The updated TokenStore record.

        Raises:
            WhoopAuthError: If no refresh token exists or the request fails.
        """
        service_key = f"whoop_{user_id}" if user_id else "whoop"
        record = db.get(TokenStore, service_key)
        if record is None or not record.refresh_token:
            raise WhoopAuthError("No refresh token available. Complete the OAuth flow first.")

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
                raise WhoopAuthError(f"Token refresh failed: {e.response.status_code}") from e

        return _store_tokens(response.json(), db, user_id=user_id)

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
    # Whoop only returns a new refresh token on initial exchange, not on refresh
    if "refresh_token" in token_data:
        record.refresh_token = token_data["refresh_token"]
    record.expires_at = expires_at.isoformat()
    record.token_data_json = json.dumps(token_data)
    record.updated_at = now.isoformat()
    record.user_id = user_id

    db.commit()
    db.refresh(record)
    return record
