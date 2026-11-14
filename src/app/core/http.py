"""HTTP client lifecycle.

One ``httpx.AsyncClient`` per upstream, created in the lifespan, reused for every
request.  Creating a client per call (the old code did this in the Feishu
webhook) throws away connection pooling and TLS sessions, which is exactly the
kind of latency the PDF calls out.
"""

from __future__ import annotations

import httpx

from src.app.core.config import Settings
from src.app.core.logging import get_logger

logger = get_logger(__name__)


class HttpClientPool:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._clients: dict[str, httpx.AsyncClient] = {}

    def _timeout(self, read: float | None = None) -> httpx.Timeout:
        s = self.settings
        return httpx.Timeout(
            connect=s.HTTP_CONNECT_TIMEOUT,
            read=read or s.HTTP_READ_TIMEOUT,
            write=s.HTTP_WRITE_TIMEOUT,
            pool=s.HTTP_POOL_TIMEOUT,
        )

    def _limits(self) -> httpx.Limits:
        s = self.settings
        return httpx.Limits(
            max_connections=s.HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=s.HTTP_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=30.0,
        )

    def client(
        self,
        name: str = "default",
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        read_timeout: float | None = None,
    ) -> httpx.AsyncClient:
        key = f"{name}:{base_url}"
        existing = self._clients.get(key)
        if existing is not None and not existing.is_closed:
            return existing
        client = httpx.AsyncClient(
            base_url=base_url or "",
            headers=headers,
            timeout=self._timeout(read_timeout),
            limits=self._limits(),
            follow_redirects=False,
            trust_env=False,
        )
        self._clients[key] = client
        return client

    async def close(self) -> None:
        for key, client in list(self._clients.items()):
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - best effort
                logger.debug("failed closing http client %s", key)
        self._clients.clear()
        logger.info("http clients closed")


__all__ = ["HttpClientPool"]
