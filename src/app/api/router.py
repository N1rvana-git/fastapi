"""API composition: the only place that knows the full route table."""

from __future__ import annotations

from fastapi import APIRouter

from src.app.api import health
from src.app.modules.auth.router import router as auth_router
from src.app.modules.chat.router import router as chat_router
from src.app.modules.feishu.router import router as feishu_router
from src.app.modules.items.router import router as items_router
from src.app.modules.users.router import router as users_router


def build_router() -> APIRouter:
    api = APIRouter()
    api.include_router(health.router)
    api.include_router(auth_router)
    api.include_router(users_router)
    api.include_router(items_router)
    api.include_router(chat_router)
    api.include_router(feishu_router)
    return api


__all__ = ["build_router"]
