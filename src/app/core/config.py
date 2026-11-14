"""Typed, validated application settings.

Everything the app needs is declared here once, validated at import time and
injected as a cached singleton.  A misconfigured environment fails fast at
start-up instead of exploding on the first request (e.g. an empty JWT secret).

Environment variables win over ``.env``; ``.env`` is only a local convenience.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/app/core/config.py -> src/app/core -> src/app -> src -> <repo root>
BASE_DIR = Path(__file__).resolve().parents[3]

Environment = Literal["development", "test", "staging", "production"]


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _default_secret(environment: str) -> str:
    """Development convenience only.

    Production/staging refuse to boot with this placeholder (see validator).
    """

    if environment in {"development", "test"}:
        return "dev-only-insecure-secret-key-" + secrets.token_hex(8)
    return ""


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # legacy keys (API_KEy, ...) must not break start-up
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app
    APP_NAME: str = "闲小宝二手交易平台"
    APP_VERSION: str = "0.2.0"
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = False
    API_PREFIX: str = ""  # set to "/api/v1" to version the public surface
    DOCS_ENABLED: bool = True

    # ----------------------------------------------------------- database
    DATABASE_URL: str = "sqlite+aiosqlite:///./test.db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=200)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0, le=400)
    DB_POOL_TIMEOUT: float = Field(default=5.0, gt=0)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=0)
    DB_PRE_PING: bool = True
    DB_CONNECT_TIMEOUT: float = Field(default=5.0, gt=0)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=15_000, ge=0)

    # -------------------------------------------------------------- redis
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    # Shared pool for rate limiting, idempotency and task enqueue. Every request
    # performs at least one Redis command, so keep this close to the expected
    # concurrent request count (the old default of 20 failed at 50 SSE streams).
    REDIS_MAX_CONNECTIONS: int = Field(default=100, ge=1, le=2000)
    # Each open SSE stream occupies one blocking Redis connection (XREAD BLOCK),
    # so this pool must be sized for the expected number of concurrent streams.
    REDIS_BLOCKING_MAX_CONNECTIONS: int = Field(default=100, ge=4, le=2000)
    REDIS_SOCKET_TIMEOUT: float = Field(default=1.0, gt=0)
    REDIS_REQUIRED: bool = False  # when True, readiness fails if Redis is down
    CACHE_TTL_SECONDS: int = Field(default=60, ge=0)

    # --------------------------------------------------------------- auth
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=60 * 24 * 30)
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 14, ge=1)
    JWT_ISSUER: str = "xianxiaobao"
    JWT_AUDIENCE: str = "xianxiaobao-api"
    #: Allow anonymous callers to choose role="admin" at registration.
    #: Off by default: it was a privilege-escalation hole in the old API.
    ALLOW_PUBLIC_ROLE_SELECTION: bool = False

    # --------------------------------------------------------------- http
    HTTP_CONNECT_TIMEOUT: float = Field(default=5.0, gt=0)
    HTTP_READ_TIMEOUT: float = Field(default=30.0, gt=0)
    HTTP_WRITE_TIMEOUT: float = Field(default=10.0, gt=0)
    HTTP_POOL_TIMEOUT: float = Field(default=5.0, gt=0)
    HTTP_MAX_CONNECTIONS: int = Field(default=100, ge=1)
    HTTP_MAX_KEEPALIVE_CONNECTIONS: int = Field(default=20, ge=0)

    # ---------------------------------------------------------------- llm
    # DeepSeek's official API is OpenAI-compatible for chat (no embeddings):
    # accept both CHAT_* and the DEEPSEEK_* names so a DeepSeek-only .env works.
    CHAT_API_KEY: str = Field(
        default="", validation_alias=AliasChoices("CHAT_API_KEY", "DEEPSEEK_API_KEY")
    )
    API_KEY: str = ""  # legacy alias kept for existing deployments
    CHAT_BASE_URL: str = Field(
        default="https://api.zetatechs.com/v1",
        validation_alias=AliasChoices("CHAT_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    CHAT_MODEL: str = Field(
        default="gemini-3-flash-preview-free",
        validation_alias=AliasChoices("CHAT_MODEL", "DEEPSEEK_MODEL"),
    )
    ALLOWED_CHAT_MODELS: str = "gemini-3-flash-preview-free,deepseek-flash,deepseek-v4-pro"
    LLM_MAX_CONCURRENCY: int = Field(default=32, ge=1, le=1024)
    LLM_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    LLM_RETRY_BASE_DELAY: float = Field(default=0.5, ge=0)
    LLM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)

    # ---------------------------------------------------------- embeddings
    # DeepSeek has no /embeddings endpoint; this stays a separate provider
    # (Zhipu embedding-2, 1024 dims by default).
    ZHIPUAI_API_KEY: str = Field(
        default="", validation_alias=AliasChoices("ZHIPUAI_API_KEY", "ZHIPU_API_KEY")
    )
    ZHIPU_EMBEDDING_MODEL: str = "embedding-2"
    ALLOWED_EMBEDDING_MODELS: str = "embedding-2"
    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    EMBEDDING_DIMENSION: int = Field(default=1024, ge=1)
    EMBEDDING_ENABLED: bool = True

    # -------------------------------------------------------------- agent
    AGENT_RUNTIME: Literal["native", "langgraph"] = "native"
    AGENT_MAX_STEPS: int = Field(default=6, ge=1, le=20)
    AGENT_APPROVAL_THRESHOLD: float = Field(default=1000.0, ge=0)
    AGENT_APPROVAL_TTL_HOURS: int = Field(default=24, ge=1)
    AGENT_CONTEXT_MESSAGES: int = Field(default=8, ge=1, le=100)
    AGENT_STREAM_TTL_SECONDS: int = Field(default=600, ge=30)
    AGENT_STREAM_MAXLEN: int = Field(default=2000, ge=10)
    AGENT_THREAD_LOCK_TTL: int = Field(default=30, ge=5)
    AGENT_STREAM_HEARTBEAT_SECONDS: int = Field(default=15, ge=1, le=60)
    AGENT_DISCONNECT_POLICY: Literal["abort", "continue"] = "continue"
    AGENT_CLEANUP_INTERVAL_SECONDS: int = Field(default=3600, ge=60)
    LANGGRAPH_ENABLED: bool = False
    POSTGRES_RAW_DSN: str = ""  # psycopg3 DSN for the checkpointer pool
    CHECKPOINTER_POOL_MIN: int = Field(default=2, ge=1)
    CHECKPOINTER_POOL_MAX: int = Field(default=10, ge=1)

    # -------------------------------------------------------------- feishu
    FEISHU_VERIFICATION_TOKEN: str = ""
    FEISHU_ENCRYPT_KEY: str = ""
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_BASE_URL: str = "https://open.feishu.cn/open-apis"
    FEISHU_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    FEISHU_RATE_LIMIT_PER_MINUTE: int = Field(default=3, ge=1)
    FEISHU_BIND_URL_BASE: str = "http://localhost:5173/bind-feishu"

    # ------------------------------------------------------------ uploads
    UPLOAD_DIR: str = "uploads"
    STATIC_DIR: str = "static"
    MAX_UPLOAD_BYTES: int = Field(default=10 * 1024 * 1024, ge=1024)
    ALLOWED_IMAGE_EXTENSIONS: str = "jpg,jpeg,png,webp,gif"
    STORAGE_BACKEND: Literal["local", "cloud"] = "local"
    STORAGE_UPLOAD_URL: str = ""
    PUBLIC_BASE_URL: str = ""
    VISION_ENABLED: bool = True
    VISION_MODEL: str = "OFA-Sys/chinese-clip-vit-base-patch16"
    VISION_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    # ---------------------------------------------------------- middleware
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_ALL_IN_DEV: bool = True
    MAX_REQUEST_BYTES: int = Field(default=1 * 1024 * 1024, ge=1024)
    SECURITY_HEADERS_ENABLED: bool = True
    HSTS_ENABLED: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"
    LOG_ACCESS_EXCLUDE: str = (
        "/health,/health/live,/health/ready,/,/favicon.ico,/docs,/redoc,/openapi.json"
    )

    # --------------------------------------------------------------- tasks
    TASKS_ENABLED: bool = True
    TASKS_EAGER: bool = False  # True -> run inline in the API process (tests)
    TASKS_STREAM: str = "xianxiaobao:tasks"
    TASKS_GROUP: str = "workers"
    TASKS_MAX_ATTEMPTS: int = Field(default=3, ge=1)
    TASKS_BACKOFF_SECONDS: float = Field(default=2.0, ge=0)
    TASKS_VISIBILITY_TIMEOUT_MS: int = Field(default=60_000, ge=1000)

    # --------------------------------------------------------- idempotency
    IDEMPOTENCY_HEADER_REQUIRED: bool = False
    IDEMPOTENCY_TTL_SECONDS: int = Field(default=60 * 60 * 24, ge=60)
    IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS: int = Field(default=120, ge=10)
    RATE_LIMIT_ENABLED: bool = True

    # ------------------------------------------------------------ derived
    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        scheme = value.split("://", 1)[0]
        if scheme not in {
            "sqlite+aiosqlite",
            "postgresql+asyncpg",
            "postgres+asyncpg",
        }:
            raise ValueError(
                "DATABASE_URL must use an async driver "
                "(sqlite+aiosqlite:// or postgresql+asyncpg://), got: " + scheme
            )
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # Placeholder is filled later (needs ENVIRONMENT); here only length of
        # explicitly provided values is checked.
        if value and len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @model_validator(mode="after")
    def _apply_defaults_and_cross_checks(self) -> Settings:
        if not self.SECRET_KEY:
            self.SECRET_KEY = _default_secret(self.ENVIRONMENT)
        if not self.SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is required outside development/test (>= 32 chars). "
                'Generate one with: python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        if self.CHAT_MODEL not in _split_csv(self.ALLOWED_CHAT_MODELS):
            raise ValueError(f"CHAT_MODEL={self.CHAT_MODEL!r} is not in ALLOWED_CHAT_MODELS")
        if self.ZHIPU_EMBEDDING_MODEL not in _split_csv(self.ALLOWED_EMBEDDING_MODELS):
            raise ValueError(
                f"ZHIPU_EMBEDDING_MODEL={self.ZHIPU_EMBEDDING_MODEL!r} is not in "
                "ALLOWED_EMBEDDING_MODELS"
            )
        if self.ENVIRONMENT == "production" and self.DEBUG:
            raise ValueError("DEBUG must be disabled in production")
        if self.ENVIRONMENT == "production" and self.CORS_ALLOW_ALL_IN_DEV:
            raise ValueError(
                "CORS_ALLOW_ALL_IN_DEV must be false in production; list explicit "
                "origins in CORS_ORIGINS"
            )
        if self.ENVIRONMENT not in {"development", "test"} and self.TASKS_EAGER:
            raise ValueError("TASKS_EAGER is only allowed in development/test")
        return self

    # ------------------------------------------------------------ helpers
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "test"

    @property
    def uses_ephemeral_secret(self) -> bool:
        """True when a throw-away development secret was generated."""

        return self.SECRET_KEY.startswith("dev-only-insecure-secret-key-")

    @property
    def chat_api_key(self) -> str:
        """Resolve the API-key setting and its documented legacy alias."""

        return self.CHAT_API_KEY or self.API_KEY

    @property
    def cors_origins(self) -> list[str]:
        origins = list(_split_csv(self.CORS_ORIGINS))
        # The dev frontends are always allowed while developing.
        if self.ENVIRONMENT == "development":
            for extra in ("http://localhost:5173", "http://127.0.0.1:5173"):
                if extra not in origins:
                    origins.append(extra)
        return origins

    @property
    def allowed_image_extensions(self) -> set[str]:
        return {item.lower().lstrip(".") for item in _split_csv(self.ALLOWED_IMAGE_EXTENSIONS)}

    @property
    def upload_dir(self) -> Path:
        return (BASE_DIR / self.UPLOAD_DIR).resolve()

    @property
    def static_dir(self) -> Path:
        return (BASE_DIR / self.STATIC_DIR).resolve()

    @property
    def log_access_exclude(self) -> set[str]:
        return {path.strip() for path in _split_csv(self.LOG_ACCESS_EXCLUDE)}

    @property
    def tasks_eager(self) -> bool:
        return self.TASKS_EAGER or self.is_testing

    def public_dict(self) -> dict[str, object]:
        """Non-secret view for the /health/details endpoint."""

        return {
            "app_name": self.APP_NAME,
            "version": self.APP_VERSION,
            "environment": self.ENVIRONMENT,
            "agent_runtime": self.AGENT_RUNTIME,
            "langgraph_enabled": self.LANGGRAPH_ENABLED,
            "tasks_eager": self.tasks_eager,
            "vision_enabled": self.VISION_ENABLED,
            "debug": self.DEBUG,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor (override in tests via ``get_settings.cache_clear``)."""

    return Settings()


settings = get_settings()

__all__ = ["BASE_DIR", "Settings", "get_settings", "settings"]
