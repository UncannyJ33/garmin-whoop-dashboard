"""pg_connect_args: default sslmode=require unless the URL sets its own."""

from src.database.connection import pg_connect_args


def test_defaults_to_require() -> None:
    assert pg_connect_args("postgresql://u:p@host:5432/db") == {"sslmode": "require"}


def test_url_sslmode_is_respected() -> None:
    assert pg_connect_args("postgresql://u:p@localhost:5432/db?sslmode=disable") == {}
    assert pg_connect_args("postgresql://u:p@h/db?application_name=x&sslmode=verify-full") == {}
