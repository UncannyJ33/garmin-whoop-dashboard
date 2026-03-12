"""FastAPI dependency for extracting and validating the current user from a JWT."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.auth.models import User
from src.auth.security import decode_token

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Verify the Bearer JWT and return the authenticated User.

    Raises 401 if the token is missing, expired, or invalid.
    Raises 403 if the account is inactive.
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

    user = db.get(User, user_id)
    if user is None:
        raise invalid
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")

    return user
