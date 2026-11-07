"""Tests for the SPA catch-all path resolution (confined to dist)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import _spa_file


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "demo").mkdir()
    (d / "index.html").write_text("root")
    (d / "demo" / "index.html").write_text("demo")
    (d / "assets" / "x.js").write_text("js")
    (tmp_path / "secret.txt").write_text("secret")
    return d


def test_asset_file_served(dist: Path) -> None:
    assert _spa_file(dist, "assets/x.js") == (dist / "assets" / "x.js").resolve()


def test_client_route_gets_index(dist: Path) -> None:
    assert _spa_file(dist, "training") == dist / "index.html"


@pytest.mark.parametrize("p", ["../secret.txt", "..%2Fsecret.txt", "assets/../../secret.txt"])
def test_traversal_never_escapes(dist: Path, p: str) -> None:
    assert _spa_file(dist, p) == dist / "index.html"


def test_symlink_escape_blocked(dist: Path, tmp_path: Path) -> None:
    (dist / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert _spa_file(dist, "link.txt") == dist / "index.html"


def test_subdirectory_index_not_served(dist: Path) -> None:
    assert _spa_file(dist, "demo") == dist / "index.html"


def test_api_paths_none(dist: Path) -> None:
    assert _spa_file(dist, "api/nope") is None
    assert _spa_file(dist, "api") is None


def test_nul_byte_path_gets_index(dist: Path) -> None:
    assert _spa_file(dist, "a\x00b") == dist / "index.html"


@pytest.fixture(scope="module")
def client():
    from src.api.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_root_path_is_publicly_accessible(client: TestClient) -> None:
    """GET / must not require auth or redirect: the SPA serves the landing page."""
    res = client.get("/")
    assert res.status_code not in (401, 302, 307)


def test_login_page_is_publicly_accessible(client: TestClient) -> None:
    res = client.get("/login")
    assert res.status_code not in (401, 302, 307)


def test_waitlist_route_gone(client: TestClient) -> None:
    res = client.post("/api/waitlist", json={"email": "a@example.com"})
    assert res.status_code in (404, 405)


def test_webhook_routes_gone(client: TestClient) -> None:
    res = client.post("/api/webhooks/whoop", json={})
    assert res.status_code in (404, 405)
