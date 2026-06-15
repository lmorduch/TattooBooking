# ABOUTME: Symmetric encryption for sensitive fields stored in the database.
# ABOUTME: Uses Fernet (AES-128-CBC + HMAC) keyed from ENCRYPTION_KEY env var.

import base64
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        # Derive a stable key from JWT_SECRET so dev works without extra config
        jwt_secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
        raw = jwt_secret.encode().ljust(32, b"\0")[:32]
        key = base64.urlsafe_b64encode(raw)
    elif len(key) != 44:
        # If someone passed a raw string, encode it properly
        raw = key.encode().ljust(32, b"\0")[:32]
        key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
