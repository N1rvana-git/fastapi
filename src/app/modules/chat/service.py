"""Chat orchestration: idempotent runs, detached worker, replayable SSE.

Flow (see the architecture doc for the diagram):

    POST /agent ──► claim idempotency key ──► already running? attach
                              │
                              └─ new: persist user msg, spawn worker, return stream
    worker ──► thread lock ──► agent runtime ──► buffer.append(event)
    stream ──► buffer.read(after=Last-Event-ID) ──► HTTP frames + heartbeats

The HTTP handler never holds a database session: the worker opens short-lived
ones.  A 30-second LLM turn therefore uses zero pool connections while idle,
which is the pool-exhaustion fix the PDF describes.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, desc, select

from src.app.core.config import Settings
from src.app.core.context import context_snapshot, restored_context
from src.app.core.database import Database
from src.app.core.exceptions import ConflictError, ValidationError
from src.app.core.idempotency import (
    IdempotencyOutcome,
    IdempotencyRecord,
    IdempotencyStore,
    body_fingerprint,
)
from src.app.core.logging import get_logger, log_extra
from src.app.modules.chat import approvals
from src.app.modules.chat.models import ChatRecord
from src.app.modules.chat.prompts import build_system_prompt
from src.app.modules.chat.stream import (
    SSE_HEADERS,
    StreamBuffer,
    ThreadLockManager,
    sse_frame,
)
from src.app.modules.chat.stream_runtime import AgentRuntime
from src.app.modules.users.models import UserModel

logger = get_logger(__name__)

_TERMINAL_EVENTS = frozenset({"done", "error", "aborted", "interrupt_required"})

#: Injected by the HTTP layer so the service can detect a gone client without
#: knowing anything about Starlette/FastAPI request objects.
DisconnectCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class ChatRun:
    """Transport-agnostic description of an SSE response.

    The router wraps ``events`` in ``StreamingResponse``; the service only knows
    about bytes frames and headers, which keeps the FastAPI boundary in the
    router (ARCHITECTURE.md section 2).
    """

    events: AsyncIterator[str]
    headers: dict[str, str]
    media_type: str = "text/event-stream"


@dataclass(frozen=True)
class ChatDeps:
    settings: Settings
    database: Database
    runtime: AgentRuntime
    buffer: StreamBuffer
    locks: ThreadLockManager
    idempotency: IdempotencyStore


@dataclass
class ChatRequestContext:
    user: UserModel
    thread_id: str
    idempotency_key: str
    message: str


@dataclass
class ChatService:
    deps: ChatDeps
    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _cancellations: dict[str, asyncio.Event] = field(default_factory=dict)

    # ------------------------------------------------------------------ reads
    async def history(
        self, user: UserModel, *, skip: int = 0, limit: int = 20, thread_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with self.deps.database.session() as session:
            stmt = select(ChatRecord).where(ChatRecord.user_id == user.id)
            if thread_id:
                stmt = stmt.where(ChatRecord.thread_id == thread_id)
            stmt = (
                stmt.order_by(desc(ChatRecord.created_at), desc(ChatRecord.id))
                .offset(skip)
                .limit(limit)
            )
            records = list((await session.execute(stmt)).scalars().all())
        records.reverse()
        return [
            {
                "role": record.role,
                "content": record.content,
                "timestamp": record.created_at.isoformat() if record.created_at else None,
                "thread_id": record.thread_id,
            }
            for record in records
        ]

    async def clear_history(self, user: UserModel, *, thread_id: str | None = None) -> int:
        async with self.deps.database.session() as session:
            stmt = delete(ChatRecord).where(ChatRecord.user_id == user.id)
            if thread_id:
                stmt = stmt.where(ChatRecord.thread_id == thread_id)
            result = await session.execute(stmt)
            await session.commit()
        deleted = int(result.rowcount or 0)
        logger.info(
            "chat history cleared", extra=log_extra(event="chat_history_cleared", deleted=deleted)
        )
        return deleted

    async def thread_status(self, user: UserModel, thread_id: str) -> dict[str, Any]:
        async with self.deps.database.session() as session:
            pending = await approvals.list_pending(session, thread_id, user_id=user.id)
            recent = list(
                (
                    await session.execute(
                        select(ChatRecord)
                        .where(ChatRecord.user_id == user.id, ChatRecord.thread_id == thread_id)
                        .order_by(desc(ChatRecord.id))
                        .limit(1)
                    )
                )
                .scalars()
                .all()
            )
            all_pending = await approvals.list_pending(session, thread_id)

        latest = recent[0] if recent else None
        return {
            "thread_id": thread_id,
            "is_interrupted": bool(all_pending),
            "pending_approvals": [approvals.serialize(item) for item in pending],
            "last_message_at": latest.created_at.isoformat()
            if latest and latest.created_at
            else None,
            "last_role": latest.role if latest else None,
        }

    async def resume(
        self,
        user: UserModel,
        thread_id: str,
        *,
        approved: bool,
        approval_id: int | None = None,
        comment: str | None = None,
        dispatcher: Any | None = None,
    ) -> dict[str, Any]:
        async with self.deps.database.session() as session:
            target_id = approval_id
            if target_id is None:
                pending = await approvals.list_pending(session, thread_id, user_id=user.id)
                if not pending:
                    raise ConflictError(
                        "当前会话没有待审批的挂起操作", details={"thread_id": thread_id}
                    )
                target_id = pending[0].id
            decision = await approvals.decide(
                session,
                approval_id=target_id,
                approve=approved,
                actor=user,
                comment=comment,
                settings=self.deps.settings,
                dispatcher=dispatcher,
            )

        fallback = (
            f"人工审核已通过，订单 #{decision.order_id} 已创建。"
            if approved and decision.order_id
            else "人工审核未通过，本次操作已取消。"
        )
        content = await self._resume_agent(thread_id, decision, approved=approved, comment=comment)
        async with self.deps.database.session() as session:
            await self._append_message(
                session,
                user_id=user.id,
                thread_id=thread_id,
                role="assistant",
                content=(content or fallback)[:8000],
            )

        logger.info(
            "approval decided",
            extra=log_extra(
                event="approval_decided",
                thread_id=thread_id,
                approved=approved,
                approval_id=target_id,
            ),
        )
        return {
            "status": decision.status,
            "approval_id": decision.approval_id,
            "thread_id": decision.thread_id,
            "order_id": decision.order_id,
        }

    # ------------------------------------------------------------------ non-stream
    async def complete(self, user: UserModel, *, thread_id: str, message: str) -> str:
        """Collect a full answer (Feishu has no streaming transport).

        Shares the same runtime, tools, approvals and persistence as the SSE
        path, so both channels behave identically.
        """

        async with self.deps.locks.hold(thread_id, f"sync:{thread_id}") as acquired:
            if not acquired:
                return "上一条消息还在处理中，请稍候再发一次～"

            async with self.deps.database.session() as session:
                await self._append_message(
                    session, user_id=user.id, thread_id=thread_id, role="user", content=message
                )

            messages = await self._build_messages(
                ChatRequestContext(
                    user=user, thread_id=thread_id, idempotency_key="sync", message=message
                )
            )
            parts: list[str] = []
            async for event in self.deps.runtime.run(
                user_id=user.id,
                user_name=user.username,
                thread_id=thread_id,
                messages=messages,
                cancel_event=asyncio.Event(),
            ):
                if event.type == "token":
                    parts.append(str(event.data.get("text", "")))
                elif event.type == "interrupt_required":
                    parts.append(str(event.data.get("message", "")))
                elif event.type == "error":
                    parts.append(str(event.data.get("message", "AI 服务暂时不可用")))

            reply = "".join(parts).strip() or "抱歉，我暂时没能理解您的需求，可以再描述一下吗？"
            async with self.deps.database.session() as session:
                await self._append_message(
                    session,
                    user_id=user.id,
                    thread_id=thread_id,
                    role="assistant",
                    content=reply[:8000],
                )
            return reply

    # ------------------------------------------------------------------ stream
    async def handle_stream(
        self,
        ctx: ChatRequestContext,
        *,
        last_event_id: str | None = None,
        is_disconnected: DisconnectCheck | None = None,
    ) -> ChatRun:
        settings = self.deps.settings
        run_key = f"chat:{ctx.user.id}:{ctx.idempotency_key}"
        outcome, _ = await self.deps.idempotency.begin(
            run_key,
            fingerprint=body_fingerprint(ctx.thread_id, ctx.message),
            ttl=settings.AGENT_STREAM_TTL_SECONDS,
            pending_ttl=settings.AGENT_STREAM_TTL_SECONDS,
        )
        if outcome is IdempotencyOutcome.MISMATCH:
            raise ConflictError(
                "同一个幂等键不能用于不同的消息",
                details={"idempotency_key": ctx.idempotency_key},
            )

        if outcome is IdempotencyOutcome.STARTED:
            await self._start_run(ctx, run_key)

        logger.info(
            "chat stream attached",
            extra=log_extra(
                event="chat_stream_attached",
                thread_id=ctx.thread_id,
                outcome=outcome.value,
                user_id=ctx.user.id,
            ),
        )
        return ChatRun(
            events=self._event_stream(
                run_key=run_key,
                ctx=ctx,
                is_disconnected=is_disconnected,
                last_event_id=last_event_id,
            ),
            headers={
                **SSE_HEADERS,
                "X-Idempotency-Key": ctx.idempotency_key,
                "X-Thread-ID": ctx.thread_id,
            },
        )

    async def _start_run(self, ctx: ChatRequestContext, run_key: str) -> None:
        # Persist the user message *before* starting the worker so history is
        # complete even if the worker crashes immediately.
        async with self.deps.database.session() as session:
            await self._append_message(
                session,
                user_id=ctx.user.id,
                thread_id=ctx.thread_id,
                role="user",
                content=ctx.message,
            )
        snapshot = context_snapshot()
        task = asyncio.create_task(
            self._run_worker(ctx=ctx, run_key=run_key, snapshot=snapshot),
            name=f"chat-run:{ctx.thread_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resume_agent(
        self, thread_id: str, decision: Any, *, approved: bool, comment: str | None
    ) -> str:
        """Let a stateful runtime finish the suspended turn, if it supports it.

        The purchase has already been executed exactly once by
        ``approvals.decide``; the graph only needs the decision to continue the
        conversation, so a runtime failure must not lose the order result.
        """

        resume = getattr(self.deps.runtime, "resume", None)
        if not callable(resume):
            return ""
        parts: list[str] = []
        try:
            async for event in resume(
                thread_id=thread_id,
                decision={
                    "approved": approved,
                    "order_id": getattr(decision, "order_id", None),
                    "comment": comment,
                },
            ):
                if event.type == "token":
                    parts.append(str(event.data.get("text", "")))
                elif event.type == "error":
                    parts.append(str(event.data.get("message", "")))
        except Exception:  # order already persisted above
            logger.exception("failed to resume agent graph", extra=log_extra(thread_id=thread_id))
        return "".join(parts).strip()

    async def _run_worker(
        self, *, ctx: ChatRequestContext, run_key: str, snapshot: dict[str, str]
    ) -> None:
        settings = self.deps.settings
        cancel_event = asyncio.Event()
        self._cancellations[run_key] = cancel_event
        reply_parts: list[str] = []
        interrupted = False
        failed = False

        with restored_context(snapshot):
            try:
                async with self.deps.locks.hold(ctx.thread_id, run_key) as acquired:
                    if not acquired:
                        await self.deps.buffer.append(
                            ctx.thread_id,
                            "error",
                            {
                                "message": "该会话正在处理上一条消息，请稍后再试",
                                "code": "THREAD_BUSY",
                            },
                        )
                        failed = True
                        return

                    messages = await self._build_messages(ctx)
                    async for event in self.deps.runtime.run(
                        user_id=ctx.user.id,
                        user_name=ctx.user.username,
                        thread_id=ctx.thread_id,
                        messages=messages,
                        cancel_event=cancel_event,
                    ):
                        payload = dict(event.data)
                        if event.type == "token":
                            text = str(payload.get("text", ""))
                            reply_parts.append(text)
                            payload.setdefault("content", text)  # legacy SSE contract
                        elif event.type in {"error", "aborted"}:
                            failed = event.type == "error"
                        elif event.type == "interrupt_required":
                            interrupted = True
                            reply_parts.append(str(payload.get("message", "")))
                        await self.deps.buffer.append(ctx.thread_id, event.type, payload)
            except asyncio.CancelledError:
                await self._safe_append(ctx.thread_id, "aborted", {"reason": "server_shutdown"})
                raise
            except Exception as exc:
                logger.exception("chat run crashed", extra=log_extra(thread_id=ctx.thread_id))
                failed = True
                await self._safe_append(
                    ctx.thread_id,
                    "error",
                    {
                        "message": "AI 服务异常，请稍后重试。",
                        "code": "AGENT_FAILED",
                        "reason": type(exc).__name__,
                    },
                )
            finally:
                self._cancellations.pop(run_key, None)

            try:
                reply = "".join(reply_parts).strip()
                if reply:
                    async with self.deps.database.session() as session:
                        await self._append_message(
                            session,
                            user_id=ctx.user.id,
                            thread_id=ctx.thread_id,
                            role="assistant",
                            content=reply[:8000],
                        )
                if failed:
                    # Release the key so the client may retry the same message.
                    await self.deps.idempotency.release(run_key)
                else:
                    await self.deps.idempotency.complete(
                        run_key,
                        IdempotencyRecord(
                            state="completed",
                            status_code=200,
                            body={
                                "thread_id": ctx.thread_id,
                                "reply": reply[:4000],
                                "interrupted": interrupted,
                            },
                            fingerprint=body_fingerprint(ctx.thread_id, ctx.message),
                        ),
                        ttl=settings.AGENT_STREAM_TTL_SECONDS,
                    )
            except Exception:
                logger.exception(
                    "failed to finalize chat run", extra=log_extra(thread_id=ctx.thread_id)
                )

    async def _build_messages(self, ctx: ChatRequestContext) -> list[dict[str, Any]]:
        settings = self.deps.settings
        async with self.deps.database.session() as session:
            stmt = (
                select(ChatRecord)
                .where(ChatRecord.user_id == ctx.user.id, ChatRecord.thread_id == ctx.thread_id)
                .order_by(desc(ChatRecord.id))
                .limit(settings.AGENT_CONTEXT_MESSAGES)
            )
            records = list((await session.execute(stmt)).scalars().all())
        records.reverse()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(ctx.user.username)}
        ]
        for record in records:
            if record.role in {"user", "assistant"} and record.content:
                messages.append({"role": record.role, "content": record.content})
        return messages

    async def _event_stream(
        self,
        *,
        run_key: str,
        ctx: ChatRequestContext,
        is_disconnected: DisconnectCheck | None,
        last_event_id: str | None,
    ) -> AsyncIterator[str]:
        settings = self.deps.settings
        cursor = last_event_id if last_event_id and last_event_id not in {"0", ""} else None
        deadline = time.monotonic() + settings.AGENT_STREAM_TTL_SECONDS
        heartbeat_after = settings.AGENT_STREAM_HEARTBEAT_SECONDS
        last_activity = time.monotonic()

        while time.monotonic() < deadline:
            if await _client_gone(is_disconnected):
                logger.info(
                    "chat client disconnected",
                    extra=log_extra(
                        thread_id=ctx.thread_id, policy=settings.AGENT_DISCONNECT_POLICY
                    ),
                )
                if settings.AGENT_DISCONNECT_POLICY == "abort":
                    cancel_event = self._cancellations.get(run_key)
                    if cancel_event is not None:
                        cancel_event.set()
                return

            entries = await self.deps.buffer.read(ctx.thread_id, cursor, block_ms=1000, count=50)
            if entries:
                for entry in entries:
                    cursor = entry.id
                    yield sse_frame(entry.event, entry.data, event_id=entry.id)
                    if entry.event in _TERMINAL_EVENTS:
                        return
                last_activity = time.monotonic()
                continue

            record = await self.deps.idempotency.get(run_key)
            if record is not None and record.state == "completed":
                if cursor is None:
                    body = record.body if isinstance(record.body, dict) else {}
                    yield sse_frame("done", {"replayed": True, **body})
                return
            if record is None:
                # The run was released (failure) or expired: do not hang forever.
                yield sse_frame(
                    "error",
                    {"message": "本次回答已结束或已过期，请重新发送", "code": "RUN_GONE"},
                )
                return

            if time.monotonic() - last_activity >= heartbeat_after:
                # SSE comment keeps nginx/ALB from closing an idle connection.
                yield ": ping\n\n"
                last_activity = time.monotonic()

        yield sse_frame("error", {"message": "生成超时，请重试", "code": "STREAM_TIMEOUT"})

    # ----------------------------------------------------------------- helpers
    async def _append_message(
        self,
        session: Any,
        *,
        user_id: int,
        thread_id: str,
        role: str,
        content: str,
    ) -> ChatRecord:
        record = ChatRecord(user_id=user_id, thread_id=thread_id, role=role, content=content)
        session.add(record)
        await session.commit()
        # expire_on_commit=False keeps the inserted row usable; calling refresh()
        # here would explode if the session was closed concurrently (seen as a
        # flaky "Could not refresh instance" in the Feishu webhook tests).
        return record

    async def _safe_append(self, thread_id: str, event: str, data: dict[str, Any]) -> None:
        try:
            await self.deps.buffer.append(thread_id, event, data)
        except Exception:
            logger.exception("failed to append stream event", extra=log_extra(thread_id=thread_id))

    async def shutdown(self, *, grace_seconds: float = 10.0) -> None:
        """Drain in-flight runs (graceful shutdown)."""

        if not self._tasks:
            return
        logger.info("draining chat runs", extra=log_extra(count=len(self._tasks)))
        pending = list(self._tasks)
        done, still_running = await asyncio.wait(pending, timeout=grace_seconds)
        for task in still_running:
            task.cancel()
        if still_running:
            await asyncio.wait(still_running, timeout=2.0)
        for task in done | still_running:
            with suppress(asyncio.CancelledError, Exception):
                task.result()


async def _client_gone(check: DisconnectCheck | None) -> bool:
    """Consult the HTTP layer's disconnect probe, tolerating any failure."""

    if check is None:
        return False
    try:
        return bool(await check())
    except Exception:
        # Test transports (and some servers) do not implement is_disconnected.
        return False


def new_thread_id(user_id: int) -> str:
    return f"u{user_id}-{uuid.uuid4().hex[:12]}"


def validate_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        return uuid.uuid4().hex
    cleaned = value.strip()
    if len(cleaned) > 128 or not all(char.isalnum() or char in "-_:" for char in cleaned):
        raise ValidationError(
            "X-Idempotency-Key 格式不合法（1-128 位字母、数字、-_ :）",
            details={"value": cleaned[:64]},
        )
    return cleaned


__all__ = [
    "ChatDeps",
    "ChatRequestContext",
    "ChatRun",
    "ChatService",
    "DisconnectCheck",
    "new_thread_id",
    "validate_idempotency_key",
]
