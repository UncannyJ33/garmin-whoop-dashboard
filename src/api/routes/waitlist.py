"""Waitlist routes: pre-launch email sign-up and admin export."""

import logging
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import Engine, text

from config.settings import settings
from src.api.dependencies import get_engine_dep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per IP) — 5 sign-ups per minute per IP
# ---------------------------------------------------------------------------

_RATE_WINDOW_SECONDS = 60
_RATE_MAX = 5
_attempts: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(ip: str) -> None:
    now = datetime.now(UTC).timestamp()
    q = _attempts[ip]
    while q and now - q[0] > _RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again in a minute.",
        )
    q.append(now)


# ---------------------------------------------------------------------------
# Sign-up
# ---------------------------------------------------------------------------


class WaitlistSignup(BaseModel):
    email: EmailStr


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="Join the PulseEngine waitlist",
)
async def join_waitlist(
    body: WaitlistSignup,
    request: Request,
    engine: Engine = Depends(get_engine_dep),
) -> JSONResponse:
    """Store an email on the waitlist.

    Idempotent: returns success even if the email is already registered so
    callers can't enumerate existing addresses.  Rate-limited to 5/min per IP.
    """
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    now = datetime.now(UTC).isoformat()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO waitlist (email, signed_up_at, notified)"
                    " VALUES (:email, :now, 0)"
                    " ON CONFLICT (email) DO NOTHING"
                ),
                {"email": body.email, "now": now},
            )
    except Exception:
        logger.exception("Waitlist insert failed for %s", body.email)
        # Still return success — don't leak DB errors to the client
    else:
        logger.info("Waitlist signup: %s", body.email)

    return JSONResponse({"success": True, "message": "You're on the list!"})


# ---------------------------------------------------------------------------
# Admin export
# ---------------------------------------------------------------------------


@router.get(
    "/admin",
    summary="Return all waitlist emails (admin only)",
)
async def admin_waitlist(
    request: Request,
    engine: Engine = Depends(get_engine_dep),
) -> JSONResponse:
    """Return all waitlist entries.

    Protected: the caller must provide ``Authorization: Bearer <admin_email>``
    where ``admin_email`` matches the ``ADMIN_EMAIL`` environment variable.
    """
    if not settings.admin_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin not configured.")

    auth = request.headers.get("Authorization", "")
    if (
        not auth.startswith("Bearer ")
        or auth.removeprefix("Bearer ").strip() != settings.admin_email
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT id, email, signed_up_at, notified FROM waitlist ORDER BY signed_up_at")
            )
            .mappings()
            .all()
        )

    return JSONResponse(
        {
            "count": len(rows),
            "entries": [dict(r) for r in rows],
        }
    )
