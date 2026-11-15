"""Agent runtime: a bounded tool-calling loop over the async LLM gateway.

This is the default runtime (``AGENT_RUNTIME=native``).  It is deliberately
explicit about its state machine, because that is what makes the SSE layer and
the approval flow predictable:

    LLM step -> (text deltas streamed to the client)
             -> tool calls? -> execute tools -> feed results back -> next step
             -> approval required? -> persist approval, emit interrupt, stop
             -> no tool calls -> done

Guarantees:

* at most ``AGENT_MAX_STEPS`` upstream calls per turn (no runaway agent loops);
* cooperative cancellation checked before every step and every tool;
* tool results are bounded (see ``tools._truncate``);
* an approval request never blocks a worker - it is persisted and the turn ends.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from src.app.core.exceptions import ApprovalRequiredError
from src.app.core.logging import get_logger
from src.app.modules.chat import approvals
from src.app.modules.chat.intent import classify_intent
from src.app.modules.chat.llm_gateway import LLMGateway
from src.app.modules.chat.reflection import inject_reflection, is_error_result
from src.app.modules.chat.tools import ToolContext, ToolDeps, execute_tool, openai_tools

logger = get_logger(__name__)

AgentEventType = Literal[
    "intent",
    "token",
    "tool_start",
    "tool_end",
    "interrupt_required",
    "done",
    "error",
    "aborted",
]


@dataclass
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)


class AgentRuntime(Protocol):
    # NOTE: a non-async ``def`` returning an AsyncIterator is the correct way to
    # type an async-generator implementation; ``async def`` would make callers
    # see a coroutine and fail to iterate it.
    def run(
        self,
        *,
        user_id: int,
        user_name: str,
        thread_id: str,
        messages: list[dict[str, Any]],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]: ...


@dataclass
class NativeAgentRuntime:
    gateway: LLMGateway
    deps: ToolDeps
    max_steps: int = 6
    context_messages: int = 8

    async def run(
        self,
        *,
        user_id: int,
        user_name: str,
        thread_id: str,
        messages: list[dict[str, Any]],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]:
        working: list[dict[str, Any]] = list(messages[-self.context_messages :])
        last_user = next(
            (
                str(item.get("content") or "")
                for item in reversed(working)
                if item.get("role") == "user"
            ),
            "",
        )
        decision = classify_intent(last_user)
        yield AgentEvent("intent", {"intent": decision.intent, "tools": list(decision.tools)})
        retry_counts: dict[str, int] = {}

        for step in range(1, self.max_steps + 1):
            if cancel_event.is_set():
                yield AgentEvent("aborted", {"reason": "client_disconnected"})
                return

            tool_calls = []
            try:
                async for event in self.gateway.stream_chat(
                    working,
                    tools=openai_tools(decision.tools) if decision.tools else None,
                    cancel_event=cancel_event,
                ):
                    if event.type == "text" and event.text:
                        yield AgentEvent("token", {"text": event.text})
                    elif event.type == "tool_calls":
                        tool_calls = event.tool_calls
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Never leak upstream/provider details to the end user; the full
                # exception is in the server log with the request trace id.
                logger.exception("agent llm step failed", extra={"ctx_thread_id": thread_id})
                yield AgentEvent(
                    "error",
                    {
                        "message": "AI 服务暂时不可用，请稍后再试。",
                        "code": "UPSTREAM_UNAVAILABLE",
                        "reason": type(exc).__name__,
                    },
                )
                return

            if cancel_event.is_set():
                yield AgentEvent("aborted", {"reason": "client_disconnected"})
                return

            if not tool_calls:
                yield AgentEvent("done", {"steps": step})
                return

            working.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                        for call in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                if cancel_event.is_set():
                    yield AgentEvent("aborted", {"reason": "client_disconnected"})
                    return
                yield AgentEvent(
                    "tool_start", {"name": call.name, "arguments": _safe_json(call.arguments)}
                )
                arguments: dict[str, Any] = {}
                try:
                    parsed = json.loads(call.arguments or "{}")
                    if not isinstance(parsed, dict):
                        raise ValueError("tool arguments must be a JSON object")
                    arguments = parsed
                    result = await execute_tool(
                        call.name,
                        arguments,
                        ToolContext(
                            deps=self.deps,
                            user_id=user_id,
                            thread_id=thread_id,
                            tool_call_id=call.id,
                        ),
                    )
                except ApprovalRequiredError as exc:
                    approval = await _persist_approval(
                        self.deps,
                        thread_id=thread_id,
                        user_id=user_id,
                        action=call.name,
                        details=exc.details,
                        reason=exc.message,
                    )
                    message = (
                        f"这笔订单金额（￥{exc.details.get('amount', 0):.2f}）超过了自动授权额度，"
                        "已提交人工审核。审核通过后会立即为您下单，请稍候。"
                    )
                    yield AgentEvent(
                        "interrupt_required",
                        {
                            "approval_id": approval.id,
                            "thread_id": thread_id,
                            "action": approval.action,
                            "reason": approval.reason,
                            "expires_at": approval.expires_at.isoformat()
                            if approval.expires_at
                            else None,
                            "payload": exc.details,
                            "message": message,
                        },
                    )
                    yield AgentEvent("done", {"interrupted": True})
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("tool execution crashed", extra={"ctx_tool": call.name})
                    result = json.dumps(
                        {"status": "error", "message": str(exc)}, ensure_ascii=False
                    )

                working.append({"role": "tool", "tool_call_id": call.id, "content": result})
                augmented, retry_counts[call.name] = inject_reflection(
                    result,
                    tool=call.name,
                    arguments=arguments,
                    attempt=retry_counts.get(call.name, 0),
                )
                working[-1]["content"] = augmented
                yield AgentEvent(
                    "tool_end",
                    {"name": call.name, "ok": not is_error_result(augmented)},
                )

        logger.warning("agent hit max steps", extra={"ctx_thread_id": thread_id})
        yield AgentEvent(
            "error",
            {"message": "这个需求有点复杂，我先为您转接人工客服，请稍等。"},
        )


async def _persist_approval(
    deps: ToolDeps,
    *,
    thread_id: str,
    user_id: int,
    action: str,
    details: dict[str, Any],
    reason: str,
) -> Any:
    async with deps.database.session() as session:
        return await approvals.request_approval(
            session,
            thread_id=thread_id,
            user_id=user_id,
            action=action,
            payload=details,
            reason=reason,
            settings=deps.settings,
        )


def _safe_json(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw[:200]}


__all__ = ["AgentEvent", "AgentEventType", "AgentRuntime", "NativeAgentRuntime"]
