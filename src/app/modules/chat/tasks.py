"""Background tasks for the chat module (zombie approval cleanup)."""

from __future__ import annotations

from src.app.core.logging import get_logger
from src.app.core.tasks import task

logger = get_logger(__name__)


@task("chat.expire_approvals", max_attempts=2)
async def expire_approvals() -> int:
    """Close approvals nobody decided (prevents permanently half-suspended threads)."""

    from src.app.container import get_container
    from src.app.modules.chat import approvals

    container = get_container()
    async with container.database.session() as session:
        count = await approvals.expire_stale(session)
    if count:
        logger.info("expired zombie approvals", extra={"ctx_count": count})
    return count


@task("chat.purge_stale_streams", max_attempts=1)
async def purge_stale_streams() -> None:
    from src.app.container import get_container

    buffer = get_container().stream_buffer
    purge = getattr(buffer, "purge_expired", None)
    if callable(purge):
        purge()


__all__ = ["expire_approvals", "purge_stale_streams"]
