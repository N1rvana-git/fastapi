"""Native runtime: intent routing + reflection observation injection."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.app.core.config import Settings
from src.app.modules.chat.llm_gateway import StreamEvent, ToolCall
from src.app.modules.chat.stream_runtime import NativeAgentRuntime
from src.app.modules.chat.tools import ToolDeps


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ENVIRONMENT="test",
        SECRET_KEY="x" * 48,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        CHAT_API_KEY="test",
        CHAT_MODEL="deepseek-flash",
    )


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append({"messages": list(messages), "tools": tools})
        if len(self.calls) == 1:
            yield StreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_search_1",
                        name="search_items",
                        arguments=json.dumps({"query": "显示器", "max_price": 2000}),
                    )
                ],
            )
        else:
            yield StreamEvent(type="text", text="我帮您放宽一点预算再找找")


@pytest.mark.asyncio
async def test_intent_filters_tools_and_empty_result_gets_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeGateway()
    runtime = NativeAgentRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        deps=ToolDeps(
            settings=_settings(),
            database=object(),
            embeddings=None,
            vision=None,
            dispatcher=None,
        ),
    )

    async def empty_tool(_name: str, _args: dict[str, Any], _ctx: Any) -> str:
        return json.dumps({"status": "empty", "results": []})

    monkeypatch.setattr("src.app.modules.chat.stream_runtime.execute_tool", empty_tool)

    events = [
        event
        async for event in runtime.run(
            user_id=1,
            user_name="buyer",
            thread_id="u1:routing",
            messages=[{"role": "user", "content": "预算 2000 想买显示器"}],
            cancel_event=asyncio.Event(),
        )
    ]

    types = [event.type for event in events]
    assert types[0] == "intent"
    assert types[0] == "intent" and events[0].data["intent"] == "shopping_search"
    assert "tool_start" in types and "tool_end" in types

    assert gateway.calls[0]["tools"] is not None
    tool_names = {tool["function"]["name"] for tool in gateway.calls[0]["tools"] or []}
    assert tool_names == {"search_items", "search_web_price"}
    assert "create_order" not in tool_names

    observation = gateway.calls[1]["messages"][-1]
    assert observation["role"] == "tool"
    payload = json.loads(observation["content"])
    assert payload["status"] == "empty"
    assert "放宽价格上下限 20%" in payload["reflection_hint"]
    assert any(event.type == "token" for event in events)
    assert types[-1] == "done"
