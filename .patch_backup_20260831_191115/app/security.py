from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PASSWORD_RESET_MAX_AGE = int(os.getenv("PASSWORD_RESET_MAX_AGE", "3600"))
PBKDF2_ROUNDS = int(os.getenv("PASSWORD_PBKDF2_ROUNDS", "310000"))


def _ab64_encode(data: bytes) -> str:
    """Passlib-compatible adapted base64 ('.' replaces '+', padding omitted)."""
    return base64.b64encode(data).decode("ascii").rstrip("=").replace("+", ".")


def _ab64_decode(value: str) -> bytes:
    value = value.replace(".", "+")
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value)


def hash_password(password: str) -> str:
    """Create a PBKDF2-SHA256 hash in the same modular format used by passlib.

    This keeps compatibility with the original TopBearing hashes without requiring passlib.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"$pbkdf2-sha256${PBKDF2_ROUNDS}${_ab64_encode(salt)}${_ab64_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        if password_hash.startswith("$pbkdf2-sha256$"):
            _, scheme, rounds_text, salt_text, checksum = password_hash.split("$", 4)
            if scheme != "pbkdf2-sha256":
                return False
            rounds = int(rounds_text)
            salt = _ab64_decode(salt_text)
            expected = _ab64_decode(checksum)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=len(expected))
            return hmac.compare_digest(actual, expected)

        # Compatibility fallback for a common explicit stdlib format if an older local build used it.
        if password_hash.startswith("pbkdf2_sha256$"):
            _, rounds_text, salt_text, checksum = password_hash.split("$", 3)
            rounds = int(rounds_text)
            expected = base64.b64decode(checksum)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_text.encode("utf-8"), rounds, dklen=len(expected))
            return hmac.compare_digest(actual, expected)
    except Exception:
        return False
    return False


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET", "dev-change-me-now")
    return URLSafeTimedSerializer(secret_key=secret, salt="topbearing-password-reset-v1")


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:20]


def create_password_reset_token(user_id: int, password_hash: str) -> str:
    payload = {"uid": int(user_id), "fp": _password_fingerprint(password_hash)}
    return _serializer().dumps(payload)


def decode_password_reset_token(token: str, current_password_hash: str | None = None) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(token, max_age=PASSWORD_RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if current_password_hash and data.get("fp") != _password_fingerprint(current_password_hash):
        return None
    return data
