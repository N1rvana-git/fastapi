"""FastAPI dependencies shared by every module.

Rules:

* infrastructure comes from the application container (created in the lifespan),
  never from module-level globals, so tests can swap it;
* authentication lives here exactly once - routers only declare
  ``user = Depends(get_current_user)``;
* background/messaging dependencies return the process-wide instances.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.cache import TwoLevelCache
from src.app.core.config import Settings
from src.app.core.context import set_user_id
from src.app.core.database import Database
from src.app.core.exceptions import (
    ConflictError,
    IdempotencyConflict,
    PermissionDeniedError,
    RateLimitedError,
    UnauthorizedError,
    ValidationError,
)
from src.app.core.idempotency import IdempotencyGuard, IdempotencyOutcome, body_fingerprint
from src.app.core.ratelimit import RateLimiter
from src.app.core.security import TokenService
from src.app.modules.users import repository as users_repository
from src.app.modules.users.models import UserModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.app.container import AppContainer
    from src.app.modules.chat.service import ChatService

# ``token`` is the historical endpoint; keep the OpenAPI security scheme honest.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)

IDEMPOTENCY_HEADER = "X-Idempotency-Key"


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_container(request: Request) -> AppContainer:
    # cast() takes a runtime expression, so the TYPE_CHECKING import is quoted.
    return cast("AppContainer", request.app.state.container)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.container.database)


def get_token_service(request: Request) -> TokenService:
    return cast(TokenService, request.app.state.container.token_service)


def get_cache(request: Request) -> TwoLevelCache:
    return cast(TwoLevelCache, request.app.state.container.cache)


def get_rate_limiter(request: Request) -> RateLimiter:
    return cast(RateLimiter, request.app.state.container.rate_limiter)


def get_chat_service(request: Request) -> ChatService:
    return cast("ChatService", request.app.state.container.chat_service)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One short-lived session per request; closed by the context manager."""

    database: Database = request.app.state.container.database
    async with database.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
    request: Request,
) -> UserModel:
    token_service: TokenService = request.app.state.container.token_service
    payload = token_service.decode_token(token)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError("Could not validate credentials") from exc

    user = await users_repository.get_by_id(session, user_id)
    if user is None:
        raise UnauthorizedError("用户不存在或已注销")
    set_user_id(user.id)
    return user


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    session: SessionDep,
    request: Request,
) -> UserModel | None:
    if not token:
        return None
    try:
        payload = request.app.state.container.token_service.decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        return None
    user = await users_repository.get_by_id(session, user_id)
    if user is not None:
        set_user_id(user.id)
    return user


CurrentUser = Annotated[UserModel, Depends(get_current_user)]
OptionalUser = Annotated[UserModel | None, Depends(get_current_user_optional)]


async def require_admin(user: CurrentUser) -> UserModel:
    if user.role != "admin":
        raise PermissionDeniedError("需要管理员权限")
    return user


AdminUser = Annotated[UserModel, Depends(require_admin)]


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
def rate_limit(scope: str, limit: int, window_seconds: int = 60) -> Callable[..., object]:
    """Dependency factory: ``Depends(rate_limit("chat", 20, 60))``."""

    async def dependency(request: Request) -> None:
        settings: Settings = request.app.state.settings
        if not settings.RATE_LIMIT_ENABLED:
            return
        from src.app.core.context import get_user_id

        user_id = get_user_id()
        client = request.client.host if request.client else "unknown"
        bucket = f"{scope}:{user_id or client}"
        result = await request.app.state.container.rate_limiter.hit(
            bucket, limit=limit, window_seconds=window_seconds
        )
        if not result.allowed:
            raise RateLimitedError(
                f"请求过于频繁，请 {result.retry_after} 秒后再试",
                retry_after=result.retry_after,
            )

    return dependency


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def idempotency_guard(
    scope: str,
    *,
    required: bool | None = None,
    include_body: bool = True,
) -> Callable[..., AsyncIterator[IdempotencyGuard]]:
    """Dependency factory enforcing ``X-Idempotency-Key`` semantics."""

    async def dependency(request: Request) -> AsyncIterator[IdempotencyGuard]:
        settings: Settings = request.app.state.settings
        store = request.app.state.container.idempotency
        key = (request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
        is_required = settings.IDEMPOTENCY_HEADER_REQUIRED if required is None else required

        if not key:
            if is_required:
                raise ValidationError(
                    "写操作必须携带幂等键",
                    details={"header": IDEMPOTENCY_HEADER},
                )
            guard = IdempotencyGuard.disabled()
            yield guard
            return

        if len(key) > 128:
            raise ValidationError("X-Idempotency-Key 过长", details={"max_length": 128})

        fingerprint_parts = [scope, request.method, request.url.path]
        if include_body:
            body = await request.body()
            fingerprint_parts.append(body.decode("utf-8", "replace"))
        fingerprint = body_fingerprint(*fingerprint_parts)

        guard = IdempotencyGuard(
            store=store,
            key=f"{scope}:{key}",
            fingerprint=fingerprint,
            ttl=settings.IDEMPOTENCY_TTL_SECONDS,
            pending_ttl=settings.IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS,
        )
        outcome = await guard.begin()
        if outcome is IdempotencyOutcome.IN_PROGRESS:
            raise IdempotencyConflict(
                "相同请求正在处理中，请稍后重试",
                details={"idempotency_key": key},
            )
        if outcome is IdempotencyOutcome.MISMATCH:
            raise ConflictError(
                "该幂等键已用于不同的请求体",
                details={"idempotency_key": key},
            )
        try:
            yield guard
        finally:
            await guard.release()

    return dependency


def replay_response(guard: IdempotencyGuard) -> JSONResponse | None:
    """Return the cached response for a replayed key, if any."""

    if guard.outcome is not IdempotencyOutcome.REPLAY or guard.record is None:
        return None
    if guard.record.status_code is None:
        return None
    return JSONResponse(
        status_code=guard.record.status_code,
        content=guard.record.body,
        headers={IDEMPOTENCY_HEADER: guard.key or "", "X-Idempotent-Replay": "true"},
    )


__all__ = [
    "IDEMPOTENCY_HEADER",
    "AdminUser",
    "CurrentUser",
    "OptionalUser",
    "SessionDep",
    "get_cache",
    "get_chat_service",
    "get_container",
    "get_current_user",
    "get_current_user_optional",
    "get_database",
    "get_db_session",
    "get_rate_limiter",
    "get_settings",
    "get_token_service",
    "idempotency_guard",
    "oauth2_scheme",
    "rate_limit",
    "replay_response",
    "require_admin",
]
