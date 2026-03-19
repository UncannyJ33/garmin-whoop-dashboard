"""Fernet symmetric encryption for at-rest credential storage.

Usage::

    from src.auth.encryption import encrypt_credential, decrypt_credential

    ciphertext = encrypt_credential("my-password")
    plaintext  = decrypt_credential(ciphertext)

Configuration
-------------
Set ``GARMIN_ENCRYPTION_KEY`` in your environment to a Fernet key.
Generate a new key once with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

The key MUST be stored in an environment variable — never hardcoded or
committed to version control.  Rotating the key requires re-encrypting all
stored credentials; a helper ``rotate_key`` is provided for that purpose.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_ENV_VAR = "GARMIN_ENCRYPTION_KEY"


def _get_key() -> bytes:
    """Return the Fernet key bytes from the environment.

    Raises:
        ValueError: If ``GARMIN_ENCRYPTION_KEY`` is not set.
    """
    raw = os.getenv(_ENV_VAR, "")
    if not raw:
        raise ValueError(
            f"{_ENV_VAR} environment variable is not set. "
            "Generate a key with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return raw.encode()


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a plaintext credential string using Fernet (AES-128-CBC + HMAC-SHA256).

    Args:
        plaintext: The credential to encrypt (e.g. email or password).

    Returns:
        URL-safe base64-encoded ciphertext string.

    Raises:
        ValueError: If the encryption key is not configured.
    """
    return Fernet(_get_key()).encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a Fernet ciphertext back to plaintext.

    Args:
        ciphertext: The base64-encoded ciphertext produced by ``encrypt_credential``.

    Returns:
        The original plaintext string.

    Raises:
        ValueError: If the key is not configured or the token is invalid/corrupted.
    """
    try:
        return Fernet(_get_key()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt credential — wrong key or corrupted data."
        ) from exc


def rotate_key(old_key: str, new_key: str, ciphertext: str) -> str:
    """Re-encrypt a ciphertext under a new Fernet key.

    Useful for key rotation: decrypt with the old key, re-encrypt with the new
    key.  The caller is responsible for persisting the new ciphertext.

    Args:
        old_key: The previous Fernet key (base64-encoded string).
        new_key: The replacement Fernet key (base64-encoded string).
        ciphertext: The existing encrypted credential.

    Returns:
        New ciphertext encrypted under ``new_key``.

    Raises:
        ValueError: If either key is invalid or the token cannot be decrypted.
    """
    try:
        plaintext = Fernet(old_key.encode()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Key rotation failed — could not decrypt with old key.") from exc
    return Fernet(new_key.encode()).encrypt(plaintext.encode()).decode()
