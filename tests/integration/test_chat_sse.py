"""SSE chat: streaming, replay, history and idempotency."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from src.app.modules.chat.service import ChatDeps, ChatService
from src.app.shared.deps import get_chat_service
from tests.conftest import FakeAgentRuntime

SSE_HEADERS = {"Accept": "text/event-stream"}


def _override_service(app, runtime: FakeAgentRuntime) -> None:
    container = app.state.container
    service = ChatService(
        deps=ChatDeps(
            settings=container.settings,
            database=container.database,
            runtime=runtime,
            buffer=container.stream_buffer,
            locks=container.locks,
            idempotency=container.idempotency,
        )
    )
    app.dependency_overrides[get_chat_service] = lambda: service


@pytest.mark.asyncio
async def test_stream_returns_tokens_and_persists_history(
    client: AsyncClient, fake_runtime: FakeAgentRuntime, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/items/ai/agent/stream",
        json={"message": "你好，有什么推荐？"},
        headers={
            **auth_headers,
            **SSE_HEADERS,
            "X-Idempotency-Key": "msg-1",
            "X-Thread-ID": "u1:main",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-thread-id"] == "u1:main"

    body = response.text
    assert "event: token" in body
    assert "event: done" in body
    assert "我是闲小宝" in body
    assert fake_runtime.calls == 1

    history = await client.get(
        "/items/ai/history", params={"thread_id": "u1:main"}, headers=auth_headers
    )
    assert history.status_code == 200
    records = history.json()
    assert [record["role"] for record in records] == ["user", "assistant"]
    assert records[0]["content"] == "你好，有什么推荐？"
    assert records[1]["content"] == "你好，我是闲小宝"


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_instead_of_calling_llm(
    client: AsyncClient, fake_runtime: FakeAgentRuntime, auth_headers: dict[str, str]
) -> None:
    headers = {
        **auth_headers,
        **SSE_HEADERS,
        "X-Idempotency-Key": "msg-2",
        "X-Thread-ID": "u1:main",
    }
    first = await client.post("/items/ai/agent/stream", json={"message": "在吗"}, headers=headers)
    second = await client.post("/items/ai/agent/stream", json={"message": "在吗"}, headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert fake_runtime.calls == 1
    assert "我是闲小宝" in second.text


@pytest.mark.asyncio
async def test_same_key_different_message_is_rejected(
    client: AsyncClient, fake_runtime: FakeAgentRuntime, auth_headers: dict[str, str]
) -> None:
    headers = {**auth_headers, **SSE_HEADERS, "X-Idempotency-Key": "msg-3"}
    await client.post("/items/ai/agent/stream", json={"message": "第一句"}, headers=headers)
    conflicting = await client.post(
        "/items/ai/agent/stream", json={"message": "第二句"}, headers=headers
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_stream_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/items/ai/agent/stream", json={"message": "hi"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_interrupt_is_forwarded_and_history_records_notice(
    client: AsyncClient, started_app, auth_headers: dict[str, str]
) -> None:
    runtime = FakeAgentRuntime(
        tokens=[],
        interrupt={
            "approval_id": 7,
            "thread_id": "u1:main",
            "action": "create_order",
            "message": "已提交人工审核，请稍候。",
            "payload": {"amount": 1500},
        },
    )
    _override_service(started_app, runtime)

    response = await client.post(
        "/items/ai/agent/stream",
        json={"message": "帮我下单"},
        headers={
            **auth_headers,
            **SSE_HEADERS,
            "X-Idempotency-Key": "msg-interrupt",
            "X-Thread-ID": "u1:main",
        },
    )
    assert response.status_code == 200
    assert "event: interrupt_required" in response.text
    assert "已提交人工审核" in response.text

    history = await client.get(
        "/items/ai/history", params={"thread_id": "u1:main"}, headers=auth_headers
    )
    contents = [record["content"] for record in history.json()]
    assert any("已提交人工审核" in content for content in contents)


@pytest.mark.asyncio
async def test_history_is_scoped_to_the_user(
    client: AsyncClient,
    fake_runtime: FakeAgentRuntime,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    await client.post(
        "/items/ai/agent/stream",
        json={"message": "我的私密对话"},
        headers={**auth_headers, "X-Idempotency-Key": "private-1", "X-Thread-ID": "u1:main"},
    )
    other = await client.get("/items/ai/history", headers=second_user_headers)
    assert other.json() == []


@pytest.mark.asyncio
async def test_anonymous_history_is_empty_not_401(client: AsyncClient) -> None:
    response = await client.get("/items/ai/history")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_clear_history(
    client: AsyncClient, fake_runtime: FakeAgentRuntime, auth_headers: dict[str, str]
) -> None:
    await client.post(
        "/items/ai/agent/stream",
        json={"message": "记住我"},
        headers={**auth_headers, "X-Idempotency-Key": "clear-1"},
    )
    cleared = await client.delete("/items/ai/history", headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 2
    assert (await client.get("/items/ai/history", headers=auth_headers)).json() == []


@pytest.mark.asyncio
async def test_validation_error_shape(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/items/ai/agent/stream", json={"message": ""}, headers=auth_headers
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "trace_id" in body["error"]
