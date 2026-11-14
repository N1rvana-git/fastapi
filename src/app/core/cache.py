"""Two-level cache: process-local TTL cache + optional Redis.

The PDF's checklist asks for a real cache hierarchy instead of ad-hoc
``redis.get`` calls sprinkled through routers.  ``TwoLevelCache`` gives:

1. a local dict with per-entry TTL (microsecond reads for hot, tiny payloads
   such as the tag list);
2. Redis as the shared layer, so all replicas see invalidations;
3. explicit ``invalidate`` on writes (no stale tag list after create/delete).

Semantics are deliberately simple: best-effort, staleness bounded by TTL.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from src.app.core.logging import get_logger

logger = get_logger(__name__)


class LocalTTLCache:
    def __init__(self, max_entries: int = 1024) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: float) -> None:
        async with self._lock:
            if len(self._data) >= self._max_entries:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.monotonic() + max(ttl, 0.001), value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class TwoLevelCache:
    def __init__(
        self, redis_manager: Any | None, *, namespace: str = "cache", ttl: int = 60
    ) -> None:
        self.redis_manager = redis_manager
        self.namespace = namespace
        self.ttl = ttl
        self.local = LocalTTLCache()

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def get(self, key: str) -> Any | None:
        local = self.local.get(self._key(key))
        if local is not None:
            return local
        client = self._client()
        if client is None:
            return None
        try:
            raw = await client.get(self._key(key))
        except Exception as exc:
            logger.debug("redis cache get failed: %s", exc)
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        await self.local.set(self._key(key), value, self.ttl)
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = self.ttl if ttl is None else ttl
        await self.local.set(self._key(key), value, ttl)
        client = self._client()
        if client is None:
            return
        try:
            await client.set(self._key(key), json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception as exc:
            logger.debug("redis cache set failed: %s", exc)

    async def get_or_load(
        self, key: str, loader: Callable[[], Awaitable[Any]], ttl: int | None = None
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await loader()
        if value is not None:
            await self.set(key, value, ttl)
        return value

    async def invalidate(self, key: str) -> None:
        await self.local.delete(self._key(key))
        client = self._client()
        if client is None:
            return
        try:
            await client.delete(self._key(key))
        except Exception as exc:
            logger.debug("redis cache delete failed: %s", exc)

    def _client(self) -> Any | None:
        manager = self.redis_manager
        if manager is None:
            return None
        return getattr(manager, "active_client", None)


__all__ = ["LocalTTLCache", "TwoLevelCache"]
