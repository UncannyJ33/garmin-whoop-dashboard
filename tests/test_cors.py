"""CORS is off unless CORS_ORIGINS is configured."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.main import app, install_cors


def test_no_cors_header_by_default() -> None:
    """The app sends no CORS headers when CORS_ORIGINS is unset."""
    resp = TestClient(app).get("/api/health", headers={"Origin": "http://x.test"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_cors_when_configured() -> None:
    """install_cors adds the middleware for a non-empty origin list."""
    test_app = FastAPI()
    install_cors(test_app, ["http://x.test"])

    @test_app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    resp = TestClient(test_app).get("/ping", headers={"Origin": "http://x.test"})
    assert resp.headers["access-control-allow-origin"] == "http://x.test"
