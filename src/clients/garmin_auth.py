"""Garmin authentication module using the garminconnect library.

Handles token persistence via garth's token directory and provides
session recovery with automatic re-authentication on 401 errors.

Two module-level helpers (save_garmin_tokens_to_db / load_garmin_tokens_from_db)
support Railway deployments where the filesystem is ephemeral: tokens are
persisted in the ``token_store`` PostgreSQL table and restored on container boot.
"""

import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from garminconnect import Garmin
from garth.exc import GarthHTTPError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB token persistence helpers (for Railway / ephemeral filesystems)
# ---------------------------------------------------------------------------


def save_garmin_tokens_to_db(engine: Engine, token_dir: Path | None = None) -> None:
    """Persist garth token files from the filesystem into the ``token_store`` table.

    Reads every file in *token_dir* and stores its content as a JSON dict
    under ``service='garmin'``.  No-op if the directory is absent or empty.

    Args:
        engine: SQLAlchemy engine connected to the application database.
        token_dir: Directory containing garth token files.  Defaults to
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
    """Restore garth token files from the ``token_store`` table to the filesystem.

    Writes the previously-persisted token files back to *token_dir* so garth
    can load them without a full email/password login.

    Args:
        engine: SQLAlchemy engine connected to the application database.
        token_dir: Directory to restore token files into.  Defaults to
            ``settings.garmin_token_dir``.

    Returns:
        ``True`` if tokens were successfully restored, ``False`` if no tokens
        were found in the database.
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

    Performs a full email/password login, dumps the resulting garth token
    files to a temporary directory, then stores them in ``token_store`` under
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
        except GarthHTTPError as exc:
            _raise_for_status(exc)

        try:
            client.garth.dump(str(token_dir))
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


def _status_code(exc: GarthHTTPError) -> int | None:
    """Extract the HTTP status code from a GarthHTTPError.

    GarthHTTPError wraps a requests.exceptions.HTTPError whose .response
    attribute is a requests.Response with a .status_code integer.

    Args:
        exc: The GarthHTTPError to inspect.

    Returns:
        The integer HTTP status code, or None if it cannot be determined.
    """
    try:
        return exc.error.response.status_code
    except AttributeError:
        return None


def _raise_for_status(exc: GarthHTTPError) -> None:
    """Raise a descriptive GarminAuthError for known HTTP error codes.

    Args:
        exc: The GarthHTTPError that was caught.

    Raises:
        GarminAuthError: Always — with a message appropriate to the status code.
    """
    code = _status_code(exc)
    if code == 401:
        raise GarminAuthError(
            "Garmin credentials are invalid or the session expired (401). "
            "Check GARMIN_EMAIL and GARMIN_PASSWORD in your .env file."
        ) from exc
    if code == 429:
        raise GarminAuthError(
            "Garmin rate limit reached (429). Wait a few minutes before retrying."
        ) from exc
    if code == 403:
        raise GarminAuthError(
            "Garmin account is locked or access is forbidden (403). "
            "Log in at connect.garmin.com to unlock your account, then retry."
        ) from exc
    raise GarminAuthError(f"Garmin request failed (HTTP {code}): {exc}") from exc


class GarminAuth:
    """Manages Garmin authentication with token persistence and session recovery.

    On first use, authenticates with email and password, and garth saves the
    resulting OAuth tokens to the configured token directory.  On subsequent
    starts, tokens are loaded from disk — no password round-trip required.
    If loading fails for any reason, the class falls back to a full login.

    Usage::

        auth = GarminAuth()
        client = auth.get_client()
        activities = client.get_activities(0, 10)
    """

    def __init__(self, token_dir: Path | None = None) -> None:
        self._client: Garmin | None = None
        self._token_dir: Path = token_dir if token_dir is not None else Path(settings.garmin_token_dir)
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

        Writes the stored token files to a managed TemporaryDirectory so garth
        can load them without a password round-trip.  The temp directory is
        kept alive for the lifetime of the returned instance.

        Args:
            user_id: App user UUID whose tokens to load.
            db: Active SQLAlchemy session.

        Returns:
            Configured GarminAuth instance ready for use.

        Raises:
            GarminAuthError: If no tokens are found for the user.
        """
        from src.database.models import TokenStore

        service_key = f"garmin_{user_id}"
        record = db.get(TokenStore, service_key)
        if record is None or not record.token_data_json:
            raise GarminAuthError(f"No Garmin tokens found for user {user_id}. Connect Garmin first.")

        token_files: dict[str, str] = json.loads(record.token_data_json)
        temp = tempfile.TemporaryDirectory()
        token_dir = Path(temp.name)
        for filename, content in token_files.items():
            (token_dir / filename).write_text(content)

        auth = cls(token_dir=token_dir)
        auth._temp_dir_obj = temp  # keep TemporaryDirectory alive
        return auth

    def save_for_user(self, user_id: str, db: Session) -> None:
        """Persist current garth token files back to token_store for this user.

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
            client = self._login_with_tokens(token_dir)
            if client is not None:
                logger.info("Garmin: loaded session from token directory %s", token_dir)
                return client
            logger.warning(
                "Garmin: token directory exists but load failed — falling back to password login"
            )

        return self._login_with_password()

    def _login_with_tokens(self, token_dir: str) -> Garmin | None:
        """Attempt to restore a session from a garth token directory.

        Args:
            token_dir: Path to the directory containing garth token files.

        Returns:
            An authenticated Garmin client, or None if loading failed.
        """
        try:
            client = Garmin()
            client.login(token_dir)
            return client
        except GarthHTTPError as exc:
            code = _status_code(exc)
            if code in (401, 403):
                logger.warning(
                    "Garmin: cached tokens rejected (HTTP %s) — will re-authenticate", code
                )
                return None
            # Unexpected HTTP error — let caller decide
            logger.warning("Garmin: unexpected HTTP error loading tokens: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
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
        except GarthHTTPError as exc:
            _raise_for_status(exc)

        # Persist tokens for future sessions
        self._token_dir.mkdir(parents=True, exist_ok=True)
        try:
            client.garth.dump(str(self._token_dir))
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
        except GarthHTTPError as exc:
            code = _status_code(exc)
            if code == 401:
                logger.info("Garmin: session expired — re-authenticating")
                self._client = None
                return self._build_client()
            _raise_for_status(exc)
