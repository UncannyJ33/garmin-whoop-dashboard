"""Password hashing and JWT token utilities."""

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from config.settings import settings

ACCESS_TOKEN_EXPIRE_HOURS = 24
REFRESH_TOKEN_EXPIRE_DAYS = 30

_ALGORITHM = settings.jwt_algorithm


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Return True if the plaintext password matches the bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str) -> tuple[str, datetime]:
    """Create a signed JWT access token. Returns (token, expires_at)."""
    expires_at = datetime.now(UTC) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)
    return token, expires_at


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """Create a signed JWT refresh token. Returns (token, expires_at)."""
    expires_at = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> dict:
    """Decode and verify a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "JWTError",
]
