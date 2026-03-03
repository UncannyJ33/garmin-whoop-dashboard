from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.clients.whoop_auth import WhoopAuth, WhoopAuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory CSRF state store. Fine for a single-user personal app.
# A multi-user app would use a short-lived cache (Redis, etc.).
_pending_states: set[str] = set()

_whoop_auth = WhoopAuth()


@router.get("/whoop", summary="Start Whoop OAuth flow")
async def whoop_authorize() -> RedirectResponse:
    """Redirect the user to Whoop's authorization page.

    Generates a random state token for CSRF protection and stores it
    temporarily until the callback arrives.
    """
    url, state = _whoop_auth.get_authorization_url()
    _pending_states.add(state)
    return RedirectResponse(url)


@router.get("/whoop/callback", summary="Handle Whoop OAuth callback")
async def whoop_callback(
    code: str = Query(..., description="Authorization code from Whoop"),
    state: str = Query(..., description="CSRF state token"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Exchange the authorization code for tokens and persist them.

    Whoop redirects here after the user grants consent. Validates the
    state parameter, exchanges the code, and stores the tokens.
    """
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter.")
    _pending_states.discard(state)

    try:
        await _whoop_auth.exchange_code(code, db)
    except WhoopAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return JSONResponse({"status": "authorized", "message": "Whoop connected successfully."})
