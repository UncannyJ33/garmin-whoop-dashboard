import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from src.database.models import TokenStore

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

    async def exchange_code(self, code: str, db: Session) -> TokenStore:
        """Exchange an authorization code for access and refresh tokens.

        Args:
            code: The authorization code received in the OAuth callback.
            db: Active database session for persisting the token.

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
                raise WhoopAuthError(f"Token exchange failed: {e.response.status_code}") from e

        return _store_tokens(response.json(), db)

    async def refresh_access_token(self, db: Session) -> TokenStore:
        """Use the stored refresh token to obtain a new access token.

        Args:
            db: Active database session for reading and updating the token.

        Returns:
            The updated TokenStore record.

        Raises:
            WhoopAuthError: If no refresh token exists or the request fails.
        """
        record = db.get(TokenStore, "whoop")
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

        return _store_tokens(response.json(), db)

    async def get_valid_token(self, db: Session) -> str:
        """Return a valid access token, automatically refreshing if expired.

        Args:
            db: Active database session.

        Returns:
            A valid access token string.

        Raises:
            WhoopAuthError: If no token exists or refresh fails.
        """
        record = db.get(TokenStore, "whoop")
        if record is None:
            raise WhoopAuthError("Not authenticated. Visit /api/auth/whoop to authorize.")

        if is_token_expired(record):
            record = await self.refresh_access_token(db)

        return record.access_token


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


def _store_tokens(token_data: dict, db: Session) -> TokenStore:
    """Upsert token data into the token_store table.

    Args:
        token_data: Parsed JSON response from the Whoop token endpoint.
        db: Active database session.

    Returns:
        The saved TokenStore record.
    """
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(seconds=token_data.get("expires_in", 3600))

    record = db.get(TokenStore, "whoop")
    if record is None:
        record = TokenStore(service="whoop")
        db.add(record)

    record.access_token = token_data["access_token"]
    # Whoop only returns a new refresh token on initial exchange, not on refresh
    if "refresh_token" in token_data:
        record.refresh_token = token_data["refresh_token"]
    record.expires_at = expires_at.isoformat()
    record.token_data_json = json.dumps(token_data)
    record.updated_at = now.isoformat()

    db.commit()
    db.refresh(record)
    return record
