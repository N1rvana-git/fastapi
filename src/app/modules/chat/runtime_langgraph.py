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

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.config import get_config, get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.types import Command, interrupt

from src.app.core.config import Settings
from src.app.core.exceptions import ApprovalRequiredError, ConflictError
from src.app.core.logging import get_logger
from src.app.modules.chat import approvals
from src.app.modules.chat.intent import INTENT_TOOLS, classify_intent
from src.app.modules.chat.reflection import inject_reflection, is_error_result
from src.app.modules.chat.stream_runtime import AgentEvent
from src.app.modules.chat.tools import ToolContext, ToolDeps, execute_tool, openai_tools

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: int
    steps: int
    intent: str
    reflections: dict[str, int]


@dataclass
class LangGraphAgentRuntime:
    settings: Settings
    model: Any  # BaseChatModel with tools bound (or a test double)
    deps: ToolDeps
    checkpointer: Any
    max_steps: int = 6
    graph: Any = field(init=False)
    _models: dict[str, Any] = field(default_factory=dict, init=False)

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
        intent = str(state.get("intent") or "shopping_search")
        response = await self._model_for(intent).ainvoke(state["messages"])
        return {"messages": [response], "steps": steps}

    def _model_for(self, intent: str) -> Any:
        if intent in self._models:
            return self._models[intent]
        names = INTENT_TOOLS.get(intent, ())
        if not names:
            bound = self.model
        else:
            try:
                bound = self.model.bind_tools(openai_tools(names))
            except (AttributeError, TypeError):  # test doubles / non-tool models
                bound = self.model
        self._models[intent] = bound
        return bound

    def _route(self, state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    async def _tools(self, state: AgentState) -> dict[str, Any]:
        config = get_config()
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        user_id = int(state.get("user_id") or 0)
        intent = str(state.get("intent") or "shopping_search")
        allowed = set(INTENT_TOOLS.get(intent, ()))
        last = state["messages"][-1]
        results: list[ToolMessage] = []
        reflections = dict(state.get("reflections") or {})

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
            _emit(
                {
                    "event": "tool_start",
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                }
            )
            interrupted = False
            ok = True
            if name not in allowed:
                ok = False
                content = json.dumps(
                    {
                        "status": "error",
                        "code": "TOOL_NOT_ALLOWED",
                        "message": f"当前意图 {intent} 不允许调用 {name}",
                    },
                    ensure_ascii=False,
                )
            else:
                try:
                    content = await execute_tool(name, arguments, context)
                except ApprovalRequiredError as exc:
                    interrupted = True
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
                except Exception as exc:
                    logger.exception("langgraph tool execution crashed", extra={"ctx_tool": name})
                    ok = False
                    content = json.dumps(
                        {"status": "error", "message": str(exc)}, ensure_ascii=False
                    )

            if not interrupted:
                content, reflections[name] = inject_reflection(
                    content,
                    tool=name,
                    arguments=arguments,
                    attempt=reflections.get(name, 0),
                )
                ok = not is_error_result(content)
                _emit({"event": "tool_end", "name": name, "ok": ok})
            results.append(ToolMessage(content=content, tool_call_id=tool_call_id))
        return {"messages": results, "reflections": reflections}

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
        last_user = next(
            (
                str(item.get("content") or "")
                for item in reversed(messages)
                if item.get("role") == "user"
            ),
            "",
        )
        decision = classify_intent(last_user)
        yield AgentEvent("intent", {"intent": decision.intent, "tools": list(decision.tools)})
        payload: dict[str, Any] = (
            {
                "messages": [HumanMessage(content=str(messages[-1]["content"]))],
                "user_id": user_id,
                "intent": decision.intent,
            }
            if has_history and messages
            else {
                "messages": _to_langchain(messages),
                "user_id": user_id,
                "steps": 0,
                "intent": decision.intent,
            }
        )

        async for mode, data in self.graph.astream(
            payload, config=config, stream_mode=["messages", "custom"]
        ):
            if cancel_event is not None and cancel_event.is_set():
                yield AgentEvent("aborted", {"reason": "client_disconnected"})
                return
            if mode == "custom":
                event = _custom_event(data)
                if event is not None:
                    yield event
                continue
            chunk, metadata = data
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

        async for mode, data in self.graph.astream(
            Command(resume=decision), config=config, stream_mode=["messages", "custom"]
        ):
            if mode == "custom":
                event = _custom_event(data)
                if event is not None:
                    yield event
                continue
            chunk, metadata = data
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

    # ------------------------------------------------------------ time travel
    async def history(self, *, thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """List checkpoints for a conversation (newest first)."""

        config = {"configurable": {"thread_id": thread_id}}
        snapshots: list[dict[str, Any]] = []
        async for snapshot in self.graph.aget_state_history(config, limit=limit):
            snapshots.append(_snapshot_summary(snapshot))
        return snapshots

    async def rollback(self, *, thread_id: str, checkpoint_id: str) -> dict[str, Any]:
        """Fork the conversation from a historical checkpoint.

        LangGraph checkpoints are immutable, so a "rollback" writes a new
        checkpoint whose state is a copy of the chosen one; subsequent runs
        continue from the restored messages.  Returns a summary instead of the
        whole state (messages can be large).
        """

        config = {"configurable": {"thread_id": thread_id}}
        target: Any | None = None
        async for snapshot in self.graph.aget_state_history(config):
            current = str(snapshot.config.get("configurable", {}).get("checkpoint_id") or "")
            if current == checkpoint_id:
                target = snapshot
                break
        if target is None:
            raise ConflictError(
                "找不到指定的 checkpoint",
                details={"thread_id": thread_id, "checkpoint_id": checkpoint_id},
            )

        messages = list(target.values.get("messages", []))
        update: dict[str, Any] = {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages],
            "steps": int(target.values.get("steps", 0)),
        }
        if "user_id" in target.values:
            update["user_id"] = int(target.values.get("user_id") or 0)
        # ``as_node`` tells LangGraph which node "produced" the restored state:
        # for a non-empty history continue from the chatbot, for the initial
        # empty checkpoint restart from START (otherwise routing sees no message).
        await self.graph.aupdate_state(
            target.config, update, as_node="chatbot" if messages else START
        )
        return {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "messages": len(messages),
            "restored": True,
        }

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


def _emit(payload: dict[str, Any]) -> None:
    """Emit a custom stream event (no-op when called outside ``astream``)."""

    try:
        writer = get_stream_writer()
    except Exception:  # pragma: no cover - only outside a stream context
        return
    writer(payload)


def _custom_event(data: Any) -> AgentEvent | None:
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    if event == "tool_start":
        return AgentEvent(
            "tool_start",
            {"name": str(data.get("name", "")), "arguments": str(data.get("arguments", ""))},
        )
    if event == "tool_end":
        return AgentEvent(
            "tool_end", {"name": str(data.get("name", "")), "ok": bool(data.get("ok"))}
        )
    return None


def _snapshot_summary(snapshot: Any) -> dict[str, Any]:
    configurable = snapshot.config.get("configurable", {})
    metadata = snapshot.metadata or {}
    return {
        "checkpoint_id": configurable.get("checkpoint_id"),
        "created_at": snapshot.created_at,
        "step": metadata.get("step"),
        "next": list(snapshot.next or []),
        "message_count": len(snapshot.values.get("messages", [])),
    }


__all__ = [
    "AgentState",
    "LangGraphAgentRuntime",
    "build_chat_model",
]
