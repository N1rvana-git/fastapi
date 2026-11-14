"""LangGraph runtime: interrupt on high-value orders, then resume.

The model is a scripted double, so the test exercises the real graph, the real
``interrupt()`` primitive, the real approval table and the real purchase service
without any network call.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from src.app.modules.chat import approvals
from src.app.modules.chat.runtime_langgraph import LangGraphAgentRuntime
from src.app.modules.chat.tools import ToolDeps
from src.app.modules.users import repository as users_repository
from tests.conftest import create_listing


class ScriptedModel:
    """Returns predefined AIMessages; optionally records the tool schemas."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools: list[Any]) -> ScriptedModel:
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _tool_call_message(item_id: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "create_order",
                "args": {"item_id": item_id, "address": "上海市浦东新区测试路 1 号", "quantity": 1},
                "id": "call_order_1",
            }
        ],
    )


async def _runtime(started_app, settings, responses: list[AIMessage]) -> LangGraphAgentRuntime:
    container = started_app.state.container
    deps = ToolDeps(
        settings=settings,
        database=container.database,
        embeddings=None,
        vision=None,
        dispatcher=None,
    )
    model = ScriptedModel(responses)
    return LangGraphAgentRuntime(
        settings=settings,
        model=model,
        deps=deps,
        checkpointer=InMemorySaver(),
        max_steps=4,
    )


@pytest.mark.asyncio
async def test_high_value_order_interrupts_and_resume_completes(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    from tests.conftest import register_and_login

    await register_and_login(client, email="graph-buyer@example.com")
    listing = await create_listing(client, auth_headers, price=1500.0, inventory=2)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-buyer@example.com")
        assert buyer is not None
        buyer_id = buyer.id
        buyer_name = buyer.username

    runtime = await _runtime(
        started_app,
        settings,
        [_tool_call_message(listing["id"]), AIMessage(content="订单已创建，感谢老板！")],
    )
    thread_id = f"u{buyer_id}:graph"
    events = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name=buyer_name,
            thread_id=thread_id,
            messages=[
                {"role": "system", "content": "you are a sales agent"},
                {"role": "user", "content": "我要买这台相机"},
            ],
            cancel_event=asyncio.Event(),
        )
    ]
    event_types = [event.type for event in events]
    assert "interrupt_required" in event_types
    interrupt = next(event for event in events if event.type == "interrupt_required")
    assert interrupt.data["approval_id"] > 0
    assert interrupt.data["payload"]["amount"] == 1500.0

    async with started_app.state.container.database.session() as session:
        pending = await approvals.list_pending(session, thread_id, user_id=buyer_id)
        assert len(pending) == 1
        decision = await approvals.decide(
            session,
            approval_id=pending[0].id,
            approve=True,
            actor=buyer,
            comment="批准",
            settings=settings,
            dispatcher=None,
        )
    assert decision.order_id is not None

    resume_events = [
        event
        async for event in runtime.resume(
            thread_id=thread_id,
            decision={"approved": True, "order_id": decision.order_id},
        )
    ]
    assert any(event.type == "done" for event in resume_events)
    text = "".join(
        str(event.data.get("text", "")) for event in resume_events if event.type == "token"
    )
    assert "感谢老板" in text

    # Inventory was decremented exactly once by the approval service.
    item = await client.get(f"/items/{listing['id']}")
    assert item.json()["inventory"] == 1


@pytest.mark.asyncio
async def test_rejected_approval_resumes_without_order(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    from tests.conftest import register_and_login

    await register_and_login(client, email="graph-reject@example.com")
    listing = await create_listing(client, auth_headers, price=2000.0, inventory=2)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-reject@example.com")
        assert buyer is not None
        buyer_id = buyer.id
        buyer_name = buyer.username

    runtime = await _runtime(
        started_app,
        settings,
        [_tool_call_message(listing["id"]), AIMessage(content="好的，已为您取消。")],
    )
    thread_id = f"u{buyer_id}:graph-reject"
    _ = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name=buyer_name,
            thread_id=thread_id,
            messages=[{"role": "user", "content": "帮我下单"}],
            cancel_event=asyncio.Event(),
        )
    ]

    async with started_app.state.container.database.session() as session:
        pending = await approvals.list_pending(session, thread_id, user_id=buyer_id)
        decision = await approvals.decide(
            session,
            approval_id=pending[0].id,
            approve=False,
            actor=buyer,
            comment="不批",
            settings=settings,
            dispatcher=None,
        )
    assert decision.order_id is None

    resume_events = [
        event
        async for event in runtime.resume(
            thread_id=thread_id, decision={"approved": False, "order_id": None}
        )
    ]
    text = "".join(
        str(event.data.get("text", "")) for event in resume_events if event.type == "token"
    )
    assert "取消" in text
    item = await client.get(f"/items/{listing['id']}")
    assert item.json()["inventory"] == 2


