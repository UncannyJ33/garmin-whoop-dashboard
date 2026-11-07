"""scripts/create_owner.py: one-shot owner bootstrap."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from scripts.create_owner import main
from src.auth.security import verify_password

PW = "correct-horse-battery"


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with patch("scripts.create_owner.get_engine", return_value=eng):
        yield eng


def _count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()


def test_create_owner_creates_user(engine):
    with patch("getpass.getpass", side_effect=[PW, PW]):
        assert main(["--email", "a@b.com"]) == 0
    assert _count(engine) == 1
    with engine.connect() as conn:
        hashed = conn.execute(text("SELECT hashed_password FROM users")).scalar_one()
    assert verify_password(PW, hashed)


def test_create_owner_refuses_second_user(engine, capsys):
    with patch("getpass.getpass", side_effect=[PW, PW]):
        assert main(["--email", "a@b.com"]) == 0
    with patch("getpass.getpass", side_effect=[PW, PW]):
        assert main(["--email", "c@d.com"]) == 2
    assert "an owner already exists" in capsys.readouterr().err
    assert _count(engine) == 1


def test_create_owner_password_mismatch(engine):
    with patch("getpass.getpass", side_effect=[PW, PW + "x"]):
        assert main(["--email", "a@b.com"]) != 0
    assert _count(engine) == 0


def test_create_owner_password_short(engine):
    with patch("getpass.getpass", side_effect=["short", "short"]):
        assert main(["--email", "a@b.com"]) != 0
    assert _count(engine) == 0


def test_create_owner_rejects_invalid_email(engine):
    with patch("getpass.getpass", side_effect=[PW, PW]) as gp:
        assert main(["--email", "owner"]) != 0
    gp.assert_not_called()
    with engine.connect() as conn:
        # migrations never ran, so no users table either
        tables = conn.execute(text("SELECT name FROM sqlite_master WHERE name='users'")).all()
    assert tables == []


def test_create_owner_normalizes_email_then_login_works(engine):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    with patch("getpass.getpass", side_effect=[PW, PW]):
        assert main(["--email", " Owner@Example.COM "]) == 0
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT email FROM users")).scalar_one()
    assert stored == "Owner@example.com"

    def _db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_engine_dep] = lambda: engine
    try:
        res = TestClient(app, raise_server_exceptions=False).post(
            "/api/auth/login", json={"email": stored, "password": PW}
        )
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200
