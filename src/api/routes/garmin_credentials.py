"""Garmin credential storage endpoints.

Allows users to store encrypted Garmin Connect credentials for automatic
background sync.  The raw email and password are encrypted with Fernet before
being written to the database and are NEVER returned by any endpoint.

Endpoints
---------
POST   /api/garmin/credentials         — store (requires explicit consent)
DELETE /api/garmin/credentials         — permanently delete + disable auto-sync
GET    /api/garmin/credentials/status  — returns has_credentials + auto_sync_enabled
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.auth.dependencies import get_current_user
from src.auth.encryption import decrypt_credential, encrypt_credential
from src.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/garmin", tags=["garmin-credentials"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StoreCredentialsRequest(BaseModel):
    email: str
    password: str
    consent: bool


class CredentialsStatusResponse(BaseModel):
    has_credentials: bool
    auto_sync_enabled: bool
    last_sync_at: str | None  # ISO 8601 or None


class StoreCredentialsResponse(BaseModel):
    has_credentials: bool
    auto_sync_enabled: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/credentials",
    response_model=StoreCredentialsResponse,
    status_code=status.HTTP_200_OK,
    summary="Store encrypted Garmin credentials for auto-sync",
)
def store_credentials(
    body: StoreCredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StoreCredentialsResponse:
    """Encrypt and store Garmin Connect credentials.

    The email and password are encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
    before being written to the database.  The plaintext is discarded immediately
    after encryption.

    **Consent is required.** The ``consent`` field must be ``true``; passing
    ``false`` returns a 400 error.  The timestamp at which consent was given is
    recorded in ``consent_given_at``.

    The stored credentials are also used to validate that the login works before
    saving — invalid credentials return a 400 error.
    """
    if not body.consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Consent is required to store credentials. "
                "Set consent=true to confirm you agree to encrypted credential storage."
            ),
        )

    if not body.email.strip():
        raise HTTPException(status_code=400, detail="Email cannot be empty.")
    if not body.password:
        raise HTTPException(status_code=400, detail="Password cannot be empty.")

    # Validate encryption key is configured before attempting to store
    try:
        encrypted_email = encrypt_credential(body.email.strip())
        encrypted_password = encrypt_credential(body.password)
    except ValueError as exc:
        logger.error("Credential encryption failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Credential encryption is not configured on this server. "
                "Contact the administrator."
            ),
        ) from exc

    # Validate credentials actually work before storing
    try:
        from src.clients.garmin_auth import GarminAuthError, authenticate_user_garmin

        authenticate_user_garmin(current_user.id, body.email.strip(), body.password, db)
    except Exception as exc:  # noqa: BLE001
        # GarminAuthError or any unexpected error
        err_msg = str(exc)
        if "401" in err_msg or "invalid" in err_msg.lower() or "credentials" in err_msg.lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Garmin credentials are invalid. "
                    "Check your email and password and try again."
                ),
            ) from exc
        if "429" in err_msg or "rate limit" in err_msg.lower():
            raise HTTPException(
                status_code=429,
                detail="Garmin rate limit reached. Wait a few minutes before retrying.",
            ) from exc
        # Unexpected error — still store the credentials (they may work later)
        logger.warning(
            "Garmin credential validation failed for user %s (non-auth error): %s — storing anyway",
            current_user.id,
            exc,
        )

    now = datetime.now(UTC).isoformat()

    existing = db.execute(
        text("SELECT user_id FROM garmin_credentials WHERE user_id = :uid"),
        {"uid": current_user.id},
    ).one_or_none()

    if existing:
        db.execute(
            text(
                """
                UPDATE garmin_credentials
                SET encrypted_email    = :email,
                    encrypted_password = :password,
                    auto_sync_enabled  = 1,
                    updated_at         = :now
                WHERE user_id = :uid
                """
            ),
            {
                "email": encrypted_email,
                "password": encrypted_password,
                "now": now,
                "uid": current_user.id,
            },
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO garmin_credentials
                    (user_id, encrypted_email, encrypted_password,
                     auto_sync_enabled, consent_given_at, created_at, updated_at)
                VALUES (:uid, :email, :password, 1, :consent_at, :now, :now)
                """
            ),
            {
                "uid": current_user.id,
                "email": encrypted_email,
                "password": encrypted_password,
                "consent_at": now,
                "now": now,
            },
        )

    db.commit()
    logger.info("Garmin credentials stored for user %s", current_user.id)

    return StoreCredentialsResponse(has_credentials=True, auto_sync_enabled=True)


@router.delete(
    "/credentials",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete stored Garmin credentials",
)
def delete_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Permanently delete stored Garmin credentials.

    This stops automatic background sync for the authenticated user and
    removes the encrypted credentials from the database.  The Garmin session
    tokens (in ``token_store``) are also removed so the user is fully
    disconnected.
    """
    db.execute(
        text("DELETE FROM garmin_credentials WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    # Also remove session tokens so the user is fully disconnected
    db.execute(
        text("DELETE FROM token_store WHERE service = :key"),
        {"key": f"garmin_{current_user.id}"},
    )
    db.commit()
    logger.info("Garmin credentials deleted for user %s", current_user.id)


@router.get(
    "/credentials/status",
    response_model=CredentialsStatusResponse,
    summary="Check whether Garmin credentials are stored (never returns actual credentials)",
)
def credentials_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CredentialsStatusResponse:
    """Return the credential storage status for the authenticated user.

    This endpoint NEVER returns the actual email or password — only a boolean
    indicating whether credentials exist and whether auto-sync is enabled.
    """
    row = db.execute(
        text(
            "SELECT auto_sync_enabled FROM garmin_credentials WHERE user_id = :uid"
        ),
        {"uid": current_user.id},
    ).one_or_none()

    has_creds = row is not None
    auto_sync = bool(row[0]) if row is not None else False

    # Last sync time from sync_log
    last_sync_row = db.execute(
        text(
            """
            SELECT completed_at FROM sync_log
            WHERE source = 'garmin' AND status = 'success' AND user_id = :uid
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"uid": current_user.id},
    ).one_or_none()

    last_sync_at = str(last_sync_row[0]) if last_sync_row and last_sync_row[0] else None

    return CredentialsStatusResponse(
        has_credentials=has_creds,
        auto_sync_enabled=auto_sync,
        last_sync_at=last_sync_at,
    )
