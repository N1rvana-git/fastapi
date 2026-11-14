"""Idempotency store semantics."""

from __future__ import annotations

import pytest
from src.app.core.idempotency import (
    IdempotencyGuard,
    IdempotencyOutcome,
    IdempotencyRecord,
    InMemoryIdempotencyStore,
    body_fingerprint,
)


@pytest.mark.asyncio
async def test_first_request_starts_then_completed_replays() -> None:
    store = InMemoryIdempotencyStore()
    outcome, _ = await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    assert outcome is IdempotencyOutcome.STARTED

    await store.complete(
        "k", IdempotencyRecord(state="completed", status_code=201, body={"id": 1}), ttl=60
    )
    outcome, record = await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    assert outcome is IdempotencyOutcome.REPLAY
    assert record is not None
    assert record.body == {"id": 1}
    assert record.status_code == 201


@pytest.mark.asyncio
async def test_pending_key_conflicts() -> None:
    store = InMemoryIdempotencyStore()
    await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    outcome, _ = await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    assert outcome is IdempotencyOutcome.IN_PROGRESS


@pytest.mark.asyncio
async def test_same_key_with_different_payload_is_a_mismatch() -> None:
    store = InMemoryIdempotencyStore()
    await store.begin("k", fingerprint="fp-1", ttl=60, pending_ttl=10)
    outcome, _ = await store.begin("k", fingerprint="fp-2", ttl=60, pending_ttl=10)
    assert outcome is IdempotencyOutcome.MISMATCH


@pytest.mark.asyncio
async def test_release_allows_retry() -> None:
    store = InMemoryIdempotencyStore()
    await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    await store.release("k")
    outcome, _ = await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    assert outcome is IdempotencyOutcome.STARTED


@pytest.mark.asyncio
async def test_release_does_not_drop_completed_entry() -> None:
    store = InMemoryIdempotencyStore()
    await store.begin("k", fingerprint="fp", ttl=60, pending_ttl=10)
    await store.complete("k", IdempotencyRecord(state="completed", status_code=200), ttl=60)
    await store.release("k")
    assert await store.get("k") is not None


@pytest.mark.asyncio
async def test_guard_remembers_and_releases() -> None:
    store = InMemoryIdempotencyStore()
    guard = IdempotencyGuard(store=store, key="scope:abc", fingerprint="fp", ttl=60, pending_ttl=10)
    assert await guard.begin() is IdempotencyOutcome.STARTED
    await guard.remember({"ok": True}, status_code=201)
    await guard.release()  # must not delete a completed record

    replaying = IdempotencyGuard(
        store=store, key="scope:abc", fingerprint="fp", ttl=60, pending_ttl=10
    )
    assert await replaying.begin() is IdempotencyOutcome.REPLAY
    assert replaying.record is not None and replaying.record.body == {"ok": True}


def test_fingerprint_is_stable_and_order_sensitive() -> None:
    assert body_fingerprint("a", "b") == body_fingerprint("a", "b")
    assert body_fingerprint("a", "b") != body_fingerprint("b", "a")
