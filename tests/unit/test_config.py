"""Configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.app.core.config import Settings

_LONG_SECRET = "x" * 48


def _settings(**overrides: object) -> Settings:
    base = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": _LONG_SECRET,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_rejects_sync_database_driver() -> None:
    with pytest.raises(ValidationError, match="async driver"):
        _settings(DATABASE_URL="postgresql://user:pass@localhost/db")


def test_rejects_short_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        _settings(SECRET_KEY="too-short")


def test_production_requires_secret_and_closed_cors() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            CORS_ALLOW_ALL_IN_DEV=False,
        )
    with pytest.raises(ValidationError, match="CORS_ALLOW_ALL_IN_DEV"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY=_LONG_SECRET,
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            CORS_ALLOW_ALL_IN_DEV=True,
        )


def test_chat_model_must_be_allowlisted() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_CHAT_MODELS"):
        _settings(CHAT_MODEL="unknown-model", ALLOWED_CHAT_MODELS="allowed-model")


def test_development_gets_ephemeral_secret() -> None:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        SECRET_KEY="",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    assert len(settings.SECRET_KEY) >= 32


def test_api_key_alias_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "legacy-key")
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY=_LONG_SECRET,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        CHAT_API_KEY="",
    )
    assert settings.chat_api_key == "legacy-key"


def test_deepseek_env_aliases_are_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest exports an empty CHAT_API_KEY for hermetic tests; remove it so the
    # alias chain can fall through to the real DEEPSEEK_* name.
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY=_LONG_SECRET,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    assert settings.CHAT_API_KEY == "sk-test"
    assert settings.CHAT_BASE_URL == "https://api.deepseek.com/v1"
    assert settings.CHAT_MODEL == "deepseek-flash"


def test_zhipu_aliases_are_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.setenv("ZHIPU_KEY", "zhipu-test")
    monkeypatch.setenv("ZHIPU_BASE_URL", "https://gateway.test/v1")
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY=_LONG_SECRET,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    assert settings.ZHIPUAI_API_KEY == "zhipu-test"
    assert settings.EMBEDDING_BASE_URL == "https://gateway.test/v1"


def test_cors_origins_include_documented_frontends() -> None:
    settings = _settings(ENVIRONMENT="development", CORS_ORIGINS="https://a.example")
    assert "https://a.example" in settings.cors_origins
    assert "http://localhost:5173" in settings.cors_origins
