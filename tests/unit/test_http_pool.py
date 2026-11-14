"""HTTP client pool: reuse, recreation and shutdown."""

from __future__ import annotations

import pytest
from src.app.core.config import Settings
from src.app.core.http import HttpClientPool


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY="x" * 48,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        HTTP_CONNECT_TIMEOUT=2.0,
        HTTP_READ_TIMEOUT=7.0,
        HTTP_WRITE_TIMEOUT=3.0,
        HTTP_POOL_TIMEOUT=1.0,
        HTTP_MAX_CONNECTIONS=12,
        HTTP_MAX_KEEPALIVE_CONNECTIONS=6,
    )


@pytest.mark.asyncio
async def test_client_is_cached_reused_and_recreated_after_close() -> None:
    pool = HttpClientPool(_settings())
    client = pool.client("llm", base_url="https://example.test/v1", read_timeout=9.0)
    assert pool.client("llm", base_url="https://example.test/v1") is client
    assert client.timeout.read == 9.0
    assert client.timeout.connect == 2.0
    assert str(client.base_url).startswith("https://example.test/v1")

    await client.aclose()
    replacement = pool.client("llm", base_url="https://example.test/v1")
    assert replacement is not client

    await pool.close()
    assert pool._clients == {}  # lifecycle cleanup


@pytest.mark.asyncio
async def test_timeout_and_limit_helpers() -> None:
    pool = HttpClientPool(_settings())
    timeout = pool._timeout()
    assert timeout.read == 7.0
    assert timeout.write == 3.0
    assert timeout.pool == 1.0
    limits = pool._limits()
    assert limits.max_connections == 12
    assert limits.max_keepalive_connections == 6
    await pool.close()
