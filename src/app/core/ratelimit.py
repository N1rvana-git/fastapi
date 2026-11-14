"""Fixed-window rate limiting with an atomic Redis counter.

Used by the Feishu webhook (which previously did ``INCR`` + ``EXPIRE`` in two
round-trips, so a crash between them leaked a key without TTL) and by the public
write endpoints.  The Lua script makes increment+expire atomic; the in-memory
implementation covers tests and Redis-less deployments.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

_INCR_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_after: int


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        async with self._lock:
            now = time.monotonic()
            count, reset_at = self._data.get(key, (0, now + window_seconds))
            if reset_at <= now:
                count, reset_at = 0, now + window_seconds
            count += 1
            self._data[key] = (count, reset_at)
            reset_after = max(0, round(reset_at - now))
            allowed = count <= limit
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=max(0, limit - count),
                retry_after=0 if allowed else max(1, reset_after),
                reset_after=reset_after,
            )

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


class RedisRateLimiter:
    def __init__(self, client: Any, *, namespace: str = "ratelimit") -> None:
        self.client = client
        self.namespace = namespace

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        full_key = f"{self.namespace}:{key}"
        count, ttl = await self.client.eval(_INCR_LUA, 1, full_key, window_seconds)
        count = int(count)
        ttl = int(ttl) if ttl is not None and int(ttl) >= 0 else window_seconds
        allowed = count <= limit
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=0 if allowed else max(1, ttl),
            reset_after=ttl,
        )


def build_rate_limiter(redis_manager: Any | None) -> RateLimiter:
    client = getattr(redis_manager, "active_client", None) if redis_manager is not None else None
    if client is not None:
        return RedisRateLimiter(client)
    return InMemoryRateLimiter()


__all__ = [
    "InMemoryRateLimiter",
    "RateLimitResult",
    "RateLimiter",
    "RedisRateLimiter",
    "build_rate_limiter",
]
