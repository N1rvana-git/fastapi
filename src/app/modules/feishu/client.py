"""Feishu (Lark) API client with tenant-token caching.

``tenant_access_token`` is valid for ~2 hours; the old code fetched a new one for
*every* outbound message.  Here it is cached (local + Redis) and reused, and all
calls share the process HTTP pool with explicit timeouts and bounded retries.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from src.app.core.cache import TwoLevelCache
from src.app.core.config import Settings
from src.app.core.exceptions import DependencyUnavailableError, FeatureUnavailableError
from src.app.core.http import HttpClientPool
from src.app.core.logging import get_logger
from src.app.core.retry import retry_async

logger = get_logger(__name__)

_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)
_TOKEN_CACHE_KEY = "feishu:tenant_token"
_TOKEN_TTL_SECONDS = 90 * 60


class FeishuClient:
    def __init__(self, settings: Settings, http_pool: HttpClientPool, cache: TwoLevelCache) -> None:
        self.settings = settings
        self.http_pool = http_pool
        self.cache = cache
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.settings.FEISHU_APP_ID and self.settings.FEISHU_APP_SECRET)

    def _client(self) -> httpx.AsyncClient:
        return self.http_pool.client(
            "feishu",
            base_url=self.settings.FEISHU_BASE_URL,
            read_timeout=self.settings.FEISHU_TIMEOUT_SECONDS,
        )

    async def tenant_token(self, *, refresh: bool = False) -> str:
        if not self.configured:
            raise FeatureUnavailableError("飞书应用未配置 (FEISHU_APP_ID / FEISHU_APP_SECRET)")
        if not refresh:
            cached = await self.cache.get(_TOKEN_CACHE_KEY)
            if isinstance(cached, str) and cached:
                return cached
        async with self._token_lock:
            if not refresh:
                cached = await self.cache.get(_TOKEN_CACHE_KEY)
                if isinstance(cached, str) and cached:
                    return cached
            client = self._client()
            response = await retry_async(
                lambda: client.post(
                    "/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.settings.FEISHU_APP_ID,
                        "app_secret": self.settings.FEISHU_APP_SECRET,
                    },
                ),
                attempts=2,
                retry_on=_RETRYABLE,
            )
            payload: dict[str, Any] = response.json()
            token = payload.get("tenant_access_token")
            if not token:
                raise DependencyUnavailableError(
                    "飞书 token 获取失败",
                    details={"code": payload.get("code"), "msg": payload.get("msg")},
                )
            await self.cache.set(_TOKEN_CACHE_KEY, token, _TOKEN_TTL_SECONDS)
            return str(token)

    async def send_text(self, open_id: str, text: str) -> bool:
        if not open_id:
            logger.warning("feishu send skipped: empty open_id")
            return False
        try:
            token = await self.tenant_token()
        except Exception as exc:
            logger.warning("feishu send skipped: %s", exc)
            return False
        client = self._client()

        async def call() -> bool:
            response = await client.post(
                "/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": open_id,
                    "msg_type": "text",
                    "content": __import__("json").dumps({"text": text}, ensure_ascii=False),
                },
            )
            payload = response.json()
            if payload.get("code") not in (0, None):
                raise DependencyUnavailableError(
                    "飞书消息发送失败",
                    details={"code": payload.get("code"), "msg": payload.get("msg")},
                )
            return True

        try:
            return await retry_async(
                call, attempts=3, retry_on=_RETRYABLE + (DependencyUnavailableError,)
            )
        except Exception:
            logger.exception("feishu send failed", extra={"ctx_open_id": open_id})
            return False


__all__ = ["FeishuClient"]
