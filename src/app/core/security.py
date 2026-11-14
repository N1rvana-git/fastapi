"""Password hashing and JWT issuing/verification.

Notes
-----
* ``python-jose`` is deprecated and was removed from the dependency set; PyJWT
  (already pinned) does the same job with a smaller attack surface.
* Token subject is the **user id**, not the e-mail: changing an e-mail must not
  silently invalidate every session, and ids are opaque.
* Passwords keep bcrypt compatibility (existing hashes verify) while new hashes
  go through Argon2id when ``argon2-cffi`` is installed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from src.app.core.config import Settings
from src.app.core.exceptions import UnauthorizedError, ValidationError
from src.app.core.logging import get_logger

logger = get_logger(__name__)

_BCRYPT_MAX_BYTES = 72


class PasswordHasher:
    """Hash/verify passwords, keeping backwards compatibility with bcrypt."""

    def __init__(self) -> None:
        schemes = ["bcrypt"]
        try:  # argon2 is optional; prefer it when available
            import argon2  # noqa: F401

            schemes = ["argon2", "bcrypt"]
        except Exception:  # pragma: no cover - depends on the deployment
            pass
        self._context = CryptContext(schemes=schemes, deprecated="auto")

    @property
    def primary_scheme(self) -> str:
        return self._context.schemes()[0]

    def hash(self, password: str) -> str:
        if not password:
            raise ValidationError("Password must not be empty")
        self._ensure_bcrypt_limit(password)
        return self._context.hash(password)

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        if not plain_password or not hashed_password:
            return False
        try:
            return bool(self._context.verify(plain_password, hashed_password))
        except Exception:
            logger.warning("password verification failed on malformed hash")
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        try:
            return bool(self._context.needs_update(hashed_password))
        except Exception:
            return True

    @staticmethod
    def _ensure_bcrypt_limit(password: str) -> None:
        if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
            raise ValidationError(
                f"Password must be at most {_BCRYPT_MAX_BYTES} bytes when using bcrypt"
            )


class TokenService:
    """Stateless HS256 access tokens with issuer/audience validation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._key = settings.SECRET_KEY
        self._algorithm = settings.ALGORITHM

    def create_access_token(
        self,
        subject: str | int,
        *,
        role: str = "user",
        expires_delta: timedelta | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = datetime.now(UTC)
        expire = now + (
            expires_delta
            if expires_delta is not None
            else timedelta(minutes=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        payload: dict[str, Any] = {
            "sub": str(subject),
            "role": role,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "iss": self.settings.JWT_ISSUER,
            "aud": self.settings.JWT_AUDIENCE,
            "jti": secrets.token_hex(8),
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, self._key, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                audience=self.settings.JWT_AUDIENCE,
                issuer=self.settings.JWT_ISSUER,
                options={"require": ["exp", "sub", "iat"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthorizedError("Could not validate credentials") from exc
        if not str(payload.get("sub", "")).strip():
            raise UnauthorizedError("Could not validate credentials")
        return payload


def verify_shared_secret(expected: str, provided: str | None) -> bool:
    """Constant-time comparison for webhook/verification tokens."""

    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def fingerprint(value: str) -> str:
    """Stable, non-reversible fingerprint for logging identifiers."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


password_hasher = PasswordHasher()

__all__ = [
    "PasswordHasher",
    "TokenService",
    "fingerprint",
    "password_hasher",
    "verify_shared_secret",
]
