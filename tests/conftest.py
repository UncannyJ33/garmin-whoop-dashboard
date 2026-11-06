"""Shared fixtures."""

import pytest

from config.settings import settings
from src.clients.garmin_personal_auth import reset_default_auth


@pytest.fixture(autouse=True)
def _isolate_garmin_personal_api(monkeypatch):
    """Never let a test reach live Garmin with the real key from .env."""
    monkeypatch.setattr(settings, "garmin_personal_api_key", "")
    monkeypatch.setattr(settings, "garmin_personal_api_base_url", "https://garmin.invalid")
    reset_default_auth()
    yield
    reset_default_auth()
