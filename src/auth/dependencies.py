"""FastAPI dependency for extracting and validating the current user from a JWT."""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import Engine

from src.api.dependencies import get_engine_dep
from src.auth.models import User
from src.auth.security import decode_token
from src.database.owner import get_owner_user_id_cached

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    engine: Engine = Depends(get_engine_dep),
) -> User:
    """Verify the Bearer JWT and return the authenticated User.

    Constructs a User from the JWT payload — the token is cryptographically
    signed so the user_id can be trusted directly.  The only DB read is the
    owner lookup, cached for 60 s (one SELECT per minute, not per request).

    Raises 401 if the token is missing, expired, invalid, or its ``sub`` is not
    the single owner (including when no user, or more than one user, exists).
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

    try:
        owner_id = get_owner_user_id_cached(engine)
    except RuntimeError:
        logger.error("users table has more than one row; rejecting all tokens")
        owner_id = None
    if user_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not the owner account",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Build a detached (session-less) User from the JWT claims.
    return User(id=user_id, is_active=True)
