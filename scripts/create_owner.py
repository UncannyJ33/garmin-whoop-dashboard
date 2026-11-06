"""Create the single owner account.

Usage (from project root, venv active):
    python scripts/create_owner.py --email you@example.com
"""

import argparse
import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

from src.auth.models import User
from src.auth.security import hash_password
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.owner import clear_owner_cache, get_owner_user_id

MIN_PASSWORD_LENGTH = 12


def main(argv: list[str] | None = None) -> int:
    """Create the owner user; return the process exit code."""
    parser = argparse.ArgumentParser(description="Create the single owner account.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    # Normalize exactly as /login's UserLogin.email does, or the owner could never log in.
    try:
        email = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"]
        print(f"Error: invalid email address: {reason}", file=sys.stderr)
        return 1

    engine = get_engine()
    try:
        run_migrations(engine=engine)

        try:
            exists = get_owner_user_id(engine) is not None
        except RuntimeError:
            exists = True
        if exists:
            print("Error: an owner already exists.", file=sys.stderr)
            return 2

        password = getpass.getpass("Password: ")
        if getpass.getpass("Confirm password: ") != password:
            print("Error: passwords do not match.", file=sys.stderr)
            return 1
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters.",
                file=sys.stderr,
            )
            return 1

        with get_session_factory(engine)() as db:
            db.add(User(email=email, hashed_password=hash_password(password)))
            db.commit()
        clear_owner_cache()
        print(f"Owner created: {email}")
        return 0
    finally:
        # Tests patch get_engine with a shared in-memory engine; only dispose real ones.
        if not str(engine.url).endswith(":memory:"):
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
