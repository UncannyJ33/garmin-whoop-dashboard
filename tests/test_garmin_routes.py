"""Garmin route registration tests."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_csv_import_route_gone() -> None:
    """The duplicate /api/garmin/csv-import route was removed."""
    r = TestClient(app).post("/api/garmin/csv-import")
    assert r.status_code in (404, 405)
