"""Redis pool sizing must survive concurrent SSE load.

The 50-stream load test failed twice before these assertions existed:
* the dedicated blocking pool was hard-coded to 4 connections;
* the shared pool defaulted to 20, so per-request rate-limit scripts exhausted it.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.app.core.config import Settings
from src.app.core.redis import RedisManager


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY="x" * 48,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


def test_redis_pool_defaults_fit_concurrent_streams() -> None:
    settings = _settings()
    assert settings.REDIS_MAX_CONNECTIONS == 100
    assert settings.REDIS_BLOCKING_MAX_CONNECTIONS == 100


def test_blocking_client_uses_its_own_sized_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_from_url(url: str, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("redis.asyncio.Redis.from_url", fake_from_url)
    manager = RedisManager(_settings())
    manager._available = True  # no server needed for this assertion
    manager._client = object()

    client = manager.blocking_client("sse", socket_timeout=None)

    assert client is not None
    assert captured["max_connections"] == manager.settings.REDIS_BLOCKING_MAX_CONNECTIONS
    assert captured["socket_timeout"] is None
