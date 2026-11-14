"""Async task queue.

Replaces Celery for this codebase.  Celery's worker model is sync-first, which
means an async FastAPI app has to bridge with ``asyncio.run`` per task and cannot
reuse the SQLAlchemy/httpx pools - the PDF calls this out as "严重割裂感".

This implementation is intentionally small:

* tasks are plain ``async def`` functions registered with ``@task(...)``;
* enqueue writes one entry to a Redis Stream (``XADD``);
* a worker process consumes with a consumer group (``XREADGROUP``), acks on
  success and re-enqueues with exponential backoff on failure, then dead-letters
  after ``max_attempts``;
* when Redis is unavailable (or ``TASKS_EAGER=true``, e.g. in tests) tasks run
  in-process, tracked so shutdown can drain them.

The same function can therefore be a request-scoped background task today and a
horizontally scaled worker tomorrow, without rewriting business code.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.app.core.config import Settings
from src.app.core.context import context_snapshot, restored_context
from src.app.core.logging import get_logger, log_extra

logger = get_logger(__name__)

TaskFunc = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    func: TaskFunc
    max_attempts: int = 3
    backoff_seconds: float = 2.0


_registry: dict[str, TaskSpec] = {}


def task(
    name: str | None = None,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> Callable[[TaskFunc], TaskFunc]:
    """Register an async function as a dispatchable task."""

    def decorator(func: TaskFunc) -> TaskFunc:
        task_name = name or f"{func.__module__}.{func.__name__}"
        if task_name in _registry:
            raise RuntimeError(f"duplicate task name: {task_name}")
        _registry[task_name] = TaskSpec(
            name=task_name,
            func=func,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )
        return func

    return decorator


def get_registry() -> Mapping[str, TaskSpec]:
    return dict(_registry)


def clear_registry() -> None:
    """Test helper."""

    _registry.clear()


class TaskDispatcher(Protocol):
    async def enqueue(self, name: str, **kwargs: Any) -> str | None: ...

    async def drain(self, timeout: float = 10.0) -> None: ...

    async def aclose(self) -> None: ...


class InProcessDispatcher:
    """Runs tasks as local asyncio tasks (tests, dev, Redis-down fallback)."""

    def __init__(
        self, settings: Settings, *, registry: Mapping[str, TaskSpec] | None = None
    ) -> None:
        self.settings = settings
        self.registry = dict(registry or _registry)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    async def enqueue(self, name: str, **kwargs: Any) -> str | None:
        spec = self.registry.get(name)
        if spec is None:
            logger.error("unknown task", extra=log_extra(event="task_unknown", task=name))
            return None
        if self._closed:
            logger.warning("dispatcher closed, dropping task", extra=log_extra(task=name))
            return None
        job_id = uuid.uuid4().hex
        snapshot = context_snapshot()

        async def runner() -> None:
            with restored_context(snapshot):
                try:
                    await spec.func(**kwargs)
                    logger.info(
                        "task completed",
                        extra=log_extra(event="task_completed", task=name, job_id=job_id),
                    )
                except Exception:
                    logger.exception(
                        "task failed",
                        extra=log_extra(event="task_failed", task=name, job_id=job_id),
                    )

        local_task = asyncio.create_task(runner(), name=f"task:{name}:{job_id}")
        self._tasks.add(local_task)
        local_task.add_done_callback(self._tasks.discard)
        return job_id

    async def drain(self, timeout: float = 10.0) -> None:
        if not self._tasks:
            return
        pending = list(self._tasks)
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
        for item in still_pending:
            item.cancel()
        for item in done:
            try:
                item.result()
            except Exception:
                pass

    async def aclose(self) -> None:
        self._closed = True
        await self.drain(timeout=5.0)


class RedisStreamDispatcher:
    def __init__(
        self,
        settings: Settings,
        redis_manager: Any,
        *,
        fallback: InProcessDispatcher | None = None,
    ) -> None:
        self.settings = settings
        self.redis_manager = redis_manager
        self.fallback = fallback

    @property
    def _client(self) -> Any | None:
        return getattr(self.redis_manager, "client", None)

    async def enqueue(self, name: str, **kwargs: Any) -> str | None:
        client = self._client
        if client is None:
            if self.fallback is not None:
                return await self.fallback.enqueue(name, **kwargs)
            logger.error("no redis and no fallback dispatcher", extra=log_extra(task=name))
            return None
        payload = {
            "name": name,
            "kwargs": json.dumps(kwargs, ensure_ascii=False, default=str),
            "attempt": "0",
            "trace_id": context_snapshot().get("trace_id", ""),
            "request_id": context_snapshot().get("request_id", ""),
            "enqueued_at": str(time.time()),
        }
        try:
            message_id = await client.xadd(self.settings.TASKS_STREAM, payload, maxlen=100_000)
            logger.info("task enqueued", extra=log_extra(event="task_enqueued", task=name))
            return str(message_id)
        except Exception:
            logger.exception(
                "task enqueue failed", extra=log_extra(event="task_enqueue_failed", task=name)
            )
            if self.fallback is not None:
                return await self.fallback.enqueue(name, **kwargs)
            return None

    async def drain(self, timeout: float = 10.0) -> None:
        if self.fallback is not None:
            await self.fallback.drain(timeout)

    async def aclose(self) -> None:
        if self.fallback is not None:
            await self.fallback.aclose()


def build_dispatcher(
    settings: Settings,
    redis_manager: Any | None,
    *,
    registry: Mapping[str, TaskSpec] | None = None,
) -> TaskDispatcher:
    eager = InProcessDispatcher(settings, registry=registry)
    if settings.tasks_eager or not settings.TASKS_ENABLED:
        return eager
    client = getattr(redis_manager, "active_client", None) if redis_manager is not None else None
    if client is None:
        return eager
    return RedisStreamDispatcher(settings, redis_manager, fallback=eager)


@dataclass
class TaskWorker:
    """Consumes the task stream in a separate process (``python -m src.worker``)."""

    settings: Settings
    redis_manager: Any
    registry: Mapping[str, TaskSpec] | None = None
    consumer_name: str = field(default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}")
    _running: bool = False

    @property
    def _client(self) -> Any | None:
        return getattr(self.redis_manager, "client", None)

    async def _ensure_group(self) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("redis is required to run the task worker")
        try:
            await client.xgroup_create(
                self.settings.TASKS_STREAM,
                self.settings.TASKS_GROUP,
                id="0",
                mkstream=True,
            )
        except Exception as exc:  # BUSYGROUP == already exists
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self, stop_event: asyncio.Event) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("redis is required to run the task worker")
        await self._ensure_group()
        registry = dict(self.registry or _registry)
        self._running = True
        logger.info(
            "task worker started",
            extra=log_extra(
                event="worker_started",
                stream=self.settings.TASKS_STREAM,
                consumer=self.consumer_name,
            ),
        )
        try:
            while not stop_event.is_set():
                try:
                    batches = await client.xreadgroup(
                        self.settings.TASKS_GROUP,
                        self.consumer_name,
                        {self.settings.TASKS_STREAM: ">"},
                        count=10,
                        block=1000,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("task worker read failed")
                    await asyncio.sleep(1.0)
                    continue
                if not batches:
                    continue
                for _stream, messages in batches:
                    for message_id, fields in messages:
                        await self._handle(client, message_id, fields, registry)
        finally:
            self._running = False
            logger.info("task worker stopped", extra=log_extra(event="worker_stopped"))

    async def _handle(
        self,
        client: Any,
        message_id: Any,
        fields: Mapping[str, Any],
        registry: Mapping[str, TaskSpec],
    ) -> None:
        decoded = {
            (key.decode() if isinstance(key, bytes) else str(key)): (
                value.decode() if isinstance(value, bytes) else value
            )
            for key, value in fields.items()
        }
        name = decoded.get("name", "")
        attempt = int(decoded.get("attempt", "0") or 0)
        snapshot = {
            "trace_id": decoded.get("trace_id", ""),
            "request_id": decoded.get("request_id", ""),
            "user_id": "",
            "route": "",
        }
        spec = registry.get(name)
        if spec is None:
            logger.error("unknown task in stream", extra=log_extra(event="task_unknown", task=name))
            await client.xack(self.settings.TASKS_STREAM, self.settings.TASKS_GROUP, message_id)
            return

        try:
            kwargs = json.loads(decoded.get("kwargs", "{}"))
            with restored_context(snapshot):
                await spec.func(**kwargs)
            await client.xack(self.settings.TASKS_STREAM, self.settings.TASKS_GROUP, message_id)
            logger.info(
                "task completed",
                extra=log_extra(event="task_completed", task=name, attempt=attempt),
            )
        except Exception as exc:
            next_attempt = attempt + 1
            if next_attempt >= spec.max_attempts:
                logger.exception(
                    "task dead-lettered",
                    extra=log_extra(event="task_dead_letter", task=name, attempt=attempt),
                )
                await client.xadd(
                    f"{self.settings.TASKS_STREAM}:dead",
                    {**decoded, "error": str(exc)[:500]},
                    maxlen=10_000,
                )
            else:
                delay = min(60.0, spec.backoff_seconds * (2**attempt))
                logger.warning(
                    "task failed, retrying",
                    extra=log_extra(
                        event="task_retry", task=name, attempt=next_attempt, delay=delay
                    ),
                )
                await asyncio.sleep(delay)
                await client.xadd(
                    self.settings.TASKS_STREAM,
                    {**decoded, "attempt": str(next_attempt)},
                    maxlen=100_000,
                )
            await client.xack(self.settings.TASKS_STREAM, self.settings.TASKS_GROUP, message_id)


__all__ = [
    "InProcessDispatcher",
    "RedisStreamDispatcher",
    "TaskDispatcher",
    "TaskSpec",
    "TaskWorker",
    "build_dispatcher",
    "clear_registry",
    "get_registry",
    "task",
]
