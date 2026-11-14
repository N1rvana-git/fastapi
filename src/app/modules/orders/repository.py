"""Order persistence."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.modules.orders.models import OrderModel


async def get_by_idempotency_key(session: AsyncSession, key: str) -> OrderModel | None:
    stmt = select(OrderModel).where(OrderModel.idempotency_key == key)
    return (await session.execute(stmt)).scalars().first()


async def create(session: AsyncSession, order: OrderModel) -> OrderModel:
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def list_by_buyer(
    session: AsyncSession, buyer_id: int, *, limit: int = 100
) -> list[OrderModel]:
    stmt = (
        select(OrderModel)
        .options(selectinload(OrderModel.item))
        .where(OrderModel.buyer_id == buyer_id)
        .order_by(OrderModel.id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_by_buyer(session: AsyncSession, buyer_id: int) -> int:
    stmt = select(func.count()).select_from(OrderModel).where(OrderModel.buyer_id == buyer_id)
    return int(await session.scalar(stmt) or 0)


async def list_for_item(session: AsyncSession, item_id: int) -> list[OrderModel]:
    stmt = select(OrderModel).where(OrderModel.item_id == item_id).order_by(OrderModel.id)
    return list((await session.execute(stmt)).scalars().all())


__all__ = ["count_by_buyer", "create", "get_by_idempotency_key", "list_by_buyer", "list_for_item"]
