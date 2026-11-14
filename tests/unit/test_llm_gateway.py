"""LLM gateway: SSE parsing, retry semantics and cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from src.app.core.config import Settings
from src.app.core.exceptions import DependencyUnavailableError
from src.app.modules.chat.llm_gateway import LLMGateway, healthcheck


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "CHAT_API_KEY": "test-key",
        "CHAT_BASE_URL": "https://llm.test/v1",
        "CHAT_MODEL": "deepseek-flash",
        "LLM_MAX_RETRIES": 2,
        "LLM_RETRY_BASE_DELAY": 0.0,
        "LLM_MAX_CONCURRENCY": 2,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        lines: list[str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status_code = status
        self._lines = lines or []
        self._body = body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def stream(self, *args: object, **kwargs: object) -> Any:
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


async def _events(gateway: LLMGateway, **kwargs: Any) -> list[Any]:
    return [
        event async for event in gateway.stream_chat([{"role": "user", "content": "hi"}], **kwargs)
    ]


@pytest.mark.asyncio
async def test_unconfigured_gateway_fails_fast() -> None:
    gateway = LLMGateway(_settings(CHAT_API_KEY=""), FakePool(FakeClient([])))
    with pytest.raises(DependencyUnavailableError, match="not configured"):
        await _events(gateway)
    with pytest.raises(DependencyUnavailableError):
        healthcheck(gateway)


@pytest.mark.asyncio
async def test_text_usage_and_tool_calls_are_parsed() -> None:
    lines = [
        ": keep-alive",
        'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}',
        'data: {"usage":{"total_tokens":3}}',
        "data: [DONE]",
    ]
    gateway = LLMGateway(_settings(), FakePool(FakeClient([FakeResponse(lines=lines)])))
    events = await _events(gateway)

    assert [event.type for event in events] == ["text", "usage"]
    assert events[0].text == "你好"
    assert events[1].usage == {"total_tokens": 3}


@pytest.mark.asyncio
async def test_tool_call_deltas_are_assembled() -> None:
    lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"function":{"name":"search_items","arguments":"{\\"query\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"相机\\"}"}}]}}]}',
        "data: [DONE]",
    ]
    gateway = LLMGateway(_settings(), FakePool(FakeClient([FakeResponse(lines=lines)])))
    events = await _events(gateway, tools=[{"type": "function"}])

    assert len(events) == 1
    assert events[0].type == "tool_calls"
    call = events[0].tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "search_items"
    assert call.arguments == '{"query":"相机"}'


@pytest.mark.asyncio
async def test_finish_reason_only_stream_yields_done() -> None:
    lines = [
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    gateway = LLMGateway(_settings(), FakePool(FakeClient([FakeResponse(lines=lines)])))
    events = await _events(gateway)

    assert [event.type for event in events] == ["done"]
    assert events[0].error == "stop"


@pytest.mark.asyncio
async def test_malformed_json_is_ignored() -> None:
    lines = [
        "data: {not-json}",
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]
    gateway = LLMGateway(_settings(), FakePool(FakeClient([FakeResponse(lines=lines)])))
    events = await _events(gateway)

    assert [event.text for event in events if event.type == "text"] == ["ok"]


@pytest.mark.asyncio
async def test_client_error_is_not_retried() -> None:
    client = FakeClient([FakeResponse(status=400, body=b"bad request")])
    gateway = LLMGateway(_settings(), FakePool(client))

    with pytest.raises(DependencyUnavailableError, match="rejected"):
        await _events(gateway)
    assert client.calls == 1


@pytest.mark.asyncio
async def test_retryable_status_then_success() -> None:
    success = FakeResponse(
        lines=['data: {"choices":[{"delta":{"content":"retry-ok"}}]}', "data: [DONE]"]
    )
    client = FakeClient([FakeResponse(status=503, body=b"busy"), success])
    gateway = LLMGateway(_settings(), FakePool(client))

    events = await _events(gateway)
    assert [event.text for event in events] == ["retry-ok"]
    assert client.calls == 2


@pytest.mark.asyncio
async def test_retry_exhaustion_raises() -> None:
    client = FakeClient([FakeResponse(status=503), FakeResponse(status=503)])
    gateway = LLMGateway(_settings(), FakePool(client))

    with pytest.raises(DependencyUnavailableError, match="unavailable after 2"):
        await _events(gateway)
    assert client.calls == 2


@pytest.mark.asyncio
async def test_cancelled_stream_stops_early() -> None:
    cancel = asyncio.Event()
    cancel.set()
    lines = ['data: {"choices":[{"delta":{"content":"should-not-appear"}}]}', "data: [DONE]"]
    gateway = LLMGateway(_settings(), FakePool(FakeClient([FakeResponse(lines=lines)])))
    events = await _events(gateway, cancel_event=cancel)

    assert all(event.type != "text" for event in events)


@pytest.mark.asyncio
async def test_transport_error_is_wrapped() -> None:
    gateway = LLMGateway(
        _settings(LLM_MAX_RETRIES=1), FakePool(FakeClient([httpx.ConnectError("down")]))
    )

    with pytest.raises(DependencyUnavailableError, match="unavailable"):
        await _events(gateway)


@pytest.mark.asyncio
async def test_non_retryable_http_error_is_wrapped() -> None:
    gateway = LLMGateway(
        _settings(LLM_MAX_RETRIES=1),
        FakePool(FakeClient([httpx.TooManyRedirects("loop")])),
    )

    with pytest.raises(DependencyUnavailableError, match="transport"):
        await _events(gateway)
