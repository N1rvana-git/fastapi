"""Embedding gateway: disabled mode, cache hits, dimension and error mapping."""

from __future__ import annotations

from typing import Any

import pytest
from src.app.core.cache import TwoLevelCache
from src.app.core.config import Settings
from src.app.core.exceptions import DependencyUnavailableError, FeatureUnavailableError
from src.app.shared.embeddings import EmbeddingClient


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "ZHIPUAI_API_KEY": "zhipu-key",
        "ZHIPU_EMBEDDING_MODEL": "embedding-2",
        "EMBEDDING_DIMENSION": 2,
        "EMBEDDING_ENABLED": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeResponse:
    def __init__(self, status: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePool:
    def __init__(self, client: FakeClient) -> None:
        self.client_obj = client

    def client(self, *args: object, **kwargs: object) -> FakeClient:
        return self.client_obj


@pytest.mark.asyncio
async def test_disabled_and_empty_input_are_rejected() -> None:
    disabled = EmbeddingClient(_settings(ZHIPUAI_API_KEY=""), FakePool(FakeClient([])))
    assert disabled.enabled is False
    with pytest.raises(FeatureUnavailableError, match="disabled"):
        await disabled.embed("hello")

    enabled = EmbeddingClient(_settings(), FakePool(FakeClient([])))
    with pytest.raises(FeatureUnavailableError, match="empty"):
        await enabled.embed("   ")


@pytest.mark.asyncio
async def test_cache_hit_skips_the_http_call() -> None:
    cache = TwoLevelCache(None)
    client = FakeClient([])
    embeddings = EmbeddingClient(_settings(), FakePool(client), cache=cache)
    await cache.set(embeddings._cache_key("hello"), [0.1, 0.2])

    vector = await embeddings.embed("hello")
    assert vector == [0.1, 0.2]
    assert client.calls == 0


@pytest.mark.asyncio
async def test_successful_request_caches_the_vector() -> None:
    client = FakeClient([FakeResponse(200, {"data": [{"embedding": [0.3, 0.4]}]})])
    embeddings = EmbeddingClient(_settings(), FakePool(client), cache=TwoLevelCache(None))

    assert await embeddings.embed("hello") == [0.3, 0.4]
    assert client.calls == 1


@pytest.mark.asyncio
async def test_dimension_mismatch_is_rejected() -> None:
    client = FakeClient([FakeResponse(200, {"data": [{"embedding": [0.1, 0.2, 0.3]}]})])
    embeddings = EmbeddingClient(_settings(), FakePool(client))

    with pytest.raises(DependencyUnavailableError, match="dimension"):
        await embeddings.embed("hello")


@pytest.mark.asyncio
async def test_upstream_errors_are_mapped() -> None:
    for response, message in (
        (FakeResponse(429, text="rate limited"), "throttling"),
        (FakeResponse(400, text="bad"), "rejected"),
        (FakeResponse(200, {"unexpected": []}), "Malformed"),
    ):
        client = FakeClient([response])
        embeddings = EmbeddingClient(_settings(LLM_MAX_RETRIES=1), FakePool(client))
        with pytest.raises(DependencyUnavailableError, match=message):
            await embeddings.embed("hello")


@pytest.mark.asyncio
async def test_retry_then_gives_up_with_a_mapped_error() -> None:
    client = FakeClient([FakeResponse(429, text="busy"), FakeResponse(429, text="busy")])
    embeddings = EmbeddingClient(_settings(LLM_MAX_RETRIES=2), FakePool(client))

    with pytest.raises(DependencyUnavailableError, match="throttling"):
        await embeddings.embed("hello")
    assert client.calls == 2