@pytest.mark.asyncio
async def test_new_message_while_interrupted_is_rejected(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    from tests.conftest import register_and_login

    await register_and_login(client, email="graph-busy@example.com")
    listing = await create_listing(client, auth_headers, price=1500.0)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-busy@example.com")
        assert buyer is not None
        buyer_id = buyer.id

    runtime = await _runtime(
        started_app, settings, [_tool_call_message(listing["id"]), AIMessage(content="ok")]
    )
    thread_id = f"u{buyer_id}:graph-busy"
    _ = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name="buyer",
            thread_id=thread_id,
            messages=[{"role": "user", "content": "下单"}],
            cancel_event=asyncio.Event(),
        )
    ]

    from src.app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        _ = [
            event
            async for event in runtime.run(
                user_id=buyer_id,
                user_name="buyer",
                thread_id=thread_id,
                messages=[{"role": "user", "content": "还在吗"}],
                cancel_event=asyncio.Event(),
            )
        ]


@pytest.mark.asyncio
async def test_chat_service_resume_continues_the_graph(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    """The HTTP-layer service (ChatService.resume) must also drive the graph."""

    from src.app.core.idempotency import InMemoryIdempotencyStore
    from src.app.modules.chat.service import ChatDeps, ChatService
    from src.app.modules.chat.stream import InMemoryStreamBuffer, ThreadLockManager
    from tests.conftest import register_and_login

    buyer_headers = await register_and_login(client, email="graph-service@example.com")
    listing = await create_listing(client, auth_headers, price=1500.0, inventory=2)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-service@example.com")
        assert buyer is not None
        buyer_id = buyer.id
        buyer_name = buyer.username

    runtime = await _runtime(
        started_app,
        settings,
        [_tool_call_message(listing["id"]), AIMessage(content="好的老板，订单已处理完成！")],
    )
    thread_id = f"u{buyer_id}:graph-service"
    _ = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name=buyer_name,
            thread_id=thread_id,
            messages=[{"role": "user", "content": "下单"}],
            cancel_event=asyncio.Event(),
        )
    ]

    service = ChatService(
        deps=ChatDeps(
            settings=settings,
            database=started_app.state.container.database,
            runtime=runtime,
            buffer=InMemoryStreamBuffer(),
            locks=ThreadLockManager(redis_manager=None),
            idempotency=InMemoryIdempotencyStore(),
        )
    )
    result = await service.resume(buyer, thread_id, approved=True, comment="同意")
    assert result["status"] == "approved"
    assert result["order_id"] is not None

    history = await client.get(
        "/items/ai/history", params={"thread_id": thread_id}, headers=buyer_headers
    )
    contents = [record["content"] for record in history.json()]
    assert any("订单已处理完成" in content for content in contents)


@pytest.mark.asyncio
async def test_tool_events_match_the_native_contract(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    import json

    from tests.conftest import register_and_login

    await register_and_login(client, email="graph-events@example.com")
    # Below AGENT_APPROVAL_THRESHOLD, so the tool executes without interrupt().
    listing = await create_listing(client, auth_headers, price=50.0, inventory=2)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-events@example.com")
        assert buyer is not None
        buyer_id = buyer.id

    runtime = await _runtime(
        started_app, settings, [_tool_call_message(listing["id"]), AIMessage(content="已完成")]
    )
    events = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name=buyer.username,
            thread_id=f"u{buyer_id}:graph-events",
            messages=[{"role": "user", "content": "下单"}],
            cancel_event=asyncio.Event(),
        )
    ]
    types = [event.type for event in events]
    assert "tool_start" in types and "tool_end" in types
    assert types.index("tool_start") < types.index("tool_end")

    start = next(event for event in events if event.type == "tool_start")
    assert start.data["name"] == "create_order"
    assert json.loads(start.data["arguments"])["item_id"] == listing["id"]
    end = next(event for event in events if event.type == "tool_end")
    assert end.data == {"name": "create_order", "ok": True}


@pytest.mark.asyncio
async def test_checkpoint_history_and_rollback(
    client: Any, started_app: Any, settings: Any, auth_headers: dict[str, str]
) -> None:
    from tests.conftest import register_and_login

    await register_and_login(client, email="graph-time@example.com")
    listing = await create_listing(client, auth_headers, price=50.0, inventory=2)

    async with started_app.state.container.database.session() as session:
        buyer = await users_repository.get_by_email(session, "graph-time@example.com")
        assert buyer is not None
        buyer_id = buyer.id

    runtime = await _runtime(
        started_app, settings, [_tool_call_message(listing["id"]), AIMessage(content="已完成")]
    )
    thread_id = f"u{buyer_id}:graph-time"
    _ = [
        event
        async for event in runtime.run(
            user_id=buyer_id,
            user_name=buyer.username,
            thread_id=thread_id,
            messages=[{"role": "user", "content": "下单"}],
            cancel_event=asyncio.Event(),
        )
    ]

    snapshots = await runtime.history(thread_id=thread_id, limit=20)
    assert snapshots
    assert all(item["checkpoint_id"] for item in snapshots)

    target = min(snapshots, key=lambda item: int(item["message_count"]))
    result = await runtime.rollback(thread_id=thread_id, checkpoint_id=str(target["checkpoint_id"]))
    assert result["restored"] is True

    state = await runtime.graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert len(state.values.get("messages", [])) == int(target["message_count"])


@pytest.mark.asyncio
async def test_container_selects_langgraph_runtime_when_configured(settings: Any) -> None:
    from src.app.main import create_app

    app = create_app(settings.model_copy(update={"AGENT_RUNTIME": "langgraph"}))
    async with app.router.lifespan_context(app):
        runtime = app.state.container.runtime
        assert type(runtime).__name__ == "LangGraphAgentRuntime"
