"""Tests for the SPA catch-all path resolution (confined to dist)."""

from pathlib import Path

import pytest

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
