"""Order aggregate.

An order stores a **price snapshot**: if the seller edits the listing later the
historical order must not change, and the buyer must never be charged the new
price.  ``idempotency_key`` makes order creation exactly-once even when the
agent or the HTTP client retries.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.core.database import Base

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"
VALID_STATUSES = frozenset({STATUS_PENDING, STATUS_PAID, STATUS_CANCELLED, STATUS_COMPLETED})


class OrderModel(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    buyer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("item.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PAID, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    # Snapshot of the unit price at purchase time.
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Exactly-once guard for retries (HTTP + agent tool calls).
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    buyer = relationship("UserModel", lazy="selectin")
    item = relationship("ItemModel", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OrderModel id={self.id} item_id={self.item_id} status={self.status!r}>"
