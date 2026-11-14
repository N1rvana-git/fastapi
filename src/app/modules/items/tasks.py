"""Background tasks for the item module (embedding enrichment)."""

from __future__ import annotations

from src.app.core.exceptions import FeatureUnavailableError
from src.app.core.logging import get_logger
from src.app.core.tasks import task

logger = get_logger(__name__)


@task("items.embed_item", max_attempts=3, backoff_seconds=5.0)
async def embed_item(item_id: int) -> None:
    """Compute the semantic embedding for a listing, out of the request path."""

    from src.app.container import get_container
    from src.app.modules.items import repository
    from src.app.modules.items.models import ItemModel

    container = get_container()
    async with container.database.session() as session:
        item = await session.get(ItemModel, item_id)
        if item is None:
            logger.info("embedding skipped: item gone", extra={"ctx_item_id": item_id})
            return
        text = f"{item.name} ￥{item.price} 库存{item.inventory}"
        try:
            vector = await container.embeddings.embed(text)
        except FeatureUnavailableError:
            logger.info("embedding skipped: provider unavailable", extra={"ctx_item_id": item_id})
            return
        await repository.set_embedding(session, item_id, vector)
    logger.info("item embedded", extra={"ctx_item_id": item_id})


__all__ = ["embed_item"]
