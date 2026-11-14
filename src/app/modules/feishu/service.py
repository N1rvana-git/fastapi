"""Feishu webhook business logic.

The webhook must answer Feishu within a few seconds, so the event is enqueued on
the async task queue and processed out-of-band (retried on failure).  Everything
downstream - rate limiting, account binding, history, the agent runtime - is the
same code path used by the web UI, so the two channels cannot diverge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.app.core.config import Settings
from src.app.core.database import Database
from src.app.core.idempotency import (
    IdempotencyOutcome,
    IdempotencyRecord,
    body_fingerprint,
)
from src.app.core.logging import get_logger
from src.app.core.ratelimit import RateLimiter
from src.app.modules.chat.service import ChatService
from src.app.modules.feishu.client import FeishuClient
from src.app.modules.users import repository as users_repository
from src.app.modules.users.models import UserModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class FeishuDeps:
    settings: Settings
    database: Database
    chat_service: ChatService
    rate_limiter: RateLimiter
    client: FeishuClient
    idempotency: Any


@dataclass
class FeishuService:
    deps: FeishuDeps

    async def handle_event(self, event: dict[str, Any]) -> None:
        message = event.get("message") or {}
        if message.get("message_type") != "text":
            return
        try:
            content = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError:
            return
        text = str(content.get("text") or "").strip()
        open_id = ((event.get("sender") or {}).get("sender_id") or {}).get("open_id") or ""
        if not text or not open_id:
            return

        # Feishu retries the webhook when it does not get a fast ACK; message_id
        # is stable across retries, so it is the natural idempotency key.
        message_id = str(message.get("message_id") or "")
        run_key = f"feishu:{message_id}" if message_id else ""
        store = self.deps.idempotency
        if run_key:
            outcome, _ = await store.begin(
                run_key,
                fingerprint=body_fingerprint(text),
                ttl=3600,
                pending_ttl=300,
            )
            if outcome is not IdempotencyOutcome.STARTED:
                logger.info(
                    "feishu duplicate event ignored",
                    extra={"ctx_message_id": message_id, "ctx_outcome": outcome.value},
                )
                return

        try:
            await self._handle_text(text=text, open_id=open_id)
        except Exception:
            if run_key:
                await store.release(run_key)  # allow the retry to reprocess
            raise
        else:
            if run_key:
                await store.complete(
                    run_key,
                    IdempotencyRecord(state="completed", status_code=200, body={"ok": True}),
                    ttl=3600,
                )

    async def _handle_text(self, *, text: str, open_id: str) -> None:
        logger.info(
            "feishu message received",
            extra={"ctx_open_id": open_id, "ctx_chars": len(text)},
        )

        if not await self._allow(open_id):
            await self.deps.client.send_text(open_id, "🛑 老板，您的手速太快了，请休息一分钟再聊～")
            return

        async with self.deps.database.session() as session:
            user = await users_repository.get_by_feishu_open_id(session, open_id)
            if user is None:
                bind_url = f"{self.deps.settings.FEISHU_BIND_URL_BASE}?open_id={open_id}"
                await self.deps.client.send_text(
                    open_id,
                    "老板你好！我是闲小宝。您的飞书还没绑定平台账号，请先点这里绑定：\n"
                    f"{bind_url}\n绑定后我才能帮您查商品、下单哦！",
                )
                return
            if text == "/del texts":
                deleted = await self.deps.chat_service.clear_history(user)
                logger.info(
                    "feishu history cleared", extra={"ctx_user_id": user.id, "ctx_deleted": deleted}
                )
                await self.deps.client.send_text(open_id, "✅ 历史聊天记录已清除，我们重新开始吧！")
                return

            reply = await self.deps.chat_service.complete(
                user, thread_id=f"u{user.id}:feishu", message=text
            )
        await self.deps.client.send_text(open_id, reply)

    async def _allow(self, open_id: str) -> bool:
        if not self.deps.settings.RATE_LIMIT_ENABLED:
            return True
        result = await self.deps.rate_limiter.hit(
            f"feishu:{open_id}",
            limit=self.deps.settings.FEISHU_RATE_LIMIT_PER_MINUTE,
            window_seconds=60,
        )
        return result.allowed

    async def notify_order(
        self,
        *,
        item_id: int,
        buyer_id: int,
        address: str,
        quantity: int,
    ) -> None:
        """Send an order alert to whoever is reachable (seller first, then buyer)."""

        async with self.deps.database.session() as session:
            from src.app.modules.items import repository as items_repository

            item = await items_repository.get_by_id(session, item_id)
            buyer = await session.get(UserModel, buyer_id)
            seller = await session.get(UserModel, item.owner_id) if item and item.owner_id else None
        if item is None:
            return

        text = (
            f"🎉 新订单提醒\n商品：{item.name}\n单价：￥{item.price:.2f} x{quantity}\n"
            f"买家：{(buyer.email if buyer else '未知')}\n收货地址：{address or '未填写'}"
        )
        for candidate in (seller, buyer):
            if (
                candidate is not None
                and candidate.feishu_open_id
                and await self.deps.client.send_text(candidate.feishu_open_id, text)
            ):
                return
        logger.info("order alert has no Feishu recipient", extra={"ctx_item_id": item_id})


__all__ = ["FeishuDeps", "FeishuService"]
