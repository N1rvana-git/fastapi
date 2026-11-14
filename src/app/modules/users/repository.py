"""User data access. SQLAlchemy 2.0 ``select()`` only - no string SQL."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.modules.users.models import UserModel


async def get_by_id(session: AsyncSession, user_id: int) -> UserModel | None:
    return await session.get(UserModel, user_id)


async def get_by_email(session: AsyncSession, email: str) -> UserModel | None:
    stmt = select(UserModel).where(func.lower(UserModel.email) == email.strip().lower())
    return (await session.execute(stmt)).scalars().first()


async def get_by_feishu_open_id(session: AsyncSession, open_id: str) -> UserModel | None:
    stmt = select(UserModel).where(UserModel.feishu_open_id == open_id)
    return (await session.execute(stmt)).scalars().first()


async def list_users(
    session: AsyncSession, *, skip: int, limit: int
) -> tuple[list[UserModel], int]:
    total = await session.scalar(select(func.count()).select_from(UserModel)) or 0
    stmt = select(UserModel).order_by(UserModel.id).offset(skip).limit(limit)
    users = list((await session.execute(stmt)).scalars().all())
    return users, int(total)


async def count_by_email(session: AsyncSession, email: str) -> int:
    stmt = (
        select(func.count())
        .select_from(UserModel)
        .where(func.lower(UserModel.email) == email.strip().lower())
    )
    return int(await session.scalar(stmt) or 0)


__all__ = [
    "count_by_email",
    "get_by_email",
    "get_by_feishu_open_id",
    "get_by_id",
    "list_users",
]
