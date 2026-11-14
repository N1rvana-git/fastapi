"""SSE stream infrastructure: replayable event buffer + per-thread lock.

Why not just write to the HTTP response generator?  Because the PDF's core rule
is: **decouple the HTTP connection lifetime from the agent execution lifetime**.
The worker publishes events into a buffer; the HTTP generator only *reads* it.
That gives us, for free:

* reconnect with ``Last-Event-ID`` (browser-native SSE semantics);
* a slow or reconnecting client cannot stall the graph;
* a second tab with the same thread attaches to the same run instead of
  starting a duplicate one;
* a disconnected client does not cancel the run (``AGENT_DISCONNECT_POLICY``
  decides), so state-changing workflows still finish and persist.

Redis Streams is the production implementation; the in-memory one keeps tests
and Redis-less deployments working with identical semantics.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StreamEntry:
    id: str
    event: str
    data: dict[str, Any]


class StreamBuffer(Protocol):
    async def append(self, thread_id: str, event: str, data: dict[str, Any]) -> str: ...

    async def read(
        self, thread_id: str, after_id: str | None, *, block_ms: int = 1000, count: int = 50
    ) -> list[StreamEntry]: ...

    async def clear(self, thread_id: str) -> None: ...


def _decode(fields: dict[Any, Any]) -> tuple[str, dict[str, Any]]:
    decoded = {
        (key.decode() if isinstance(key, bytes) else str(key)): (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in fields.items()
    }
    try:
        data = json.loads(decoded.get("data", "{}"))
    except json.JSONDecodeError:
        data = {"raw": decoded.get("data", "")}
    return decoded.get("event", "message"), data


class RedisStreamBuffer:
    def __init__(
        self, client: Any, *, ttl: int = 600, maxlen: int = 2000, namespace: str = "chat:stream"
    ) -> None:
        self.client = client
        self.ttl = ttl
        self.maxlen = maxlen
        self.namespace = namespace

    def _key(self, thread_id: str) -> str:
        return f"{self.namespace}:{thread_id}"

    async def append(self, thread_id: str, event: str, data: dict[str, Any]) -> str:
        key = self._key(thread_id)
        message_id = await self.client.xadd(
            key,
            {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)},
            maxlen=self.maxlen,
            approximate=True,
        )
        await self.client.expire(key, self.ttl)
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    async def read(
        self, thread_id: str, after_id: str | None, *, block_ms: int = 1000, count: int = 50
    ) -> list[StreamEntry]:
        key = self._key(thread_id)
        cursor = after_id or "0-0"
        batches = await self.client.xread({key: cursor}, count=count, block=block_ms)
        entries: list[StreamEntry] = []
        if not batches:
            return entries
        for _stream, messages in batches:
            for message_id, fields in messages:
                event, data = _decode(fields)
                entries.append(
                    StreamEntry(
                        id=message_id.decode()
                        if isinstance(message_id, bytes)
                        else str(message_id),
                        event=event,
                        data=data,
                    )
                )
        return entries

    async def clear(self, thread_id: str) -> None:
        await self.client.delete(self._key(thread_id))


class InMemoryStreamBuffer:
    """Ordered, bounded buffer with blocking reads (test/dev implementation)."""

    def __init__(self, *, ttl: int = 600, maxlen: int = 2000) -> None:
        self.ttl = ttl
        self.maxlen = maxlen
        self._entries: dict[str, list[StreamEntry]] = {}
        self._counter = 0
        self._touched: dict[str, float] = {}
        self._condition = asyncio.Condition()

    async def append(self, thread_id: str, event: str, data: dict[str, Any]) -> str:
        async with self._condition:
            self._counter += 1
            entry_id = f"{self._counter}-0"
            bucket = self._entries.setdefault(thread_id, [])
            bucket.append(StreamEntry(id=entry_id, event=event, data=data))
            if len(bucket) > self.maxlen:
                del bucket[: len(bucket) - self.maxlen]
            self._touched[thread_id] = time.monotonic()
            self._condition.notify_all()
            return entry_id

    async def read(
        self, thread_id: str, after_id: str | None, *, block_ms: int = 1000, count: int = 50
    ) -> list[StreamEntry]:
        deadline = time.monotonic() + max(block_ms, 1) / 1000
        async with self._condition:
            while True:
                bucket = self._entries.get(thread_id, [])
                pending = _after(bucket, after_id)
                if pending:
                    return pending[:count]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError:
                    return []

    async def clear(self, thread_id: str) -> None:
        async with self._condition:
            self._entries.pop(thread_id, None)
            self._touched.pop(thread_id, None)
            self._condition.notify_all()

    def purge_expired(self) -> None:
        now = time.monotonic()
        for thread_id, touched in list(self._touched.items()):
            if now - touched > self.ttl:
                self._entries.pop(thread_id, None)
                self._touched.pop(thread_id, None)


def _after(entries: list[StreamEntry], after_id: str | None) -> list[StreamEntry]:
    if not after_id or after_id in {"0", "0-0"}:
        return list(entries)
    try:
        cursor = int(str(after_id).split("-", 1)[0])
    except ValueError:
        return list(entries)
    return [entry for entry in entries if int(entry.id.split("-", 1)[0]) > cursor]


# --------------------------------------------------------------------------- #
# Per-thread mutex
# --------------------------------------------------------------------------- #
_UNLOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""

_RENEW_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("expire", KEYS[1], ARGV[2])
else
  return 0
end
"""


