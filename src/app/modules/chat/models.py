"""Chat + human-approval persistence.

Two things live here:

* ``ChatRecord`` - the durable conversation memory (one row per message).  The
  ``thread_id`` column groups a conversation and is what the SSE layer uses for
  replay/status, so history survives reconnects and process restarts.
* ``AgentApproval`` - the Human-in-the-Loop queue.  When the agent wants to
  perform a high-value action it stores the pending action here instead of
  blocking a worker; ``/resume`` validates and applies the decision.  Rows that
  nobody ever decides are expired by a periodic cleanup task (no zombie state
  machines).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import Base

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_EXPIRED = "expired"
APPROVAL_STATUSES = frozenset(
    {APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED, APPROVAL_EXPIRED}
)


class ChatRecord(Base):
    __tablename__ = "ai_chat_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentApproval(Base):
    __tablename__ = "agent_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=APPROVAL_PENDING, server_default=APPROVAL_PENDING
    )
    # JSON payload of the action that needs approval (item id, address, amount...)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resolved_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Set to True once the decision was delivered to the SSE stream.
    notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
