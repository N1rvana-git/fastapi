"""Cache hierarchy: local TTL, Redis layer, stampede-safe get_or_load."""

from __future__ import annotations

import json
from typing import Any

import pytest
from src.app.core.cache import LocalTTLCache, TwoLevelCache


@pytest.mark.asyncio
async def test_local_ttl_cache_expiry_eviction_and_invalidations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = LocalTTLCache(max_entries=2)
    assert cache.get("missing") is None
    await cache.set("a", 1, ttl=10)
    assert cache.get("a") == 1

    now = 100.0
    monkeypatch.setattr("src.app.core.cache.time.monotonic", lambda: now)
    await cache.set("b", 2, ttl=1)
    now = 101.5
    assert cache.get("b") is None

    await cache.set("c", 3, ttl=10)
    await cache.set("d", 4, ttl=10)
    assert len(cache) == 2  # evicted the entry with the earliest deadline
    await cache.delete("c")
    assert cache.get("c") is None
    await cache.clear()
    assert len(cache) == 0


class FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False
        self.deleted: list[str] = []

    async def get(self, key: str) -> Any:
        if self.fail_get:
            raise RuntimeError("redis down")
        return self.store.get(key)

    async def set(self, key: str, value: str, **kwargs: object) -> None:
        if self.fail_set:
            raise RuntimeError("redis down")
        self.store[key] = value

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("redis down")
        self.deleted.append(key)
        self.store.pop(key, None)


class FakeManager:
    def __init__(self, client: Any) -> None:
        self.active_client = client


@pytest.mark.asyncio
async def test_two_level_cache_without_redis() -> None:
    cache = TwoLevelCache(None, namespace="x", ttl=5)
    assert await cache.get("k") is None
    await cache.set("k", {"v": 1})
    assert await cache.get("k") == {"v": 1}

    async def loader() -> dict[str, int]:
        return {"loaded": 1}

    assert await cache.get_or_load("new", loader) == {"loaded": 1}
    assert await cache.get("new") == {"loaded": 1}
    await cache.invalidate("new")
    assert await cache.get("new") is None


@pytest.mark.asyncio
async def test_two_level_cache_reads_redis_and_tolerates_errors() -> None:
    client = FakeClient()
    cache = TwoLevelCache(FakeManager(client), namespace="ns", ttl=30)
    client.store["ns:item"] = json.dumps({"id": 1})

    assert await cache.get("item") == {"id": 1}
    assert cache.local.get("ns:item") == {"id": 1}

    client.store["ns:bad"] = "{not-json"
    assert await cache.get("bad") is None

    client.store["ns:missing"] = None
    assert await cache.get("missing") is None

    client.fail_get = True
    assert await cache.get("other") is None

    await cache.set("written", {"ok": True})
    assert json.loads(client.store["ns:written"]) == {"ok": True}

    client.fail_set = True
    await cache.set("unwritten", {"ok": False})  # local hit still works
    assert await cache.get("unwritten") == {"ok": False}

    client.fail_delete = True
    await cache.invalidate("written")
    assert await cache.get("written") is None

    client.fail_delete = False
    await cache.invalidate("item")
    assert "ns:item" in client.deleted
