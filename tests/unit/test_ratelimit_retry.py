"""Rate limiter and retry helper."""

from __future__ import annotations

import pytest
from src.app.core.ratelimit import InMemoryRateLimiter
from src.app.core.retry import retry_async


@pytest.mark.asyncio
async def test_rate_limiter_allows_up_to_limit_then_blocks() -> None:
    limiter = InMemoryRateLimiter()
    results = [await limiter.hit("user", limit=2, window_seconds=60) for _ in range(3)]
    assert [result.allowed for result in results] == [True, True, False]
    assert results[-1].retry_after >= 1
    assert results[1].remaining == 0


@pytest.mark.asyncio
async def test_rate_limiter_is_per_key() -> None:
    limiter = InMemoryRateLimiter()
    assert (await limiter.hit("a", limit=1, window_seconds=60)).allowed
    assert (await limiter.hit("b", limit=1, window_seconds=60)).allowed
    assert not (await limiter.hit("a", limit=1, window_seconds=60)).allowed


@pytest.mark.asyncio
async def test_retry_eventually_succeeds() -> None:
    attempts = {"count": 0}

    async def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("boom")
        return "ok"

    result = await retry_async(flaky, attempts=3, base_delay=0.0, max_delay=0.0)
    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_retry_does_not_swallow_unlisted_exceptions() -> None:
    async def fail() -> None:
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        await retry_async(fail, attempts=3, base_delay=0.0, retry_on=(ConnectionError,))


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_last_error() -> None:
    calls = {"count": 0}

    async def always_fail() -> None:
        calls["count"] += 1
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await retry_async(always_fail, attempts=2, base_delay=0.0, max_delay=0.0)
    assert calls["count"] == 2
