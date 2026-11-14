"""AI chat endpoints: SSE streaming with idempotency, replay and approvals."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from src.app.core.exceptions import ValidationError
from src.app.modules.chat.service import (
    ChatRequestContext,
    ChatService,
    validate_idempotency_key,
)
from src.app.shared.deps import (
    CurrentUser,
    OptionalUser,
    SessionDep,
    get_chat_service,
    rate_limit,
)

router = APIRouter(prefix="/items/ai", tags=["ai"])

_MAX_MESSAGE_CHARS = 4000


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(default="", max_length=_MAX_MESSAGE_CHARS)


class ChatRequestIn(BaseModel):
    """Accepts both the new and the legacy body shapes."""

    model_config = ConfigDict(extra="ignore")

    message: str | None = Field(default=None, max_length=_MAX_MESSAGE_CHARS)
    content: str | None = Field(default=None, max_length=_MAX_MESSAGE_CHARS)
    messages: list[ChatMessageIn] | None = None
    history: list[ChatMessageIn] | None = None
    thread_id: str | None = Field(default=None, max_length=64)

    def resolve_message(self) -> str:
        for candidate in (self.message, self.content):
            if candidate and candidate.strip():
                return candidate.strip()
        for collection in (self.messages, self.history):
            if collection:
                for item in reversed(collection):
                    if item.role == "user" and item.content.strip():
                        return item.content.strip()
        raise ValidationError("请提供 message 内容")


class ResumeRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    approval_id: int | None = Field(default=None, ge=1)
    comment: str | None = Field(default=None, max_length=500)


def _thread_id(payload: ChatRequestIn, header_value: str | None, user_id: int) -> str:
    candidate = (header_value or payload.thread_id or "").strip()
    if not candidate:
        return f"u{user_id}:main"
    if len(candidate) > 64 or not all(char.isalnum() or char in "-_:." for char in candidate):
        raise ValidationError("thread id 格式不合法", details={"thread_id": candidate[:64]})
    return candidate


@router.post(
    "/agent",
    summary="Chat with the agent (SSE, legacy path)",
    response_class=StreamingResponse,
)
@router.post(
    "/agent/stream",
    summary="Chat with the agent (SSE)",
    response_class=StreamingResponse,
)
async def chat_stream(
    request: Request,
    payload: ChatRequestIn,
    user: CurrentUser,
    service: ChatService = Depends(get_chat_service),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_thread_id: str | None = Header(default=None, alias="X-Thread-ID"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    _: None = Depends(rate_limit("chat", limit=20, window_seconds=60)),
) -> StreamingResponse:
    settings = request.app.state.settings
    if not x_idempotency_key and settings.IDEMPOTENCY_HEADER_REQUIRED:
        raise ValidationError(
            "AI 对话必须携带 X-Idempotency-Key", details={"header": "X-Idempotency-Key"}
        )
    ctx = ChatRequestContext(
        user=user,
        thread_id=_thread_id(payload, x_thread_id, user.id),
        idempotency_key=validate_idempotency_key(x_idempotency_key),
        message=payload.resolve_message(),
    )
    run = await service.handle_stream(
        ctx,
        last_event_id=last_event_id,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(run.events, media_type=run.media_type, headers=run.headers)


@router.get("/history", summary="Chat history")
@router.get("/history/", include_in_schema=False)
async def get_ai_history(
    user: OptionalUser,
    service: ChatService = Depends(get_chat_service),
    skip: int = 0,
    limit: int = 20,
    thread_id: str | None = None,
) -> list[dict[str, object]]:
    if user is None:
        return []
    return await service.history(user, skip=skip, limit=limit, thread_id=thread_id)


@router.delete("/history", summary="Clear chat history")
@router.delete("/history/", include_in_schema=False)
async def delete_ai_history(
    user: CurrentUser,
    service: ChatService = Depends(get_chat_service),
    thread_id: str | None = None,
) -> dict[str, object]:
    deleted = await service.clear_history(user, thread_id=thread_id)
    return {"message": "历史记忆已清除", "deleted": deleted}


@router.get("/threads/{thread_id}/status", summary="Thread status / pending approvals")
async def get_thread_status(
    thread_id: str,
    user: CurrentUser,
    service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    return await service.thread_status(user, thread_id)


@router.post("/threads/{thread_id}/resume", summary="Approve or reject a suspended action")
async def resume_thread(
    request: Request,
    thread_id: str,
    payload: ResumeRequestIn,
    user: CurrentUser,
    service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    return await service.resume(
        user,
        thread_id,
        approved=payload.approved,
        approval_id=payload.approval_id,
        comment=payload.comment,
        dispatcher=request.app.state.container.dispatcher,
    )


@router.get("/approvals", summary="Pending approvals for the current user")
async def list_approvals(user: CurrentUser, session: SessionDep) -> list[dict[str, object]]:
    from src.app.modules.chat import approvals

    pending = await approvals.list_pending(session, user_id=user.id)
    return [approvals.serialize(item) for item in pending]


__all__ = ["router"]
