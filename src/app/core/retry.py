"""Small async retry helper with exponential backoff and jitter.

``tenacity`` is not installable in this deployment, and the PDF's rule is that
every outbound call must have an explicit timeout *and* a bounded retry policy.
This is the 40-line implementation used by the LLM/embeddings/Feishu clients.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def _is_retryable(exc: BaseException, retry_on: Iterable[type[BaseException]]) -> bool:
    return isinstance(exc, tuple(retry_on))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Run ``operation`` until it succeeds or ``attempts`` is exhausted.

    Only exceptions listed in ``retry_on`` are retried; everything else is
    propagated immediately so programming errors are not masked.
    """

    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc, retry_on) or attempt >= attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 0.5 + random.random()  # full jitter, capped below
            delay = min(delay, max_delay)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            await asyncio.sleep(delay)
    raise last_exc if last_exc else RuntimeError("retry_async exhausted without exception")


__all__ = ["retry_async"]
