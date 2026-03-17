"""FastAPI dependency for extracting and validating the current user from a JWT."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from src.auth.models import User
from src.auth.security import decode_token

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> User:
    """Verify the Bearer JWT and return the authenticated User.

    Constructs a User from the JWT payload without a DB lookup — the token is
    cryptographically signed so the user_id can be trusted directly.  This
    removes one DB connection per request, which is important when the Trends
    page fires many parallel requests and the connection pool is small.

    Raises 401 if the token is missing, expired, or invalid.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise invalid

    if payload.get("type") != "access":
        raise invalid

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise invalid

    # Build a detached (session-less) User from the JWT claims.
    # No DB round-trip — the signed JWT is the source of truth.
    return User(id=user_id, is_active=True)
