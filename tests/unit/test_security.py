"""Password hashing and JWT behaviour."""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.app.core.config import Settings
from src.app.core.exceptions import UnauthorizedError, ValidationError
from src.app.core.security import PasswordHasher, TokenService, verify_shared_secret


@pytest.fixture()
def token_service() -> TokenService:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY="s" * 48,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    return TokenService(settings)


def test_password_hash_roundtrip() -> None:
    hasher = PasswordHasher()
    hashed = hasher.hash("Password123")
    assert hashed != "Password123"
    assert hasher.verify("Password123", hashed)
    assert not hasher.verify("wrong-password", hashed)


def test_password_over_bcrypt_limit_is_rejected() -> None:
    hasher = PasswordHasher()
    if hasher.primary_scheme == "argon2":
        pytest.skip("argon2 has no 72-byte limit")
    with pytest.raises(ValidationError):
        hasher.hash("a" * 73)


def test_malformed_hash_does_not_raise() -> None:
    assert PasswordHasher().verify("Password123", "not-a-hash") is False


def test_token_roundtrip(token_service: TokenService) -> None:
    token = token_service.create_access_token(42, role="admin")
    payload = token_service.decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["iss"] == token_service.settings.JWT_ISSUER


def test_expired_token_is_rejected(token_service: TokenService) -> None:
    token = token_service.create_access_token(1, expires_delta=timedelta(seconds=-5))
    with pytest.raises(UnauthorizedError):
        token_service.decode_token(token)


def test_tampered_token_is_rejected(token_service: TokenService) -> None:
    token = token_service.create_access_token(1)
    with pytest.raises(UnauthorizedError):
        token_service.decode_token(token[:-2] + "aa")


def test_shared_secret_comparison() -> None:
    assert verify_shared_secret("token", "token")
    assert not verify_shared_secret("token", "other")
    assert not verify_shared_secret("", "")
    assert not verify_shared_secret("token", None)
