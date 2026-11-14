"""Embedding gateway (Zhipu ``embedding-2`` / any OpenAI-compatible endpoint).

The old code called the **sync** ``zhipuai`` SDK inside async routes, blocking
the event loop for the duration of a network round-trip.  Here it is one shared
``httpx.AsyncClient`` + a semaphore + bounded retries + a two-level cache, and
it is the single place that knows how embeddings are produced, so the item tasks
and the RAG tools cannot drift apart.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from src.app.core.cache import TwoLevelCache
from src.app.core.config import Settings
from src.app.core.exceptions import DependencyUnavailableError, FeatureUnavailableError
from src.app.core.http import HttpClientPool
from src.app.core.logging import get_logger
from src.app.core.retry import retry_async

logger = get_logger(__name__)

_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


class EmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        http_pool: HttpClientPool,
        *,
        cache: TwoLevelCache | None = None,
    ) -> None:
        self.settings = settings
        self.http_pool = http_pool
        self.cache = cache

    @property
    def enabled(self) -> bool:
        return bool(self.settings.EMBEDDING_ENABLED and self.settings.ZHIPUAI_API_KEY)

    async def embed(self, text: str, *, use_cache: bool = True) -> list[float]:
        cleaned = text.strip()
        if not cleaned:
            raise FeatureUnavailableError("Cannot embed empty text")
        if not self.enabled:
            raise FeatureUnavailableError(
                "Embedding is disabled or ZHIPUAI_API_KEY is missing",
                details={"embedding_enabled": self.settings.EMBEDDING_ENABLED},
            )

        cache_key = self._cache_key(cleaned)
        if use_cache and self.cache is not None:
            cached = await self.cache.get(cache_key)
            if isinstance(cached, list) and cached:
                return [float(value) for value in cached]

        vector = await self._request(cleaned)
        if len(vector) != self.settings.EMBEDDING_DIMENSION:
            raise DependencyUnavailableError(
                "Embedding provider returned an unexpected dimension",
                details={"expected": self.settings.EMBEDDING_DIMENSION, "actual": len(vector)},
            )
        if self.cache is not None:
            await self.cache.set(cache_key, vector)
        return vector

    async def _request(self, text: str) -> list[float]:
        client = self.http_pool.client(
            "embeddings",
            base_url=self.settings.EMBEDDING_BASE_URL,
            headers={"Authorization": f"Bearer {self.settings.ZHIPUAI_API_KEY}"},
            read_timeout=self.settings.HTTP_READ_TIMEOUT,
        )

        async def call() -> list[float]:
            response = await client.post(
                "/embeddings",
                json={"model": self.settings.ZHIPU_EMBEDDING_MODEL, "input": text},
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise DependencyUnavailableError(
                    "Embedding provider is throttling or failing",
                    details={"status_code": response.status_code},
                )
            if response.status_code >= 400:
                raise DependencyUnavailableError(
                    "Embedding request was rejected",
                    details={"status_code": response.status_code, "body": response.text[:300]},
                )
            payload: dict[str, Any] = response.json()
            try:
                return [float(value) for value in payload["data"][0]["embedding"]]
            except (KeyError, IndexError, TypeError) as exc:
                raise DependencyUnavailableError("Malformed embedding response") from exc

        return await retry_async(
            call,
            attempts=self.settings.LLM_MAX_RETRIES,
            base_delay=self.settings.LLM_RETRY_BASE_DELAY,
            retry_on=_RETRYABLE + (DependencyUnavailableError,),
            on_retry=lambda attempt, exc, delay: logger.warning(
                "embedding retry %s after %s: %s", attempt, round(delay, 2), exc
            ),
        )

    def _cache_key(self, text: str) -> str:
        digest = hashlib.sha256(
            f"{self.settings.ZHIPU_EMBEDDING_MODEL}\x00{text}".encode()
        ).hexdigest()
        return f"emb:{digest}"


__all__ = ["EmbeddingClient"]
