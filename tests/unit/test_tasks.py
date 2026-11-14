"""Task queue: eager fallback, stream dispatcher and worker retry/dead-letter."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from src.app.core.config import Settings
from src.app.core.tasks import (
    InProcessDispatcher,
    RedisStreamDispatcher,
    TaskSpec,
    TaskWorker,
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "TASKS_EAGER": "true",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _spec(func: Any, *, attempts: int = 3, backoff: float = 0.0) -> TaskSpec:
    return TaskSpec(name="demo.task", func=func, max_attempts=attempts, backoff_seconds=backoff)


@pytest.mark.asyncio
async def test_in_process_dispatcher_runs_and_ignores_unknown() -> None:
    calls: list[str] = []

    async def demo(value: str) -> None:
        calls.append(value)

    dispatcher = InProcessDispatcher(_settings(), registry={"demo": _spec(demo)})
    assert await dispatcher.enqueue("missing") is None
    job_id = await dispatcher.enqueue("demo", value="ok")
    assert job_id
    await dispatcher.drain()
    assert calls == ["ok"]

    await dispatcher.aclose()
    assert await dispatcher.enqueue("demo", value="late") is None


@pytest.mark.asyncio
async def test_in_process_dispatcher_catches_task_errors() -> None:
    async def boom() -> None:
        raise RuntimeError("task boom")

    dispatcher = InProcessDispatcher(_settings(), registry={"boom": _spec(boom)})
    await dispatcher.enqueue("boom")
    await dispatcher.drain()


class FakeClient:
    def __init__(self, *, batches: list[Any] | None = None) -> None:
        self.batches = batches or []
        self.acked: list[Any] = []
        self.added: list[tuple[str, dict[str, Any]]] = []
        self.group_error: Exception | None = None

    async def xgroup_create(self, *args: object, **kwargs: object) -> None:
        if self.group_error is not None:
            raise self.group_error

    async def xreadgroup(self, *args: object, **kwargs: object) -> list[Any]:
        if self.batches:
            return self.batches.pop(0)
        # Yield so the stop event can be set; a real Redis BLOCK would sleep too.
        await asyncio.sleep(0.01)
        return []

    async def xack(self, stream: str, group: str, message_id: Any) -> None:
        self.acked.append(message_id)

    async def xadd(self, stream: str, fields: dict[str, Any], **kwargs: object) -> str:
        self.added.append((stream, fields))
        return "1-0"


@pytest.mark.asyncio
async def test_redis_dispatcher_falls_back_on_missing_client_and_xadd_error() -> None:
    async def demo() -> None:
        return None

    class NoClient:
        client = None
        blocking_client = None

    fallback = InProcessDispatcher(_settings(), registry={"demo": _spec(demo)})
    dispatcher = RedisStreamDispatcher(_settings(), NoClient(), fallback=fallback)
    assert await dispatcher.enqueue("demo") is not None
    await dispatcher.drain()
    await dispatcher.aclose()

    class BrokenClient:
        client = type("C", (), {"xadd": staticmethod(lambda *a, **k: _raise())})()

    dispatcher2 = RedisStreamDispatcher(_settings(), BrokenClient(), fallback=None)
    assert await dispatcher2.enqueue("demo") is None


async def _raise() -> None:
    raise RuntimeError("xadd down")


@pytest.mark.asyncio
async def test_worker_acks_success_and_unknown_tasks() -> None:
    ran: list[int] = []

    async def demo(value: int) -> None:
        ran.append(value)

    worker = TaskWorker(_settings(), redis_manager=None, registry={"demo": _spec(demo)})
    client = FakeClient()
    worker._client_override = client

    await worker._handle(
        client, "1-0", {"name": "demo", "kwargs": json.dumps({"value": 7})}, worker.registry
    )
    assert ran == [7]
    assert client.acked == ["1-0"]

    await worker._handle(client, "2-0", {"name": "missing"}, worker.registry)
    assert client.acked == ["1-0", "2-0"]


@pytest.mark.asyncio
async def test_worker_retries_then_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom() -> None:
        raise RuntimeError("boom")

    worker = TaskWorker(_settings(), redis_manager=None, registry={"demo": _spec(boom, attempts=2)})
    client = FakeClient()
    worker._client_override = client

    await worker._handle(client, "1-0", {"name": "demo", "attempt": "0"}, worker.registry)
    assert client.added[0][0] == worker.settings.TASKS_STREAM
    assert client.added[0][1]["attempt"] == "1"
    assert client.acked == ["1-0"]

    await worker._handle(client, "2-0", {"name": "demo", "attempt": "1"}, worker.registry)
    assert client.added[1][0] == f"{worker.settings.TASKS_STREAM}:dead"
    assert client.added[1][1]["error"] == "boom"


@pytest.mark.asyncio
async def test_worker_run_loop_and_group_errors() -> None:
    async def demo() -> None:
        return None

    worker = TaskWorker(_settings(), redis_manager=None, registry={"demo": _spec(demo)})
    client = FakeClient(batches=[[("tasks", [("1-0", {"name": "demo", "kwargs": "{}"})])]])
    worker._client_override = client
    stop = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(worker.run(stop), stopper())
    assert client.acked == ["1-0"]

    busy = FakeClient()
    busy.group_error = RuntimeError("BUSYGROUP consumer group exists")
    worker2 = TaskWorker(_settings(), redis_manager=None, registry={"demo": _spec(demo)})
    worker2._client_override = busy
    await worker2._ensure_group()

    broken = FakeClient()
    broken.group_error = RuntimeError("other failure")
    worker3 = TaskWorker(_settings(), redis_manager=None, registry={"demo": _spec(demo)})
    worker3._client_override = broken
    with pytest.raises(RuntimeError, match="other failure"):
        await worker3._ensure_group()
