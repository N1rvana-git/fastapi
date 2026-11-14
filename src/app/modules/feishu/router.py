"""Feishu integration endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from src.app.core.logging import get_logger
from src.app.core.security import verify_shared_secret
from src.app.modules.users import service as users_service
from src.app.shared.deps import CurrentUser, SessionDep

logger = get_logger(__name__)

router = APIRouter(prefix="/feishu", tags=["feishu"])


class BindFeishuRequest(BaseModel):
    open_id: str = Field(min_length=3, max_length=128)


@router.post("/bind", summary="Bind a Feishu open_id to the current account")
async def bind_feishu_account(
    payload: BindFeishuRequest,
    session: SessionDep,
    user: CurrentUser,
) -> dict[str, str]:
    await users_service.bind_feishu_account(session, user, payload.open_id)
    return {"message": "飞书账号绑定成功"}


@router.post("/webhook", summary="Feishu event subscription endpoint")
async def feishu_webhook(request: Request) -> Any:
    try:
        payload: dict[str, Any] = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(content={"error": "invalid json"}, status_code=400)

    # URL verification handshake (Feishu sends challenge before any event).
    if payload.get("type") == "url_verification" or "challenge" in payload:
        return {"challenge": payload.get("challenge")}

    settings = request.app.state.settings
    token = payload.get("token") or (payload.get("header") or {}).get("token")
    if not verify_shared_secret(settings.FEISHU_VERIFICATION_TOKEN, token):
        logger.warning("feishu webhook rejected: bad verification token")
        return JSONResponse(content={"error": "forbidden"}, status_code=403)

    header = payload.get("header") or {}
    if header.get("event_type") != "im.message.receive_v1":
        return {"msg": "ignored"}

    event = payload.get("event") or {}
    dispatcher = request.app.state.container.dispatcher
    # Acknowledge fast; the LLM turn runs on the task queue (retried on failure).
    await dispatcher.enqueue("feishu.process_event", event=event)
    return {"msg": "ok"}


__all__ = ["router"]
