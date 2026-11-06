"""Garmin authentication module using the garminconnect library.

Handles token persistence and provides session recovery with automatic
re-authentication on 401 errors.

Two module-level helpers (save_garmin_tokens_to_db / load_garmin_tokens_from_db)
support Railway deployments where the filesystem is ephemeral: tokens are
persisted in the ``token_store`` PostgreSQL table and restored on container boot.

Token format (v0.3.x)
---------------------
garminconnect v0.3.x stores a single ``garmin_tokens.json`` file containing
DI OAuth Bearer tokens (di_token, di_refresh_token, di_client_id).  This
replaces the older garth multi-file format (oauth1_token.json + oauth2_token.json).
Old-format tokens are detected on load and trigger a fresh re-authentication.
"""

import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config.settings import settings

logger = logging.getLogger(__name__)

# Keys that indicate the old garth token format (pre-v0.3.0).
# If any stored token dict contains these keys, it must be discarded.
_OLD_GARTH_TOKEN_KEYS = {"oauth1_token.json", "oauth2_token.json"}


def _is_old_garth_format(token_files: dict[str, str]) -> bool:
    """Return True if *token_files* uses the old garth multi-file format."""
    return bool(token_files.keys() & _OLD_GARTH_TOKEN_KEYS)


# ---------------------------------------------------------------------------
# DB token persistence helpers (for Railway / ephemeral filesystems)
# ---------------------------------------------------------------------------


def save_garmin_tokens_to_db(engine: Engine, token_dir: Path | None = None) -> None:
    """Persist garminconnect token files from the filesystem into the ``token_store`` table.

    Reads every file in *token_dir* and stores its content as a JSON dict
    under ``service='garmin'``.  No-op if the directory is absent or empty.

    Args:
        engine: SQLAlchemy engine connected to the application database.
        token_dir: Directory containing garminconnect token files.  Defaults to
            ``settings.garmin_token_dir``.
    """
    if token_dir is None:
        token_dir = Path(settings.garmin_token_dir)

    if not token_dir.exists():
        logger.debug("Garmin: token dir %s not found — skipping DB save", token_dir)
        return

    files = {f.name: f.read_text() for f in token_dir.iterdir() if f.is_file()}
    if not files:
        logger.debug("Garmin: token dir %s is empty — skipping DB save", token_dir)
        return

    from src.database.connection import get_session_factory
    from src.database.models import TokenStore

    SessionFactory = get_session_factory(engine)
    with SessionFactory() as session:
        record = session.get(TokenStore, "garmin")
        if record is None:
            record = TokenStore(service="garmin")
            session.add(record)
        record.token_data_json = json.dumps(files)
        record.updated_at = datetime.now(UTC).isoformat()
        session.commit()
    logger.info("Garmin: %d token file(s) saved to DB", len(files))


def load_garmin_tokens_from_db(engine: Engine, token_dir: Path | None = None) -> bool:
    """Restore garminconnect token files from the ``token_store`` table to the filesystem.

    Writes the previously-persisted token files back to *token_dir* so
    garminconnect can load them without a full email/password login.

    If the stored tokens use the old garth format (pre-v0.3.0), they are
    silently discarded and the DB record is deleted so a fresh login occurs.

    Args:
        engine: SQLAlchemy engine connected to the application database.
        token_dir: Directory to restore token files into.  Defaults to
            ``settings.garmin_token_dir``.

    Returns:
        ``True`` if tokens were successfully restored, ``False`` if no tokens
        were found in the database or tokens were in the old format.
    """
    if token_dir is None:
        token_dir = Path(settings.garmin_token_dir)

    from src.database.connection import get_session_factory
    from src.database.models import TokenStore

    SessionFactory = get_session_factory(engine)
    with SessionFactory() as session:
        record = session.get(TokenStore, "garmin")
        if record is None or not record.token_data_json:
            logger.debug("Garmin: no tokens found in DB")
            return False
        token_files: dict[str, str] = json.loads(record.token_data_json)

        # Detect and discard old garth-format tokens
        if _is_old_garth_format(token_files):
            logger.warning(
                "Garmin: found old garth-format tokens in DB — discarding. "
                "A fresh login is required after the garminconnect v0.3.x upgrade."
            )
            session.delete(record)
            session.commit()
            return False

    token_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in token_files.items():
        (token_dir / filename).write_text(content)
    logger.info("Garmin: restored %d token file(s) from DB to %s", len(token_files), token_dir)
    return True


