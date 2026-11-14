"""Purchase flow: stock reservation, order creation, approval gate.

The order is created **after** the stock reservation succeeds, in the same
transaction, and carries the unit price it was bought at.  ``idempotency_key``
is unique at the database level, so even if two replicas both pass the Redis
guard the second insert fails instead of double-selling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import Settings
from src.app.core.exceptions import ApprovalRequiredError, BusinessRuleViolation, OutOfStockError
from src.app.core.logging import get_logger
from src.app.modules.items import repository as items_repository
from src.app.modules.items import service as items_service
from src.app.modules.items.models import ItemModel
from src.app.modules.orders import repository
from src.app.modules.orders.models import STATUS_PAID, OrderModel
from src.app.modules.users.models import UserModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class PurchaseResult:
    order: OrderModel
    item_name: str
    unit_price: float
    quantity: int
    remaining_inventory: int
    replayed: bool = False


async def purchase(
    session: AsyncSession,
    *,
    item_id: int,
    buyer: UserModel,
    settings: Settings,
    quantity: int = 1,
    address: str | None = None,
    idempotency_key: str | None = None,
    require_approval: bool = False,
    dispatcher: Any | None = None,
) -> PurchaseResult:
    if quantity < 1:
        raise BusinessRuleViolation("购买数量必须大于 0")

    if idempotency_key:
        existing = await repository.get_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            item = await items_repository.get_by_id(session, existing.item_id)
            logger.info(
                "order replay",
                extra={"ctx_order_id": existing.id, "ctx_idempotency_key": idempotency_key},
            )
            return PurchaseResult(
                order=existing,
                item_name=item.name if item else "",
                unit_price=float(existing.price or 0),
                quantity=existing.quantity,
                remaining_inventory=item.inventory if item else 0,
                replayed=True,
            )

    item = await _load_item(session, item_id)
    items_service.ensure_purchasable(item, quantity=quantity)
    if item.owner_id == buyer.id:
        raise BusinessRuleViolation("不能购买自己发布的商品")

    amount = float(item.price) * quantity
    if require_approval and amount >= settings.AGENT_APPROVAL_THRESHOLD:
        raise ApprovalRequiredError(
            "该订单金额超过自动授权额度，需要人工审核",
            details={
                "item_id": item.id,
                "item_name": item.name,
                "quantity": quantity,
                "unit_price": float(item.price),
                "amount": amount,
                "threshold": settings.AGENT_APPROVAL_THRESHOLD,
                "address": address,
            },
        )

    if not await items_repository.decrement_stock(session, item.id, quantity):
        # The conditional UPDATE changed nothing, so there is nothing to roll
        # back; reading `item` after a rollback would also expire it (and blow
        # up with MissingGreenlet), so just fail with a domain error.
        raise OutOfStockError("商品库存不足，下单失败", details={"item_id": item.id})

    order = OrderModel(
        buyer_id=buyer.id,
        item_id=item.id,
        status=STATUS_PAID,
        quantity=quantity,
        price=float(item.price),
        address=address,
        idempotency_key=idempotency_key,
    )
    try:
        await repository.create(session, order)
    except IntegrityError:
        # Another replica won the race for the same idempotency key: undo the
        # stock reservation and return its order instead.
        await session.rollback()
        existing = (
            await repository.get_by_idempotency_key(session, idempotency_key)
            if idempotency_key
            else None
        )
        if existing is None:
            raise
        item = await items_repository.get_by_id(session, existing.item_id)
        return PurchaseResult(
            order=existing,
            item_name=item.name if item else "",
            unit_price=float(existing.price or 0),
            quantity=existing.quantity,
            remaining_inventory=item.inventory if item else 0,
            replayed=True,
        )

    remaining = max(0, int(item.inventory or 0) - quantity)
    logger.info(
        "order created",
        extra={
            "ctx_order_id": order.id,
            "ctx_item_id": item.id,
            "ctx_buyer_id": buyer.id,
            "ctx_amount": amount,
            "ctx_remaining": remaining,
        },
    )
    await _notify_seller(dispatcher, item=item, buyer=buyer, address=address, quantity=quantity)
    return PurchaseResult(
        order=order,
        item_name=item.name,
        unit_price=float(item.price),
        quantity=quantity,
        remaining_inventory=remaining,
    )


async def _load_item(session: AsyncSession, item_id: int) -> ItemModel:
    from src.app.core.exceptions import NotFoundError

    item = await items_repository.get_by_id(session, item_id)
    if item is None:
        raise NotFoundError("商品不存在", details={"item_id": item_id})
    return item


async def _notify_seller(
    dispatcher: Any | None,
    *,
    item: ItemModel,
    buyer: UserModel,
    address: str | None,
    quantity: int,
) -> None:
    """Fire-and-forget notification: never blocks or fails the purchase."""

    if dispatcher is None:
        return
    try:
        await dispatcher.enqueue(
            "notifications.order_alert",
            item_id=item.id,
            buyer_id=buyer.id,
            address=address or "",
            quantity=quantity,
        )
    except Exception:
        logger.exception("failed to enqueue order notification", extra={"ctx_item_id": item.id})


async def list_my_orders(
    session: AsyncSession, buyer: UserModel, *, limit: int = 100
) -> list[OrderModel]:
    return await repository.list_by_buyer(session, buyer.id, limit=limit)


__all__ = ["PurchaseResult", "list_my_orders", "purchase"]
