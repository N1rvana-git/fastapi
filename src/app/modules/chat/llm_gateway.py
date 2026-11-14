"""Async LLM gateway: one shared connection pool, hard timeouts, bounded retry.

Why not the vendor SDKs: ``zhipuai`` exposes only a sync client and the old code
called it from ``async def`` handlers, blocking the event loop per request.  The
OpenAI-compatible HTTP API is simple enough to speak directly with ``httpx``,
which gives us exactly the controls the PDF asks for:

* a semaphore sized for the upstream quota (backpressure, not retry storms);
* explicit connect/read/write/pool timeouts;
* bounded exponential backoff on 429/5xx/connection errors, but only while no
  token has been emitted yet (retrying a half-stream would duplicate output);
* cancellation support (stop billing tokens when the client goes away);
* stable prompt ordering so provider-side prefix caching can hit.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from src.app.core.config import Settings
from src.app.core.exceptions import DependencyUnavailableError
from src.app.core.http import HttpClientPool
from src.app.core.logging import get_logger

logger = get_logger(__name__)

EventType = Literal["text", "tool_calls", "usage", "done", "error"]

_RETRYABLE_TRANSPORT = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


class _RetryableUpstream(Exception):
    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class StreamEvent:
    type: EventType
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    error: str = ""


class LLMGateway:
    def __init__(self, settings: Settings, http_pool: HttpClientPool) -> None:
        self.settings = settings
        self.http_pool = http_pool
        self._semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)

    @property
    def configured(self) -> bool:
        return bool(self.settings.chat_api_key)

    def _client(self) -> httpx.AsyncClient:
        if not self.configured:
            raise DependencyUnavailableError(
                "LLM gateway is not configured (set CHAT_API_KEY or API_KEY)"
            )
        return self.http_pool.client(
            "llm",
            base_url=self.settings.CHAT_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.settings.chat_api_key}",
                "Content-Type": "application/json",
            },
            read_timeout=self.settings.LLM_TIMEOUT_SECONDS,
        )

    async def stream_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[StreamEvent]:
        """Yield text deltas and, at the end, any tool calls the model made."""

        payload: dict[str, Any] = {
            "model": self.settings.CHAT_MODEL,
            "messages": list(messages),
            "stream": True,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        client = self._client()
        timeout = httpx.Timeout(
            connect=self.settings.HTTP_CONNECT_TIMEOUT,
            read=self.settings.LLM_TIMEOUT_SECONDS,
            write=self.settings.HTTP_WRITE_TIMEOUT,
            pool=self.settings.HTTP_POOL_TIMEOUT,
        )
        attempts = max(1, self.settings.LLM_MAX_RETRIES)
        emitted = False

        async with self._semaphore:
            for attempt in range(1, attempts + 1):
                try:
                    async with client.stream(
                        "POST", "/chat/completions", json=payload, timeout=timeout
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            body = (await response.aread()).decode("utf-8", "replace")[:300]
                            raise _RetryableUpstream(
                                f"upstream status {response.status_code}: {body}",
                                status_code=response.status_code,
                            )
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", "replace")[:500]
                            raise DependencyUnavailableError(
                                "LLM upstream rejected the request",
                                details={"status_code": response.status_code, "body": body},
                            )
                        async for event in self._parse_sse(response, cancel_event=cancel_event):
                            emitted = True
                            yield event
                        return
                except asyncio.CancelledError:
                    raise
                except DependencyUnavailableError:
                    raise
                except (_RetryableUpstream, *_RETRYABLE_TRANSPORT) as exc:  # type: ignore[misc]
                    if emitted or attempt >= attempts:
                        raise DependencyUnavailableError(
                            f"LLM upstream unavailable after {attempt} attempt(s): {exc}"
                        ) from exc
                    delay = min(8.0, self.settings.LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                    logger.warning(
                        "llm retry",
                        extra={
                            "ctx_attempt": attempt,
                            "ctx_delay": round(delay, 2),
                            "ctx_error": str(exc)[:200],
                        },
                    )
                    await asyncio.sleep(delay)
                except httpx.HTTPError as exc:
                    raise DependencyUnavailableError(f"LLM transport error: {exc}") from exc

    async def _parse_sse(
        self, response: httpx.Response, *, cancel_event: Any | None
    ) -> AsyncIterator[StreamEvent]:
        tool_calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] | None = None
        emitted_text = False
        finish_reason: str | None = None

        async for line in response.aiter_lines():
            if cancel_event is not None and cancel_event.is_set():
                logger.info("llm stream cancelled by caller")
                break
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            finish_reason = choices[0].get("finish_reason") or finish_reason
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                emitted_text = True
                yield StreamEvent(type="text", text=content)
            for call in delta.get("tool_calls") or []:
                index = int(call.get("index", 0))
                slot = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    slot["id"] = call["id"]
                function = call.get("function") or {}
                if function.get("name"):
                    slot["name"] = function["name"]
                if function.get("arguments"):
                    slot["arguments"] += function["arguments"]

        if tool_calls:
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCall(
                        id=slot["id"] or f"call_{index}",
                        name=slot["name"],
                        arguments=slot["arguments"] or "{}",
                    )
                    for index, slot in sorted(tool_calls.items())
                ],
            )
        if usage:
            yield StreamEvent(type="usage", usage=usage)
        if not emitted_text and not tool_calls:
            yield StreamEvent(type="done", error=str(finish_reason or ""))


def healthcheck(gateway: LLMGateway) -> None:
    """Cheap readiness probe: validates configuration only (no quota burn)."""

    if not gateway.configured:
        raise DependencyUnavailableError("LLM gateway is not configured")


__all__ = ["LLMGateway", "StreamEvent", "ToolCall", "healthcheck"]