# ---------------------------------------------------------------------------
# Per-user token helpers
# ---------------------------------------------------------------------------


def has_garmin_token(user_id: str, db: Session) -> bool:
    """Return True if a per-user Garmin token exists in token_store.

    Args:
        user_id: App user UUID.
        db: Active SQLAlchemy session.
    """
    from src.database.models import TokenStore

    return db.get(TokenStore, f"garmin_{user_id}") is not None


def authenticate_user_garmin(user_id: str, email: str, password: str, db: Session) -> None:
    """Authenticate with Garmin for a specific user and persist tokens in DB.

    Performs a full email/password login, dumps the resulting token file
    to a temporary directory, then stores it in ``token_store`` under
    the key ``garmin_{user_id}``.  The raw password is never stored.

    Args:
        user_id: App user UUID to tag the stored tokens.
        email: Garmin Connect email address.
        password: Garmin Connect password.
        db: Active SQLAlchemy session.

    Raises:
        GarminAuthError: If authentication fails or tokens cannot be saved.
    """
    from src.database.models import TokenStore

    with tempfile.TemporaryDirectory() as tmpdir:
        token_dir = Path(tmpdir)
        try:
            client = Garmin(email=email, password=password)
            client.login()
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthError(
                "Garmin rate limit reached (429). Wait a few minutes before retrying."
            ) from exc
        except GarminConnectAuthenticationError as exc:
            raise GarminAuthError(
                f"Garmin credentials are invalid or the session expired (401). {exc}"
            ) from exc
        except GarminConnectConnectionError as exc:
            raise GarminAuthError(f"Garmin connection error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            err_msg = str(exc)
            exc_type = type(exc).__name__
            if "429" in err_msg or "rate limit" in err_msg.lower() or "TooManyRequests" in exc_type:
                raise GarminAuthError(
                    "Garmin rate limit reached (429). Wait a few minutes before retrying."
                ) from exc
            if (
                "401" in err_msg
                or "authentication" in err_msg.lower()
                or "Authentication" in exc_type
            ):
                raise GarminAuthError(
                    f"Garmin credentials are invalid or the session expired (401). {exc}"
                ) from exc
            raise GarminAuthError(f"Garmin login failed: {exc}") from exc

        try:
            client.client.dump(str(token_dir))
        except Exception as exc:  # noqa: BLE001
            raise GarminAuthError(f"Could not save Garmin tokens: {exc}") from exc

        files = {f.name: f.read_text() for f in token_dir.iterdir() if f.is_file()}
        if not files:
            raise GarminAuthError("Garmin login succeeded but produced no token files.")

        service_key = f"garmin_{user_id}"
        record = db.get(TokenStore, service_key)
        if record is None:
            record = TokenStore(service=service_key)
            db.add(record)
        record.token_data_json = json.dumps(files)
        record.user_id = user_id
        record.updated_at = datetime.now(UTC).isoformat()
        db.commit()

    logger.info("Garmin: authenticated and stored tokens for user %s", user_id)


class GarminAuthError(Exception):
    """Raised when Garmin authentication fails."""


def _extract_status_code(exc: Exception) -> int | None:
    """Try to extract an HTTP status code from a garminconnect exception.

    garminconnect v0.3.x exceptions are plain Exception subclasses without
    a standard ``response`` attribute.  We infer the code from the exception
    type and fall back to parsing the string representation.

    Args:
        exc: The exception to inspect.

    Returns:
        The integer HTTP status code, or None if it cannot be determined.
    """
    if isinstance(exc, GarminConnectAuthenticationError):
        return 401
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return 429
    if isinstance(exc, GarminConnectConnectionError):
        # Connection errors may wrap various HTTP codes; try to parse from message
        msg = str(exc)
        for code in (400, 403, 404, 500, 502, 503):
            if str(code) in msg:
                return code
        return None
    return None


class GarminAuth:
    """Manages Garmin authentication with token persistence and session recovery.

    On first use, authenticates with email and password, and garminconnect
    saves the resulting OAuth tokens to the configured token directory.
    On subsequent starts, tokens are loaded from disk — no password
    round-trip required.  If loading fails, the class falls back to a
    full login.

    Usage::

        auth = GarminAuth()
        client = auth.get_client()
        activities = client.get_activities(0, 10)
    """

    def __init__(self, token_dir: Path | None = None) -> None:
        self._client: Garmin | None = None
        self._token_dir: Path = (
            token_dir if token_dir is not None else Path(settings.garmin_token_dir)
        )
        # Keeps a TemporaryDirectory alive when this instance owns one (per-user flow)
        self._temp_dir_obj: tempfile.TemporaryDirectory | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_client(self) -> Garmin:
        """Return a ready-to-use, authenticated Garmin client.

        Loads an existing session from the token directory when available,
        falling back to a full email/password login when tokens are missing
        or invalid.

        Returns:
            An authenticated Garmin instance.

        Raises:
            GarminAuthError: If authentication cannot be completed.
        """
        if self._client is not None:
            self._client = self._ensure_valid(self._client)
            return self._client

        self._client = self._build_client()
        return self._client

    @classmethod
    def for_user(cls, user_id: str, db: Session) -> "GarminAuth":
        """Create a GarminAuth pre-loaded with per-user tokens from token_store.

        Writes the stored token files to a managed TemporaryDirectory so
        garminconnect can load them without a password round-trip.  The temp
        directory is kept alive for the lifetime of the returned instance.

        If the stored tokens are in the old garth format (pre-v0.3.0), they
        are discarded from the DB and a GarminAuthError is raised so the user
        is prompted to reconnect.

        Args:
            user_id: App user UUID whose tokens to load.
            db: Active SQLAlchemy session.

        Returns:
            Configured GarminAuth instance ready for use.

        Raises:
            GarminAuthError: If no tokens are found for the user or tokens
                are in an incompatible format.
        """
        from src.database.models import TokenStore

        service_key = f"garmin_{user_id}"
        record = db.get(TokenStore, service_key)
        if record is None or not record.token_data_json:
            raise GarminAuthError(
                f"No Garmin tokens found for user {user_id}. Connect Garmin first."
            )

        token_files: dict[str, str] = json.loads(record.token_data_json)

        # Detect old garth-format tokens and discard them
        if _is_old_garth_format(token_files):
            logger.warning(
                "Garmin: old garth-format tokens found for user %s — discarding. "
                "User must reconnect Garmin after the v0.3.x upgrade.",
                user_id,
            )
            db.delete(record)
            db.commit()
            raise GarminAuthError(
                f"Garmin tokens for user {user_id} are in an outdated format. "
                "Please reconnect Garmin in Settings."
            )

        temp = tempfile.TemporaryDirectory()
        token_dir = Path(temp.name)
        for filename, content in token_files.items():
            (token_dir / filename).write_text(content)

        auth = cls(token_dir=token_dir)
        auth._temp_dir_obj = temp  # keep TemporaryDirectory alive
        return auth

    def save_for_user(self, user_id: str, db: Session) -> None:
        """Persist current token files back to token_store for this user.

        Should be called after a successful sync so any refreshed session
        tokens are stored and available on the next run.

        Args:
            user_id: App user UUID.
            db: Active SQLAlchemy session.
        """
        if not self._token_dir.exists():
            return
        files = {f.name: f.read_text() for f in self._token_dir.iterdir() if f.is_file()}
        if not files:
            return

        from src.database.models import TokenStore

        service_key = f"garmin_{user_id}"
        record = db.get(TokenStore, service_key)
        if record is None:
            record = TokenStore(service=service_key)
            db.add(record)
        record.token_data_json = json.dumps(files)
        record.user_id = user_id
        record.updated_at = datetime.now(UTC).isoformat()
        db.commit()
        logger.debug("Garmin: refreshed tokens saved for user %s", user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> Garmin:
        """Create and authenticate a Garmin client.

        Tries token-based login first, then falls back to password login.

        Returns:
            An authenticated Garmin instance.

        Raises:
            GarminAuthError: If both strategies fail.
        """
        token_dir = str(self._token_dir) if self._token_dir.exists() else None

        if token_dir:
            # Check for old garth-format tokens on the filesystem
            existing_files = {f.name for f in self._token_dir.iterdir() if f.is_file()}
            if existing_files & _OLD_GARTH_TOKEN_KEYS:
                logger.warning(
                    "Garmin: old garth-format tokens found in %s — deleting and re-authenticating",
                    token_dir,
                )
                for f in self._token_dir.iterdir():
                    f.unlink()
            else:
                client = self._login_with_tokens(token_dir)
                if client is not None:
                    logger.info("Garmin: loaded session from token directory %s", token_dir)
                    return client
                logger.warning(
                    "Garmin: token directory exists but load failed — falling back to password login"
                )

        return self._login_with_password()

    def _login_with_tokens(self, token_dir: str) -> Garmin | None:
        """Attempt to restore a session from a garminconnect token directory.

        Args:
            token_dir: Path to the directory containing garminconnect token files.

        Returns:
            An authenticated Garmin client, or None if loading failed.
        """
        try:
            client = Garmin()
            client.login(token_dir)
            return client
        except GarminConnectTooManyRequestsError as exc:
            # Rate limit — do NOT fall back to password login, that will also be rate-limited.
            raise GarminAuthError(
                "Garmin rate limit reached (429). Wait a few minutes before retrying."
            ) from exc
        except GarminConnectAuthenticationError:
            logger.warning(
                "Garmin: cached tokens rejected (authentication error) — will re-authenticate"
            )
            return None
        except GarminConnectConnectionError as exc:
            logger.warning("Garmin: connection error loading tokens: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower() or "too many" in err_msg.lower():
                raise GarminAuthError(
                    "Garmin rate limit reached (429). Wait a few minutes before retrying."
                ) from exc
            logger.warning("Garmin: could not load tokens (%s) — will re-authenticate", exc)
            return None

    def _login_with_password(self) -> Garmin:
        """Authenticate with email and password and persist the resulting tokens.

        Returns:
            An authenticated Garmin client.

        Raises:
            GarminAuthError: If credentials are missing or login fails.
        """
        email = settings.garmin_email
        password = settings.garmin_password

        if not email or not password:
            raise GarminAuthError(
                "GARMIN_EMAIL and GARMIN_PASSWORD must be set in your .env file "
                "for the initial Garmin login."
            )

        try:
            client = Garmin(email=email, password=password)
            client.login()
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthError(
                "Garmin rate limit reached (429). Wait a few minutes before retrying."
            ) from exc
        except GarminConnectAuthenticationError as exc:
            raise GarminAuthError(
                "Garmin credentials are invalid or the session expired (401). "
                "Check GARMIN_EMAIL and GARMIN_PASSWORD in your .env file."
            ) from exc
        except GarminConnectConnectionError as exc:
            err_msg = str(exc)
            if "403" in err_msg:
                raise GarminAuthError(
                    "Garmin account is locked or access is forbidden (403). "
                    "Log in at connect.garmin.com to unlock your account, then retry."
                ) from exc
            raise GarminAuthError(f"Garmin connection error: {exc}") from exc

        # Persist tokens for future sessions
        self._token_dir.mkdir(parents=True, exist_ok=True)
        try:
            client.client.dump(str(self._token_dir))
            logger.info("Garmin: tokens saved to %s", self._token_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Garmin: could not save tokens: %s", exc)

        return client

    def _ensure_valid(self, client: Garmin) -> Garmin:
        """Verify the client session is still alive and re-authenticate if not.

        Makes a lightweight API call (full name fetch) to probe liveness.
        On a 401, re-authenticates from scratch.

        Args:
            client: The currently cached Garmin client.

        Returns:
            A valid Garmin client (may be a new instance after re-auth).

        Raises:
            GarminAuthError: If re-authentication also fails.
        """
        try:
            client.get_full_name()
            return client
        except GarminConnectAuthenticationError:
            logger.info("Garmin: session expired — re-authenticating")
            self._client = None
            return self._build_client()
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthError(
                "Garmin rate limit reached (429). Wait a few minutes before retrying."
            ) from exc
        except GarminConnectConnectionError as exc:
            err_msg = str(exc)
            if "403" in err_msg:
                raise GarminAuthError(
                    "Garmin account is locked or access is forbidden (403). "
                    "Log in at connect.garmin.com to unlock your account, then retry."
                ) from exc
            raise GarminAuthError(f"Garmin connection error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                raise GarminAuthError(
                    "Garmin rate limit reached (429). Wait a few minutes before retrying."
                ) from exc
            raise GarminAuthError(f"Garmin session validation error: {exc}") from exc
