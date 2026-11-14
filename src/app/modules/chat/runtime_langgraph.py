"""LangGraph runtime: real state machine, checkpoints and ``interrupt()``.

Design notes
------------
* **One graph, many conversations.** The compiled graph is stateless; all state
  lives in the checkpointer keyed by ``thread_id`` (our conversation id).
* **Business effects stay in the approval service.** The ``create_order`` tool
  still raises ``ApprovalRequiredError``; this node persists a row in
  ``agent_approvals`` (idempotently) and calls ``interrupt()``.  The HTTP
  ``/resume`` endpoint decides *and executes* the purchase exactly once, then
  resumes the graph with the resulting ``order_id`` so the model can continue
  the conversation.  There is no second code path that could double-order.
* **Re-entry safety.** LangGraph re-runs a node from the top when it resumes
  from ``interrupt``.  Everything before ``interrupt()`` is idempotent:
  ``request_approval`` is keyed by (thread, action, payload) and the purchase
  gate raises before touching stock.
* **Bounded steps.** ``steps`` in the state caps the tool loop, mirroring the
  native runtime's ``AGENT_MAX_STEPS``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from src.app.core.config import Settings
from src.app.core.exceptions import ApprovalRequiredError, ConflictError
from src.app.core.logging import get_logger
from src.app.modules.chat import approvals
from src.app.modules.chat.stream_runtime import AgentEvent
from src.app.modules.chat.tools import ToolContext, ToolDeps, execute_tool, openai_tools

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: int
    steps: int


@dataclass
class LangGraphAgentRuntime:
    settings: Settings
    model: Any  # BaseChatModel with tools bound (or a test double)
    deps: ToolDeps
    checkpointer: Any
    max_steps: int = 6
    graph: Any = field(init=False)

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ graph
    def _build_graph(self) -> Any:
        builder = StateGraph(AgentState)
        builder.add_node("chatbot", self._chatbot)
        builder.add_node("tools", self._tools)
        builder.add_edge(START, "chatbot")
        builder.add_conditional_edges("chatbot", self._route, {"tools": "tools", END: END})
        builder.add_edge("tools", "chatbot")
        return builder.compile(checkpointer=self.checkpointer)

    async def _chatbot(self, state: AgentState) -> dict[str, Any]:
        steps = int(state.get("steps", 0)) + 1
        if steps > self.max_steps:
            return {
                "messages": [AIMessage(content="这个需求有点复杂，我先为您转接人工客服，请稍等。")],
                "steps": steps,
            }
        response = await self.model.ainvoke(state["messages"])
        return {"messages": [response], "steps": steps}

    def _route(self, state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    async def _tools(self, state: AgentState) -> dict[str, Any]:
        config = get_config()
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        user_id = int(state.get("user_id") or 0)
        last = state["messages"][-1]
        results: list[ToolMessage] = []

        for call in getattr(last, "tool_calls", []) or []:
            name = str(call.get("name", ""))
            arguments = call.get("args") or {}
            tool_call_id = str(call.get("id") or "")
            context = ToolContext(
                deps=self.deps,
                user_id=user_id,
                thread_id=thread_id,
                tool_call_id=tool_call_id,
            )
            try:
                content = await execute_tool(name, arguments, context)
            except ApprovalRequiredError as exc:
                approval = await self._request_approval(
                    thread_id=thread_id,
                    user_id=user_id,
                    action=name,
                    details=exc.details,
                    reason=exc.message,
                )
                decision = interrupt(
                    {
                        "approval_id": approval.id,
                        "thread_id": thread_id,
                        "action": name,
                        "reason": approval.reason,
                        "payload": exc.details,
                        "message": (
                            "这笔订单金额超过了自动授权额度，已提交人工审核。"
                            "审核通过后会立即为您下单。"
                        ),
                        "expires_at": approval.expires_at.isoformat()
                        if approval.expires_at
                        else None,
                    }
                )
                if isinstance(decision, dict) and decision.get("approved"):
                    order_id = decision.get("order_id")
                    content = (
                        f"人工审核已通过，订单 #{order_id} 已创建。"
                        if order_id
                        else "人工审核已通过，订单已创建。"
                    )
                else:
                    content = "人工审核未通过，本次下单已取消。"
            results.append(ToolMessage(content=content, tool_call_id=tool_call_id))
        return {"messages": results}

    # ------------------------------------------------------------------- run
    async def run(
        self,
        *,
        user_id: int,
        user_name: str,
        thread_id: str,
        messages: list[dict[str, Any]],
        cancel_event: Any,
    ) -> AsyncIterator[AgentEvent]:
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(10, self.max_steps * 3),
        }
        snapshot = await self.graph.aget_state(config)
        pending = _pending_interrupts(snapshot)
        if pending:
            raise ConflictError(
                "该会话存在待审批的挂起操作，请先处理审批",
                details={"thread_id": thread_id, "interrupts": pending},
            )

        has_history = bool(snapshot.values.get("messages"))
        payload: dict[str, Any] = (
            {"messages": [HumanMessage(content=str(messages[-1]["content"]))], "user_id": user_id}
            if has_history and messages
            else {
                "messages": _to_langchain(messages),
                "user_id": user_id,
                "steps": 0,
            }
        )

        async for chunk, metadata in self.graph.astream(
            payload, config=config, stream_mode="messages"
        ):
            if cancel_event is not None and cancel_event.is_set():
                yield AgentEvent("aborted", {"reason": "client_disconnected"})
                return
            if metadata.get("langgraph_node") != "chatbot":
                continue
            text = _chunk_text(chunk)
            if text:
                yield AgentEvent("token", {"text": text})

        final_state = await self.graph.aget_state(config)
        pending = _pending_interrupts(final_state)
        if pending:
            value = pending[0]["value"] if isinstance(pending[0].get("value"), dict) else {}
            yield AgentEvent("interrupt_required", {**value, "thread_id": thread_id})
            yield AgentEvent("done", {"interrupted": True})
            return
        yield AgentEvent("done", {"steps": int(final_state.values.get("steps", 0))})

    # ---------------------------------------------------------------- resume
    async def resume(
        self, *, thread_id: str, decision: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(10, self.max_steps * 3),
        }
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values:
            raise ConflictError("找不到可恢复的会话状态", details={"thread_id": thread_id})

        async for chunk, metadata in self.graph.astream(
            Command(resume=decision), config=config, stream_mode="messages"
        ):
            if metadata.get("langgraph_node") != "chatbot":
                continue
            text = _chunk_text(chunk)
            if text:
                yield AgentEvent("token", {"text": text})

        final_state = await self.graph.aget_state(config)
        pending = _pending_interrupts(final_state)
        if pending:
            value = pending[0]["value"] if isinstance(pending[0].get("value"), dict) else {}
            yield AgentEvent("interrupt_required", {**value, "thread_id": thread_id})
            yield AgentEvent("done", {"interrupted": True})
            return
        yield AgentEvent("done", {"resumed": True})

    # --------------------------------------------------------------- helpers
    async def _request_approval(
        self,
        *,
        thread_id: str,
        user_id: int,
        action: str,
        details: dict[str, Any],
        reason: str,
    ) -> Any:
        async with self.deps.database.session() as session:
            return await approvals.request_approval(
                session,
                thread_id=thread_id,
                user_id=user_id,
                action=action,
                payload=details,
                reason=reason,
                settings=self.settings,
            )


def build_chat_model(settings: Settings) -> Any:
    """OpenAI-compatible chat model with our JSON-schema tools bound."""

    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=settings.CHAT_MODEL,
        api_key=settings.chat_api_key or "not-configured",
        base_url=settings.CHAT_BASE_URL,
        temperature=0.1,
        streaming=True,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=0,  # retries/backoff live in our own gateway semantics
    )
    return model.bind_tools(openai_tools())


def _to_langchain(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def _pending_interrupts(snapshot: Any) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for task in getattr(snapshot, "tasks", None) or []:
        for entry in getattr(task, "interrupts", None) or []:
            pending.append(
                {
                    "task_id": getattr(task, "id", None),
                    "node": getattr(task, "name", None),
                    "value": getattr(entry, "value", None),
                }
            )
    return pending


__all__ = [
    "AgentState",
    "LangGraphAgentRuntime",
    "build_chat_model",
]
