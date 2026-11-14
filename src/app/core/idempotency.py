"""Idempotency primitives (Redis-backed with an in-memory fallback).

Protocol (per the PDF's "统一领域异常与防重幂等设计"):

1. client sends ``X-Idempotency-Key`` (a UUID it generates once per *action*);
2. the first request takes the key with ``SET NX EX``;
3. a concurrent duplicate gets ``409 IDEMPOTENCY_IN_PROGRESS`` instead of
   charging the user twice or double-decrementing stock;
4. after the action completes the final response is stored and replayed to any
   retry with the same key;
5. reusing a key with a *different* payload is rejected (422) - that is a client
   bug, not a retry.

The store interface is tiny so the in-memory implementation used by tests and by
degraded (Redis-less) deployments is a drop-in replacement.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class IdempotencyOutcome(str, Enum):
    STARTED = "started"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    MISMATCH = "mismatch"


@dataclass
class IdempotencyRecord:
    state: str  # "pending" | "completed"
    status_code: int | None = None
    body: Any | None = None
    fingerprint: str = ""
    created_at: float = field(default_factory=time.time)


class IdempotencyStore(Protocol):
    async def begin(
        self, key: str, *, fingerprint: str, ttl: int, pending_ttl: int
    ) -> tuple[IdempotencyOutcome, IdempotencyRecord | None]: ...

    async def get(self, key: str) -> IdempotencyRecord | None: ...

    async def complete(self, key: str, record: IdempotencyRecord, ttl: int) -> None: ...

    async def release(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """Process-local store: correct for a single worker, used in tests.

    In multi-replica deployments the Redis store must be used, otherwise two
    pods can both accept the same key.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[IdempotencyRecord, float]] = {}
        self._lock = asyncio.Lock()

    async def begin(
        self, key: str, *, fingerprint: str, ttl: int, pending_ttl: int
    ) -> tuple[IdempotencyOutcome, IdempotencyRecord | None]:
        async with self._lock:
            entry = self._data.get(key)
            if entry is not None and entry[1] > time.monotonic():
                record = entry[0]
                if record.fingerprint and fingerprint and record.fingerprint != fingerprint:
                    return IdempotencyOutcome.MISMATCH, record
                if record.state == "pending":
                    return IdempotencyOutcome.IN_PROGRESS, record
                return IdempotencyOutcome.REPLAY, record
            record = IdempotencyRecord(state="pending", fingerprint=fingerprint)
            self._data[key] = (record, time.monotonic() + pending_ttl)
            return IdempotencyOutcome.STARTED, record

    async def complete(self, key: str, record: IdempotencyRecord, ttl: int) -> None:
        async with self._lock:
            self._data[key] = (record, time.monotonic() + ttl)

    async def get(self, key: str) -> IdempotencyRecord | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None or entry[1] <= time.monotonic():
                self._data.pop(key, None)
                return None
            return entry[0]

    async def release(self, key: str) -> None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is not None and entry[0].state == "pending":
                self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


class RedisIdempotencyStore:
    """Distributed store shared by all API replicas."""

    def __init__(self, client: Any, *, namespace: str = "idem") -> None:
        self.client = client
        self.namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def begin(
        self, key: str, *, fingerprint: str, ttl: int, pending_ttl: int
    ) -> tuple[IdempotencyOutcome, IdempotencyRecord | None]:
        raw = json.dumps(
            {"state": "pending", "fingerprint": fingerprint, "created_at": time.time()}
        )
        acquired = await self.client.set(self._key(key), raw, nx=True, ex=pending_ttl)
        if acquired:
            return IdempotencyOutcome.STARTED, IdempotencyRecord(
                state="pending", fingerprint=fingerprint
            )

        stored = await self.client.get(self._key(key))
        if stored is None:
            # Expired between SET NX and GET: treat as a fresh start.
            acquired = await self.client.set(self._key(key), raw, nx=True, ex=pending_ttl)
            if acquired:
                return IdempotencyOutcome.STARTED, IdempotencyRecord(
                    state="pending", fingerprint=fingerprint
                )
            return IdempotencyOutcome.IN_PROGRESS, None

        record = _decode(stored)
        if record.fingerprint and fingerprint and record.fingerprint != fingerprint:
            return IdempotencyOutcome.MISMATCH, record
        if record.state == "pending":
            return IdempotencyOutcome.IN_PROGRESS, record
        return IdempotencyOutcome.REPLAY, record

    async def complete(self, key: str, record: IdempotencyRecord, ttl: int) -> None:
        await self.client.set(
            self._key(key),
            json.dumps(
                {
                    "state": "completed",
                    "status_code": record.status_code,
                    "body": record.body,
                    "fingerprint": record.fingerprint,
                    "created_at": record.created_at,
                },
                ensure_ascii=False,
                default=str,
            ),
            ex=ttl,
        )

    async def get(self, key: str) -> IdempotencyRecord | None:
        stored = await self.client.get(self._key(key))
        if stored is None:
            return None
        try:
            return _decode(stored)
        except Exception:
            return None

    async def release(self, key: str) -> None:
        stored = await self.client.get(self._key(key))
        if stored is None:
            return
        try:
            record = _decode(stored)
        except Exception:
            await self.client.delete(self._key(key))
            return
        if record.state == "pending":
            await self.client.delete(self._key(key))


