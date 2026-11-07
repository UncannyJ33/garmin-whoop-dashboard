"""Shared fixtures."""

import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-not-real")  # before settings import

from config.settings import settings  # noqa: E402
from src.clients.garmin_personal_auth import reset_default_auth  # noqa: E402
from src.database.owner import clear_owner_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_owner_cache():
    """Each test module builds its own engine and user ids; never leak the cached owner."""
    clear_owner_cache()
    yield
    clear_owner_cache()


@pytest.fixture(autouse=True)
def _isolate_garmin_personal_api(monkeypatch):
    """Never let a test reach live Garmin with the real key from .env."""
    monkeypatch.setattr(settings, "garmin_personal_api_key", "")
    monkeypatch.setattr(settings, "garmin_personal_api_base_url", "https://garmin.invalid")
    reset_default_auth()
    yield
    reset_default_auth()
