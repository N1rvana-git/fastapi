"""Application factory and lifespan.

``create_app()`` is the single composition root for the web process:

1. load validated settings and configure structured logging;
2. build the container (engine, pools, gateways) - no network I/O yet;
3. on start-up: connect Redis (optional), build the agent runtime, start the
   approval cleanup loop;
4. on shutdown: stop background work, drain in-flight agent runs, close HTTP
   clients, Redis and the database - in that order, so nothing is closed under a
   running coroutine.

Database migrations are deliberately **not** executed here: ``alembic upgrade``
belongs to the deployment pipeline (a Kubernetes Job / CI stage), otherwise N
replicas racing the same migration corrupt the schema.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.app.__about__ import __version__
from src.app.api.router import build_router
from src.app.container import AppContainer, set_container
from src.app.core.config import Settings, get_settings
from src.app.core.database import import_all_models, set_database
from src.app.core.exceptions import register_exception_handlers
from src.app.core.logging import configure_logging, get_logger, log_extra
from src.app.core.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from src.app.task_registry import import_task_modules

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    import_task_modules()
    import_all_models()
    container = AppContainer.create(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.container = container
        set_container(container)
        set_database(container.database)

        await container.startup()
        try:
            await container.database.ping(timeout=3.0)
            logger.info("database reachable")
        except Exception as exc:
            logger.warning(
                "database not reachable at startup; readiness will fail until it is",
                extra=log_extra(error=str(exc)[:200]),
            )
        logger.info(
            "application started",
            extra=log_extra(
                event="app_started",
                environment=settings.ENVIRONMENT,
                version=settings.APP_VERSION,
                redis_available=container.redis.available,
            ),
        )
        if settings.uses_ephemeral_secret:
            logger.warning(
                "SECRET_KEY was not configured; using an ephemeral development secret "
                "(all tokens become invalid after restart). Set SECRET_KEY in .env."
            )
        try:
            yield
        finally:
            await container.shutdown()
            set_container(None)
            set_database(None)
            logger.info("application stopped", extra=log_extra(event="app_stopped"))

    docs_enabled = settings.DOCS_ENABLED
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "闲小宝二手交易平台 API：认证、商品、订单、AI 导购（SSE）与飞书集成。"
            "所有错误遵循统一的 error envelope，写接口支持 X-Idempotency-Key。"
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        openapi_tags=[
            {"name": "health", "description": "存活与就绪探针"},
            {"name": "authentication", "description": "JWT 认证"},
            {"name": "users", "description": "用户与权限"},
            {"name": "items", "description": "商品、标签、收藏与交易"},
            {"name": "ai", "description": "AI 导购（SSE 流式 + 人工审批）"},
            {"name": "feishu", "description": "飞书机器人集成"},
        ],
    )

    # Middleware: added inner-to-outer (the last added is the outermost).
    origins = settings.cors_origins
    allow_all = settings.CORS_ALLOW_ALL_IN_DEV and settings.ENVIRONMENT == "development"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        allow_origin_regex=".*" if allow_all else None,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Idempotency-Key",
            "X-Thread-ID",
            "Last-Event-ID",
            "X-Request-ID",
            "X-Trace-ID",
        ],
        expose_headers=["X-Trace-ID", "X-Request-ID", "X-Idempotency-Key", "X-Thread-ID"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(AccessLogMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(build_router(), prefix=settings.API_PREFIX)

    _mount_static(app, settings)

    @app.get("/", include_in_schema=False)
    async def read_root() -> dict[str, str]:
        return {
            "message": "Welcome to my practice",
            "environment": settings.ENVIRONMENT,
            "version": settings.APP_VERSION,
        }

    @app.get("/version", include_in_schema=False)
    async def read_version() -> dict[str, str]:
        return settings.public_dict()  # type: ignore[return-value]

    return app


def _mount_static(app: FastAPI, settings: Settings) -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


app = create_app()

__all__ = ["__version__", "app", "create_app"]