def _decode(raw: Any) -> IdempotencyRecord:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    return IdempotencyRecord(
        state=str(data.get("state", "pending")),
        status_code=data.get("status_code"),
        body=data.get("body"),
        fingerprint=str(data.get("fingerprint", "")),
        created_at=float(data.get("created_at", 0) or 0),
    )


def build_idempotency_store(redis_manager: Any | None) -> IdempotencyStore:
    client = getattr(redis_manager, "active_client", None) if redis_manager is not None else None
    if client is not None:
        return RedisIdempotencyStore(client)
    return InMemoryIdempotencyStore()


class IdempotencyGuard:
    """Per-request helper returned by the ``idempotency_guard`` dependency."""

    def __init__(
        self,
        *,
        store: IdempotencyStore | None,
        key: str | None,
        fingerprint: str,
        ttl: int,
        pending_ttl: int,
    ) -> None:
        self.store = store
        self.key = key
        self.fingerprint = fingerprint
        self.ttl = ttl
        self.pending_ttl = pending_ttl
        self.outcome: IdempotencyOutcome | None = None
        self.record: IdempotencyRecord | None = None
        self._remembered = False
        self._started = False

    @classmethod
    def disabled(cls) -> IdempotencyGuard:
        return cls(store=None, key=None, fingerprint="", ttl=0, pending_ttl=0)

    @property
    def enabled(self) -> bool:
        return self.store is not None and bool(self.key)

    async def begin(self) -> IdempotencyOutcome:
        if not self.enabled:
            self.outcome = IdempotencyOutcome.STARTED
            return self.outcome
        assert self.store is not None and self.key is not None
        outcome, record = await self.store.begin(
            self.key,
            fingerprint=self.fingerprint,
            ttl=self.ttl,
            pending_ttl=self.pending_ttl,
        )
        self.outcome = outcome
        self.record = record
        self._started = outcome is IdempotencyOutcome.STARTED
        return outcome

    async def remember(self, body: Any, *, status_code: int = 200) -> None:
        if not self.enabled or not self._started:
            return
        assert self.store is not None and self.key is not None
        await self.store.complete(
            self.key,
            IdempotencyRecord(
                state="completed",
                status_code=status_code,
                body=body,
                fingerprint=self.fingerprint,
            ),
            self.ttl,
        )
        self._remembered = True

    async def release(self) -> None:
        """Release a started-but-unfinished key so the client may retry."""

        if not self.enabled or not self._started or self._remembered:
            return
        assert self.store is not None and self.key is not None
        await self.store.release(self.key)


def body_fingerprint(*parts: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()


def stable_key(value: str, *, prefix: str = "") -> str:
    """Hash a client key into a fixed-length, collision-safe storage key.

    Client keys may be up to 128 chars; adding a namespace prefix would overflow
    ``orders.idempotency_key VARCHAR(128)``.  A SHA-256 digest is deterministic,
    so retries still map to the same row, and it never exceeds 64 chars.
    """

    import hashlib

    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    return f"{prefix}{digest}"


def retry_after_seconds(ttl_remaining: float | None, fallback: int) -> int:
    if not ttl_remaining or ttl_remaining <= 0:
        return fallback
    return max(1, min(fallback, math.ceil(ttl_remaining)))


__all__ = [
    "IdempotencyGuard",
    "IdempotencyOutcome",
    "IdempotencyRecord",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "body_fingerprint",
    "build_idempotency_store",
    "retry_after_seconds",
    "stable_key",
]
