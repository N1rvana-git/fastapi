"""User business rules.

The service layer never raises ``HTTPException``: it speaks domain errors
(``ConflictError``, ``NotFoundError``) so the same code is reusable from the
Feishu webhook, the agent tools and a CLI.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from src.app.core.logging import get_logger
from src.app.core.security import password_hasher
from src.app.modules.users import repository
from src.app.modules.users.models import ROLE_ADMIN, ROLE_USER, UserModel
from src.app.modules.users.schemas import UserRegister

logger = get_logger(__name__)


async def register_user(
    session: AsyncSession,
    payload: UserRegister,
    *,
    allow_role_selection: bool = False,
) -> UserModel:
    email = str(payload.email).strip().lower()
    if await repository.count_by_email(session, email) > 0:
        raise ConflictError("该邮箱已被注册", details={"email": email})

    # Privilege escalation guard: only an explicit admin action may create
    # admins.  The old endpoint accepted role="admin" from anonymous callers.
    role = payload.role if allow_role_selection else ROLE_USER
    if role == ROLE_ADMIN and not allow_role_selection:
        logger.warning(
            "ignored admin role requested by public registration", extra={"ctx_email": email}
        )

    user = UserModel(
        email=email,
        username=(payload.username or email.split("@")[0])[:64],
        age=18,
        hashed_password=password_hasher.hash(payload.password),
        role=role,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The unique index on lower(email) is the final guard against two
        # replicas racing the same registration.
        await session.rollback()
        raise ConflictError("该邮箱已被注册", details={"email": email}) from exc
    await session.refresh(user)
    logger.info("user registered", extra={"ctx_user_id": user.id, "ctx_role": user.role})
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> UserModel:
    user = await repository.get_by_email(session, email)
    if user is None or not user.hashed_password:
        # Same error for unknown user and wrong password: no account enumeration.
        raise UnauthorizedError("邮箱或密码错误")
    if not password_hasher.verify(password, user.hashed_password):
        raise UnauthorizedError("邮箱或密码错误")

    if password_hasher.needs_rehash(user.hashed_password):
        user.hashed_password = password_hasher.hash(password)
        await session.commit()
        logger.info("password hash upgraded", extra={"ctx_user_id": user.id})
    return user


async def get_user_or_404(session: AsyncSession, user_id: int) -> UserModel:
    user = await repository.get_by_id(session, user_id)
    if user is None:
        raise NotFoundError("用户不存在", details={"user_id": user_id})
    return user


async def list_users(
    session: AsyncSession, *, skip: int, limit: int
) -> tuple[list[UserModel], int]:
    return await repository.list_users(session, skip=skip, limit=limit)


async def bind_feishu_account(session: AsyncSession, user: UserModel, open_id: str) -> UserModel:
    owner = await repository.get_by_feishu_open_id(session, open_id)
    if owner is not None and owner.id != user.id:
        raise ConflictError("该飞书账号已被其他用户绑定")
    user.feishu_open_id = open_id
    await session.commit()
    await session.refresh(user)
    return user


async def get_by_feishu_open_id(session: AsyncSession, open_id: str) -> UserModel | None:
    return await repository.get_by_feishu_open_id(session, open_id)


async def set_role(session: AsyncSession, user: UserModel, role: str) -> UserModel:
    user.role = role
    await session.commit()
    await session.refresh(user)
    logger.info("user role changed", extra={"ctx_user_id": user.id, "ctx_role": role})
    return user


__all__ = [
    "authenticate",
    "bind_feishu_account",
    "get_by_feishu_open_id",
    "get_user_or_404",
    "list_users",
    "register_user",
    "set_role",
]
