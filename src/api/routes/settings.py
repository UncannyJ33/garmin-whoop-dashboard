"""User settings API routes (sleep target)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from src.api.dependencies import get_engine_dep
from src.api.models import SleepSettings
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.database.user_settings import get_sleep_target_minutes, set_sleep_target_minutes

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SleepSettings, summary="Get user settings")
async def get_settings(
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> SleepSettings:
    """Return the current user's settings."""
    try:
        return SleepSettings(sleep_target_minutes=get_sleep_target_minutes(engine, current_user.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc


@router.put("", response_model=SleepSettings, summary="Update user settings")
async def put_settings(
    body: SleepSettings,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> SleepSettings:
    """Set the nightly sleep target (300-720 minutes)."""
    try:
        set_sleep_target_minutes(engine, current_user.id, body.sleep_target_minutes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    return body
