"""Task definitions for Feishu messaging and order notifications."""

from __future__ import annotations

from typing import Any

from src.app.core.logging import get_logger
from src.app.core.tasks import task

logger = get_logger(__name__)


@task("feishu.process_event", max_attempts=3, backoff_seconds=3.0)
async def process_event(event: dict[str, Any]) -> None:
    from src.app.container import get_container

    await get_container().feishu_service.handle_event(event)


@task("notifications.order_alert", max_attempts=3, backoff_seconds=3.0)
async def order_alert(item_id: int, buyer_id: int, address: str, quantity: int = 1) -> None:
    from src.app.container import get_container

    await get_container().feishu_service.notify_order(
        item_id=item_id, buyer_id=buyer_id, address=address, quantity=quantity
    )


__all__ = ["order_alert", "process_event"]
