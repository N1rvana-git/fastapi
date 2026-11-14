"""Human-in-the-loop approvals.

When the agent wants to perform an action above the auto-approval threshold it
does **not** block a worker: it stores a pending approval and tells the user
"submitted for review".  A human then approves or rejects through
``/items/ai/threads/{thread_id}/resume``.

Correctness details that the old code had no answer for:

* the decision is claimed with a conditional ``UPDATE ... WHERE status='pending'``
  so two clicks (or two replicas) cannot both execute the action;
* the resulting purchase is idempotent (its own idempotency key), so even a
  retried ``resume`` cannot double-order;
* approvals expire, and a periodic task closes them, so no workflow stays
  half-suspended forever.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import Settings
from src.app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from src.app.core.logging import get_logger
from src.app.modules.chat.models import (
    APPROVAL_APPROVED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    AgentApproval,
)
from src.app.modules.orders import service as orders_service
from src.app.modules.users.models import UserModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: int
    thread_id: str
    status: str
    order_id: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _key(thread_id: str, action: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{thread_id}\x00{action}\x00{blob}".encode()).hexdigest()[:40]
    return f"approval:{thread_id}:{action}:{digest}"


async def request_approval(
    session: AsyncSession,
    *,
    thread_id: str,
    user_id: int,
    action: str,
    payload: dict[str, Any],
    reason: str,
    settings: Settings,
) -> AgentApproval:
    """Create (or return the existing) pending approval for this exact action."""

    key = _key(thread_id, action, payload)
    existing = await _get_by_key(session, key)
    if existing is not None:
        return existing

    approval = AgentApproval(
        thread_id=thread_id,
        idempotency_key=key,
        user_id=user_id,
        action=action,
        status=APPROVAL_PENDING,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        reason=reason[:500],
        expires_at=_now() + timedelta(hours=settings.AGENT_APPROVAL_TTL_HOURS),
    )
    session.add(approval)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        existing = await _get_by_key(session, key)
        if existing is None:
            raise
        return existing
    await session.refresh(approval)
    logger.info(
        "approval requested",
        extra={"ctx_approval_id": approval.id, "ctx_thread_id": thread_id, "ctx_action": action},
    )
    return approval


async def list_pending(
    session: AsyncSession, thread_id: str | None = None, *, user_id: int | None = None
) -> list[AgentApproval]:
    stmt = select(AgentApproval).where(AgentApproval.status == APPROVAL_PENDING)
    if thread_id:
        stmt = stmt.where(AgentApproval.thread_id == thread_id)
    if user_id is not None:
        stmt = stmt.where(AgentApproval.user_id == user_id)
    stmt = stmt.order_by(AgentApproval.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_for_thread(
    session: AsyncSession, thread_id: str, *, user_id: int | None = None
) -> list[AgentApproval]:
    stmt = select(AgentApproval).where(AgentApproval.thread_id == thread_id)
    if user_id is not None:
        stmt = stmt.where(AgentApproval.user_id == user_id)
    stmt = stmt.order_by(AgentApproval.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def decide(
    session: AsyncSession,
    *,
    approval_id: int,
    approve: bool,
    actor: UserModel,
    comment: str | None,
    settings: Settings,
    dispatcher: Any | None = None,
) -> ApprovalDecision:
    approval = await session.get(AgentApproval, approval_id)
    if approval is None:
        raise NotFoundError("审批记录不存在", details={"approval_id": approval_id})
    if approval.user_id != actor.id and actor.role != "admin":
        raise PermissionDeniedError("无权处理该审批")

    if approval.status != APPROVAL_PENDING:
        raise ConflictError("该审批已被处理", details={"status": approval.status})
    if _is_expired(approval):
        await _set_status(session, approval, APPROVAL_EXPIRED, actor.id, comment)
        raise ConflictError("该审批已超时，请重新发起")

    target_status = APPROVAL_APPROVED if approve else APPROVAL_REJECTED
    claimed = await _claim(session, approval_id, target_status, actor.id, comment)
    if not claimed:
        raise ConflictError("该审批刚刚被其他人处理")

    await session.refresh(approval)
    if not approve:
        logger.info("approval rejected", extra={"ctx_approval_id": approval_id})
        return ApprovalDecision(approval.id, approval.thread_id, APPROVAL_REJECTED)

    payload = json.loads(approval.payload or "{}")
    buyer = await session.get(UserModel, approval.user_id)
    if buyer is None:
        raise NotFoundError("审批对应的用户不存在")

    result = await orders_service.purchase(
        session,
        item_id=int(payload.get("item_id", 0)),
        buyer=buyer,
        settings=settings,
        quantity=int(payload.get("quantity", 1)),
        address=payload.get("address"),
        idempotency_key=f"approval:{approval.id}",
        require_approval=False,  # already approved by a human
        dispatcher=dispatcher,
    )
    await session.execute(
        update(AgentApproval)
        .where(AgentApproval.id == approval_id)
        .values(resolved_order_id=result.order.id)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    logger.info(
        "approval approved and executed",
        extra={"ctx_approval_id": approval_id, "ctx_order_id": result.order.id},
    )
    return ApprovalDecision(approval.id, approval.thread_id, APPROVAL_APPROVED, result.order.id)


async def expire_stale(session: AsyncSession, *, now: datetime | None = None) -> int:
    moment = now or _now()
    result = await session.execute(
        update(AgentApproval)
        .where(AgentApproval.status == APPROVAL_PENDING, AgentApproval.expires_at <= moment)
        .values(status=APPROVAL_EXPIRED, decided_at=moment)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    count = int(result.rowcount or 0)
    if count:
        logger.info("expired stale approvals", extra={"ctx_count": count})
    return count


def serialize(approval: AgentApproval) -> dict[str, Any]:
    try:
        payload = json.loads(approval.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "approval_id": approval.id,
        "thread_id": approval.thread_id,
        "action": approval.action,
        "status": approval.status,
        "payload": payload,
        "reason": approval.reason,
        "decision_comment": approval.decision_comment,
        "resolved_order_id": approval.resolved_order_id,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
    }


async def _get_by_key(session: AsyncSession, key: str) -> AgentApproval | None:
    stmt = select(AgentApproval).where(AgentApproval.idempotency_key == key)
    return (await session.execute(stmt)).scalars().first()


async def _claim(
    session: AsyncSession, approval_id: int, status: str, actor_id: int, comment: str | None
) -> bool:
    result = await session.execute(
        update(AgentApproval)
        .where(AgentApproval.id == approval_id, AgentApproval.status == APPROVAL_PENDING)
        .values(status=status, decided_at=_now(), decision_by=actor_id, decision_comment=comment)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return bool(result.rowcount == 1)


async def _set_status(
    session: AsyncSession, approval: AgentApproval, status: str, actor_id: int, comment: str | None
) -> None:
    approval.status = status
    approval.decided_at = _now()
    approval.decision_by = actor_id
    approval.decision_comment = comment
    await session.commit()


def _is_expired(approval: AgentApproval) -> bool:
    if approval.expires_at is None:
        return False
    expires = approval.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=UTC)
    return expires <= _now()


__all__ = [
    "ApprovalDecision",
    "decide",
    "expire_stale",
    "get_for_thread",
    "list_pending",
    "request_approval",
    "serialize",
]
