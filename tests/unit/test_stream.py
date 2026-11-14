"""SSE stream buffer, thread lock and frame encoding."""

from __future__ import annotations

import asyncio

import pytest
from src.app.modules.chat.stream import (
    InMemoryStreamBuffer,
    ThreadLockManager,
    sse_frame,
)


@pytest.mark.asyncio
async def test_append_and_replay_after_cursor() -> None:
    buffer = InMemoryStreamBuffer()
    first = await buffer.append("t1", "token", {"text": "a"})
    second = await buffer.append("t1", "token", {"text": "b"})

    entries = await buffer.read("t1", None, block_ms=10)
    assert [entry.id for entry in entries] == [first, second]

    tail = await buffer.read("t1", first, block_ms=10)
    assert [entry.id for entry in tail] == [second]
    assert tail[0].data == {"text": "b"}


@pytest.mark.asyncio
async def test_read_blocks_then_returns_new_entries() -> None:
    buffer = InMemoryStreamBuffer()

    async def produce() -> None:
        await asyncio.sleep(0.05)
        await buffer.append("t2", "done", {})

    task = asyncio.create_task(produce())
    entries = await buffer.read("t2", None, block_ms=1000)
    await task
    assert len(entries) == 1
    assert entries[0].event == "done"


@pytest.mark.asyncio
async def test_read_times_out_quietly() -> None:
    buffer = InMemoryStreamBuffer()
    entries = await buffer.read("missing", None, block_ms=20)
    assert entries == []


@pytest.mark.asyncio
async def test_buffer_is_bounded() -> None:
    buffer = InMemoryStreamBuffer(maxlen=3)
    for index in range(5):
        await buffer.append("t3", "token", {"i": index})
    entries = await buffer.read("t3", None, block_ms=10)
    assert [entry.data["i"] for entry in entries] == [2, 3, 4]


@pytest.mark.asyncio
async def test_thread_lock_is_exclusive_and_reentrant_after_release() -> None:
    manager = ThreadLockManager(redis_manager=None, ttl=30)

    async with manager.hold("thread", "run-a") as first:
        assert first
        async with manager.hold("thread", "run-b") as second:
            assert second is False

    async with manager.hold("thread", "run-c") as third:
        assert third


def test_sse_frame_includes_id_and_event() -> None:
    frame = sse_frame("token", {"text": "你"}, event_id="12-0")
    assert frame.startswith("id: 12-0\nevent: token\ndata: ")
    assert frame.endswith("\n\n")
    assert "你" in frame
