"""Composition root: builds and owns every long-lived resource.

Nothing else in the codebase instantiates engines, HTTP clients, Redis
connections or the agent runtime.  ``AppContainer`` is created once per process
in the FastAPI lifespan and exposed via ``app.state.container``, which makes
tests trivial (build a container with test settings and override it) and
prevents the "import-time side effects" that previously loaded a 600 MB vision
model before the first request.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from src.app.core.cache import TwoLevelCache
from src.app.core.config import Settings
from src.app.core.database import Database
from src.app.core.http import HttpClientPool
from src.app.core.idempotency import IdempotencyStore, build_idempotency_store
from src.app.core.logging import get_logger, log_extra
from src.app.core.ratelimit import RateLimiter, build_rate_limiter
from src.app.core.redis import RedisManager
from src.app.core.security import TokenService
from src.app.core.tasks import TaskDispatcher, build_dispatcher
from src.app.modules.chat.llm_gateway import LLMGateway
from src.app.modules.chat.service import ChatDeps, ChatService
from src.app.modules.chat.stream import (
    StreamBuffer,
    ThreadLockManager,
    build_stream_buffer,
)
from src.app.modules.chat.stream_runtime import NativeAgentRuntime
from src.app.modules.chat.tools import ToolDeps
from src.app.modules.items.storage import StorageProvider, build_storage
from src.app.modules.items.vision import VisionService
from src.app.shared.embeddings import EmbeddingClient

logger = get_logger(__name__)


@dataclass
class AppContainer:
    settings: Settings
    database: Database = field(init=False)
    redis: RedisManager = field(init=False)
    http: HttpClientPool = field(init=False)
    cache: TwoLevelCache = field(init=False)
    embeddings: EmbeddingClient = field(init=False)
    vision: VisionService = field(init=False)
    storage: StorageProvider = field(init=False)
    token_service: TokenService = field(init=False)
    idempotency: IdempotencyStore = field(init=False)
    rate_limiter: RateLimiter = field(init=False)
    dispatcher: TaskDispatcher = field(init=False)
    llm: LLMGateway = field(init=False)
    runtime: Any = field(init=False)
    stream_buffer: StreamBuffer = field(init=False)
    locks: ThreadLockManager = field(init=False)
    chat_service: ChatService = field(init=False)
    tool_deps: ToolDeps = field(init=False)
    feishu_service: Any = field(init=False)
    started_at: float = field(default_factory=time.monotonic)
    _cleanup_task: asyncio.Task[Any] | None = field(default=None, init=False)
    _started: bool = field(default=False, init=False)

    @classmethod
    def create(cls, settings: Settings) -> AppContainer:
        container = cls(settings=settings)
        container.database = Database(settings)
        container.redis = RedisManager(settings)
        container.http = HttpClientPool(settings)
        container.cache = TwoLevelCache(
            container.redis, namespace="xianxiaobao:cache", ttl=settings.CACHE_TTL_SECONDS
        )
        container.embeddings = EmbeddingClient(settings, container.http, cache=container.cache)
        container.vision = VisionService(settings)
        container.storage = build_storage(settings)
        container.token_service = TokenService(settings)
        container.llm = LLMGateway(settings, container.http)
        container.tool_deps = ToolDeps(
            settings=settings,
            database=container.database,
            embeddings=container.embeddings,
            vision=container.vision,
            dispatcher=None,  # filled in startup(), after the dispatcher exists
        )
        return container

    async def startup(self) -> None:
        if self._started:
            return
        await self.redis.connect()  # never fatal: degraded mode is supported

        self.idempotency = build_idempotency_store(self.redis)
        self.rate_limiter = build_rate_limiter(self.redis)
        self.dispatcher = build_dispatcher(self.settings, self.redis)
        self.stream_buffer = build_stream_buffer(
            self.redis,
            ttl=self.settings.AGENT_STREAM_TTL_SECONDS,
            maxlen=self.settings.AGENT_STREAM_MAXLEN,
        )
        self.locks = ThreadLockManager(self.redis, ttl=self.settings.AGENT_THREAD_LOCK_TTL)
        self.tool_deps = ToolDeps(
            settings=self.settings,
            database=self.database,
            embeddings=self.embeddings,
            vision=self.vision,
            dispatcher=self.dispatcher,
        )
        self.runtime = NativeAgentRuntime(
            gateway=self.llm,
            deps=self.tool_deps,
            max_steps=self.settings.AGENT_MAX_STEPS,
            context_messages=self.settings.AGENT_CONTEXT_MESSAGES,
        )
        self.chat_service = ChatService(
            deps=ChatDeps(
                settings=self.settings,
                database=self.database,
                runtime=self.runtime,
                buffer=self.stream_buffer,
                locks=self.locks,
                idempotency=self.idempotency,
            )
        )
        from src.app.modules.feishu.client import FeishuClient
        from src.app.modules.feishu.service import FeishuDeps, FeishuService

        self.feishu_service = FeishuService(
            deps=FeishuDeps(
                settings=self.settings,
                database=self.database,
                chat_service=self.chat_service,
                rate_limiter=self.rate_limiter,
                client=FeishuClient(self.settings, self.http, self.cache),
                idempotency=self.idempotency,
            )
        )
        self._started = True

        if self.settings.TASKS_ENABLED and not self.settings.tasks_eager:
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(), name="agent-approval-cleanup"
            )
        logger.info(
            "container started",
            extra=log_extra(
                event="container_started",
                environment=self.settings.ENVIRONMENT,
                redis_available=self.redis.available,
            ),
        )

    async def shutdown(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._cleanup_task
            self._cleanup_task = None

        if hasattr(self, "chat_service"):
            await self.chat_service.shutdown(grace_seconds=10.0)
        if hasattr(self, "dispatcher"):
            await self.dispatcher.aclose()
        await self.http.close()
        await self.redis.close()
        await self.database.dispose()
        self._started = False
        logger.info("container stopped", extra=log_extra(event="container_stopped"))

    # ------------------------------------------------------------------ health
    async def readiness(self) -> list[tuple[str, bool, float, str | None]]:
        checks: list[tuple[str, bool, float, str | None]] = []

        started = time.perf_counter()
        try:
            await self.database.ping(max_wait=2.0)
            checks.append(("database", True, (time.perf_counter() - started) * 1000, None))
        except Exception as exc:
            checks.append(
                ("database", False, (time.perf_counter() - started) * 1000, str(exc)[:200])
            )

        if self.redis.client is not None or self.settings.REDIS_REQUIRED:
            started = time.perf_counter()
            ok = await self.redis.ping()
            checks.append(
                (
                    "redis",
                    ok,
                    (time.perf_counter() - started) * 1000,
                    None if ok else "redis is not reachable",
                )
            )

        started = time.perf_counter()
        llm_ok = self.llm.configured
        checks.append(
            (
                "llm",
                llm_ok,
                (time.perf_counter() - started) * 1000,
                None if llm_ok else "CHAT_API_KEY is not configured",
            )
        )
        return checks

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    # ----------------------------------------------------------------- internal
    async def _cleanup_loop(self) -> None:
        from src.app.modules.chat import approvals

        interval = self.settings.AGENT_CLEANUP_INTERVAL_SECONDS
        while True:
            try:
                await asyncio.sleep(interval)
                async with self.database.session() as session:
                    expired = await approvals.expire_stale(session)
                if expired:
                    logger.info("agent approvals expired", extra=log_extra(count=expired))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("approval cleanup iteration failed")


_container: AppContainer | None = None


def set_container(container: AppContainer | None) -> None:
    global _container
    _container = container


def get_container() -> AppContainer:
    if _container is None:  # pragma: no cover - programming error
        raise RuntimeError("Application container is not initialised")
    return _container


__all__ = ["AppContainer", "get_container", "set_container"]