@dataclass
class ThreadLockManager:
    """Serialises runs of the same conversation (per-thread mutex).

    A watchdog renews the TTL while the run is alive, so a long multi-step turn
    cannot lose its lock; if the process dies the TTL expires and the next
    request can proceed.  Only the owner can release (compare-and-delete).
    """

    redis_manager: Any | None
    ttl: int = 30
    _local: dict[str, str] = field(default_factory=dict)
    _local_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def _client(self) -> Any | None:
        return (
            getattr(self.redis_manager, "active_client", None)
            if self.redis_manager is not None
            else None
        )

    @asynccontextmanager
    async def hold(self, thread_id: str, run_id: str) -> AsyncIterator[bool]:
        acquired = await self._acquire(thread_id, run_id)
        if not acquired:
            yield False
            return
        stop = asyncio.Event()
        watchdog = asyncio.create_task(self._renew_loop(thread_id, run_id, stop))
        try:
            yield True
        finally:
            stop.set()
            watchdog.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await watchdog
            await self._release(thread_id, run_id)

    async def _acquire(self, thread_id: str, run_id: str) -> bool:
        client = self._client
        if client is None:
            async with self._local_lock:
                owner = self._local.get(thread_id)
                if owner is not None and owner != run_id:
                    return False
                self._local[thread_id] = run_id
                return True
        try:
            return bool(await client.set(f"chat:lock:{thread_id}", run_id, nx=True, ex=self.ttl))
        except Exception:
            logger.warning("redis lock unavailable, falling back to process-local lock")
            async with self._local_lock:
                self._local[thread_id] = run_id
                return True

    async def _release(self, thread_id: str, run_id: str) -> None:
        client = self._client
        if client is None:
            async with self._local_lock:
                if self._local.get(thread_id) == run_id:
                    self._local.pop(thread_id, None)
            return
        try:
            await client.eval(_UNLOCK_LUA, 1, f"chat:lock:{thread_id}", run_id)
        except Exception:
            logger.debug("lock release failed for thread %s", thread_id)

    async def _renew_loop(self, thread_id: str, run_id: str, stop: asyncio.Event) -> None:
        interval = max(1.0, self.ttl / 3)
        client = self._client
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            if client is None:
                continue
            try:
                renewed = await client.eval(
                    _RENEW_LUA, 1, f"chat:lock:{thread_id}", run_id, self.ttl
                )
                if not renewed:
                    logger.warning("thread lock lost", extra={"ctx_thread_id": thread_id})
                    return
            except Exception:
                logger.debug("lock renewal failed for thread %s", thread_id)


def build_stream_buffer(redis_manager: Any | None, *, ttl: int, maxlen: int) -> StreamBuffer:
    """Prefer a dedicated blocking client.

    ``XREAD ... BLOCK`` deliberately idles; sharing the short-timeout client
    would raise ``redis.TimeoutError`` on every read in production.
    """

    if redis_manager is None:
        return InMemoryStreamBuffer(ttl=ttl, maxlen=maxlen)
    factory = getattr(redis_manager, "blocking_client", None)
    client = factory("sse", socket_timeout=None) if callable(factory) else None
    if client is not None:
        return RedisStreamBuffer(client, ttl=ttl, maxlen=maxlen)
    return InMemoryStreamBuffer(ttl=ttl, maxlen=maxlen)


def sse_frame(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    """Encode one SSE frame. ``id`` enables browser-native reconnect."""

    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, default=str))
    return "\n".join(lines) + "\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx/ingress must not buffer token frames
}


__all__ = [
    "SSE_HEADERS",
    "InMemoryStreamBuffer",
    "RedisStreamBuffer",
    "StreamBuffer",
    "StreamEntry",
    "ThreadLockManager",
    "build_stream_buffer",
    "sse_frame",
]
