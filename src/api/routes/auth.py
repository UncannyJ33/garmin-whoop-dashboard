"""Authentication routes: JWT register/login/refresh/me + Whoop OAuth."""

import logging
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.schemas import TokenResponse, UserCreate, UserLogin, UserResponse
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


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
def register(body: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Register a new account."""
    existing = db.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": body.email}
    ).one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered.")
    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("New user registered: %s", user.email)
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


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
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at,
    )


# ── Whoop OAuth (unchanged) ───────────────────────────────────────────────────

_pending_states: set[str] = set()
_whoop_auth = WhoopAuth()


@router.get("/whoop", summary="Start Whoop OAuth flow")
async def whoop_authorize() -> RedirectResponse:
    """Redirect the user to Whoop's authorization page."""
    url, state = _whoop_auth.get_authorization_url()
    _pending_states.add(state)
    return RedirectResponse(url)


@router.get("/whoop/callback", summary="Handle Whoop OAuth callback")
async def whoop_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Exchange the authorization code for tokens and persist them."""
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter.")
    _pending_states.discard(state)
    try:
        await _whoop_auth.exchange_code(code, db)
    except WhoopAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return JSONResponse({"status": "authorized", "message": "Whoop connected successfully."})
