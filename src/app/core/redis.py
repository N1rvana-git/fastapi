"""Redis connection management.

Redis is treated as an *optional* dependency: if it is down the API must still
serve reads/writes, just without distributed locks, shared idempotency and
stream replay.  ``RedisManager`` therefore never raises during startup; callers
check ``available`` (or use the in-memory fallbacks) instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.app.core.config import Settings
from src.app.core.logging import get_logger

logger = get_logger(__name__)


class RedisManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self._available: bool | None = None
        self._closed = False

    @property
    def client(self) -> Any | None:
        return self._client

    @property
    def active_client(self) -> Any | None:
        """The client only when a PING has succeeded; else ``None``.

        Adapters are selected at startup from this property, so a Redis outage
        degrades to the in-memory implementations instead of making every
        request wait for a TCP timeout.
        """

        return self._client if self.available else None

    @property
    def available(self) -> bool:
        return bool(self._available) and self._client is not None

    async def connect(self) -> bool:
        if self._client is not None:
            return self.available
        try:
            from redis.asyncio import Redis

            self._client = Redis.from_url(
                self.settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=self.settings.REDIS_MAX_CONNECTIONS,
                socket_timeout=self.settings.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=self.settings.REDIS_SOCKET_TIMEOUT,
                health_check_interval=30,
                retry_on_timeout=True,
            )
        except Exception as exc:  # pragma: no cover - import/config problems
            logger.warning("redis client could not be created: %s", exc)
            self._available = False
            return False

        self._available = await self.ping()
        if self._available:
            logger.info(
                "redis connected", extra={"ctx_redis_url": _redact(self.settings.REDIS_URL)}
            )
        else:
            logger.warning(
                "redis unavailable; running in degraded mode (in-memory locks, "
                "idempotency and stream replay)"
            )
        return self._available

    async def ping(self, timeout: float | None = None) -> bool:
        if self._client is None:
            return False
        wait = timeout if timeout is not None else self.settings.REDIS_SOCKET_TIMEOUT
        try:
            pong = await asyncio.wait_for(self._client.ping(), timeout=wait)
            self._available = bool(pong)
        except Exception as exc:
            self._available = False
            logger.debug("redis ping failed: %s", exc)
        return self.available

    async def close(self) -> None:
        if self._closed or self._client is None:
            return
        self._closed = True
        try:
            await self._client.aclose()
        except Exception:  # pragma: no cover - best effort on shutdown
            pass
        finally:
            self._client = None
            self._available = False
            logger.info("redis connection closed")


def _redact(url: str) -> str:
    """Hide credentials before logging a connection string."""

    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


__all__ = ["RedisManager"]
