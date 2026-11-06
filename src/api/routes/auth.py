"""Authentication routes: JWT login/refresh/me + Whoop OAuth."""

import asyncio
import logging
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.schemas import TokenResponse, UserLogin, UserResponse
from src.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.clients.whoop_auth import WhoopAuth, WhoopAuthError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Rate limiting (in-memory, per IP) ────────────────────────────────────────
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_ATTEMPTS = 5
_login_attempts: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(ip: str) -> None:
    """Allow max 5 login attempts per IP per 60 s. Raises 429 on breach."""
    now = datetime.now(UTC).timestamp()
    attempts = _login_attempts[ip]
    # Evict entries older than the window
    while attempts and now - attempts[0] > _RATE_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _RATE_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a minute.",
        )
    attempts.append(now)


# ── JWT endpoints ─────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse, summary="Login and receive JWT tokens")
def login(body: UserLogin, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate with email + password. Returns access + refresh tokens."""
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    user = (
        db.execute(text("SELECT * FROM users WHERE email = :email"), {"email": body.email})
        .mappings()
        .one_or_none()
    )

    if user is None or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")

    access_token, access_expires = create_access_token(user["id"])
    refresh_token, _ = create_refresh_token(user["id"])
    logger.info("User logged in: %s", user["email"])
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expires.isoformat(),
    )


@router.post(
    "/refresh", response_model=TokenResponse, summary="Exchange refresh token for new access token"
)
def refresh_token(request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Pass a refresh token in the Authorization: Bearer header to get a new access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token."
        )

    token = auth_header.removeprefix("Bearer ").strip()
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token."
    )
    try:
        payload = decode_token(token)
    except JWTError:
        raise invalid

    if payload.get("type") != "refresh":
        raise invalid

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise invalid

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid

    access_token, access_expires = create_access_token(user.id)
    new_refresh, _ = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_at=access_expires.isoformat(),
    )


@router.get("/me", response_model=UserResponse, summary="Current user info")
def me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserResponse:
    """Return the authenticated user's profile.

    ``get_current_user`` builds a detached User from the JWT (no email), so the
    profile is read from the ``users`` row.
    """
    row = (
        db.execute(
            text("SELECT id, email, created_at FROM users WHERE id = :id"),
            {"id": current_user.id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse(id=row["id"], email=row["email"], created_at=str(row["created_at"]))


# ── Whoop OAuth ───────────────────────────────────────────────────────────────

_whoop_auth = WhoopAuth()

# State TTL: OAuth states older than this are considered expired
_OAUTH_STATE_TTL_MINUTES = 30


def _store_oauth_state(state: str, user_id: str, db: Session) -> None:
    """Persist a Whoop OAuth CSRF state → user_id mapping in token_store.

    Uses the DB so the mapping survives restarts.
    Entries are keyed as ``whoop_state_{state}`` and cleaned up on use.
    """
    from src.database.models import TokenStore

    record = db.get(TokenStore, f"whoop_state_{state}")
    if record is None:
        record = TokenStore(service=f"whoop_state_{state}")
        db.add(record)
    record.token_data_json = user_id
    record.user_id = user_id
    record.updated_at = datetime.now(UTC).isoformat()
    db.commit()


def _pop_oauth_state(state: str, db: Session) -> str | None:
    """Retrieve and delete the user_id for a Whoop OAuth state.

    Returns the user_id if the state is valid and not expired, else None.
    """
    from src.database.models import TokenStore

    record = db.get(TokenStore, f"whoop_state_{state}")
    if record is None:
        return None

    # Reject states older than TTL
    try:
        updated = datetime.fromisoformat(record.updated_at)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        age_minutes = (datetime.now(UTC) - updated).total_seconds() / 60
        if age_minutes > _OAUTH_STATE_TTL_MINUTES:
            db.delete(record)
            db.commit()
            return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "OAuth state has an unparseable updated_at; skipping TTL check", exc_info=True
        )

    user_id = record.token_data_json
    db.delete(record)
    db.commit()
    return user_id


@router.get("/whoop/url", summary="Get Whoop OAuth authorization URL")
async def whoop_authorize_url(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return the Whoop authorization URL for the authenticated user.

    The frontend navigates to this URL to start the OAuth flow.
    State is persisted to the DB so it survives server restarts.
    """
    url, state = _whoop_auth.get_authorization_url()
    _store_oauth_state(state, current_user.id, db)
    return JSONResponse({"url": url})


@router.get("/whoop/status", summary="Check whether the current user has connected Whoop")
async def whoop_connection_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return whether the current user has a valid Whoop token stored."""
    connected = WhoopAuth.has_token(current_user.id, db)
    return JSONResponse({"connected": connected})


_GARMIN_PROBE_TTL_SECONDS = 600
# (monotonic timestamp, connected, error) of the last key-validity probe.
_garmin_probe_cache: tuple[float, bool, str | None] | None = None


def _probe_garmin_key() -> tuple[bool, str | None]:
    """Call the cheap user-settings endpoint to check the key; body is discarded."""
    from src.clients.garmin_client import GarminClient
    from src.clients.garmin_personal_auth import GarminPersonalApiError

    try:
        GarminClient().get_user_settings()
    except GarminPersonalApiError as exc:
        return False, str(exc)
    except Exception as exc:
        # Never echo the message (may contain a URL); log the type only.
        logger.warning("Garmin status probe failed unexpectedly: %s", type(exc).__name__)
        return False, type(exc).__name__
    return True, None


@router.get("/garmin/status", summary="Check whether the Garmin Personal API key works")
async def garmin_connection_status(
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return ``{"connected", "configured", "error"}`` for the Garmin Personal API key.

    ``connected`` requires no recorded token-exchange failure and a successful
    probe; the probe result is cached for 10 minutes, but a recorded
    ``last_error`` (e.g. from the scheduler) bypasses the cache.
    """
    global _garmin_probe_cache
    import time

    from config.settings import settings
    from src.clients.garmin_personal_auth import get_default_auth

    if not settings.garmin_personal_api_key:
        return JSONResponse({"connected": False, "configured": False, "error": None})

    last_error = get_default_auth().last_error
    if last_error is not None:
        return JSONResponse({"connected": False, "configured": True, "error": last_error})

    cached = _garmin_probe_cache
    if cached is not None and time.monotonic() - cached[0] < _GARMIN_PROBE_TTL_SECONDS:
        connected, error = cached[1], cached[2]
    else:
        connected, error = await asyncio.to_thread(_probe_garmin_key)
        _garmin_probe_cache = (time.monotonic(), connected, error)
    return JSONResponse({"connected": connected, "configured": True, "error": error})


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the current user's password",
)
def change_password(
    body: ChangePasswordBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Change the authenticated user's password.

    Requires the correct current password.  The new password must be at least
    8 characters.  ``get_current_user`` builds User from JWT without a DB
    lookup, so we fetch ``hashed_password`` explicitly here.
    """
    row = db.execute(
        text("SELECT hashed_password FROM users WHERE id = :uid"),
        {"uid": current_user.id},
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not verify_password(body.current_password, row[0]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters.",
        )
    db.execute(
        text("UPDATE users SET hashed_password = :hp WHERE id = :uid"),
        {"hp": hash_password(body.new_password), "uid": current_user.id},
    )
    db.commit()
    logger.info("Password changed for user %s", current_user.id)


@router.delete(
    "/whoop/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect the current user's Whoop account",
)
async def whoop_disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove the stored Whoop OAuth token for the current user.

    The user will be prompted to reconnect Whoop on their next visit.
    No API call is made to Whoop — only the local token is deleted.
    """
    from src.database.models import TokenStore

    record = db.get(TokenStore, f"whoop_{current_user.id}")
    if record:
        db.delete(record)
        db.commit()
    logger.info("Whoop disconnected for user %s", current_user.id)


@router.get("/whoop/callback", summary="Handle Whoop OAuth callback")
async def whoop_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Exchange the authorization code for tokens and redirect back to Settings.

    Always returns a redirect — never a bare error response — so the browser
    always lands back on the SPA rather than showing a blank/JSON error page.
    """
    try:
        user_id = _pop_oauth_state(state, db)
        if user_id is None:
            logger.warning(
                "Whoop callback: unknown or expired state — possible CSRF or server restart"
            )
            return RedirectResponse(url="/settings?whoop_error=expired", status_code=302)
        await _whoop_auth.exchange_code(code, db, user_id=user_id)
        logger.info("Whoop OAuth complete for user %s", user_id)
        return RedirectResponse(url="/settings?whoop_connected=1", status_code=302)
    except WhoopAuthError as e:
        logger.error("Whoop OAuth exchange failed (WhoopAuthError): %s", e)
        return RedirectResponse(url="/settings?whoop_error=auth_failed", status_code=302)
    except Exception:
        logger.exception("Whoop OAuth callback: unexpected error — redirecting to error page")
        return RedirectResponse(url="/settings?whoop_error=auth_failed", status_code=302)
