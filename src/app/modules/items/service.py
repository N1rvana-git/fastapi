"""Item business rules (listing CRUD, tags, favourites, search, ingestion)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.cache import TwoLevelCache
from src.app.core.exceptions import (
    BusinessRuleViolation,
    FeatureUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from src.app.core.logging import get_logger
from src.app.modules.items import repository
from src.app.modules.items.models import ItemModel, TagModel
from src.app.modules.items.schemas import ItemCreate, ItemUpdate
from src.app.modules.users.models import UserModel
from src.app.shared.hybrid_rrf import HybridHit

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def list_items(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None = None,
    is_offer: bool | None = None,
    owner_id: int | None = None,
) -> tuple[list[ItemModel], int]:
    return await repository.list_items(
        session, skip=skip, limit=limit, search=search, is_offer=is_offer, owner_id=owner_id
    )


async def get_item_or_404(session: AsyncSession, item_id: int) -> ItemModel:
    item = await repository.get_by_id(session, item_id)
    if item is None:
        raise NotFoundError("商品不存在", details={"item_id": item_id})
    return item


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
async def create_item(
    session: AsyncSession,
    payload: ItemCreate,
    *,
    owner_id: int,
    dispatcher: Any | None = None,
) -> ItemModel:
    tags = await _resolve_tags(session, payload.tag_ids)
    values = payload.model_dump(exclude={"tag_ids"})
    item = ItemModel(**values, owner_id=owner_id)
    item.tags = tags
    await repository.create(session, item)
    logger.info(
        "item created",
        extra={"ctx_item_id": item.id, "ctx_owner_id": owner_id, "ctx_tag_count": len(tags)},
    )
    await _enqueue_embedding(dispatcher, item.id)
    return item


async def update_item(
    session: AsyncSession,
    item_id: int,
    payload: ItemUpdate,
    *,
    actor: UserModel,
) -> ItemModel:
    item = await get_item_or_404(session, item_id)
    _ensure_can_manage(item, actor)

    values = payload.model_dump(exclude_unset=True, exclude={"tag_ids"})
    if payload.tag_ids is not None:
        item.tags = await _resolve_tags(session, payload.tag_ids)
    for key, value in values.items():
        setattr(item, key, value)

    # Inventory is the source of truth for "sold out".
    if "inventory" in values and item.inventory is not None:
        item.is_sold = item.inventory <= 0

    await repository.update_fields(session, item, {})
    logger.info("item updated", extra={"ctx_item_id": item.id, "ctx_fields": sorted(values)})
    return item


async def delete_item(session: AsyncSession, item_id: int, *, actor: UserModel) -> None:
    item = await get_item_or_404(session, item_id)
    _ensure_can_manage(item, actor)
    await repository.delete_item(session, item)
    logger.info("item deleted", extra={"ctx_item_id": item_id, "ctx_actor_id": actor.id})


async def toggle_favourite(
    session: AsyncSession, item_id: int, *, user: UserModel
) -> tuple[bool, int]:
    item = await get_item_or_404(session, item_id)
    favorited = await repository.toggle_favourite(session, item, user.id)
    return favorited, len(item.favourited_by)


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #
async def list_tags(
    session: AsyncSession, *, cache: TwoLevelCache | None = None
) -> list[dict[str, Any]]:
    async def loader() -> list[dict[str, Any]]:
        tags = await repository.list_tags(session)
        return [{"id": tag.id, "name": tag.name} for tag in tags]

    if cache is None:
        return await loader()
    return await cache.get_or_load("items:tags", loader)


async def create_tag(session: AsyncSession, name: str, *, cache: Any | None = None) -> TagModel:
    existing = await repository.get_tag_by_name(session, name)
    if existing is not None:
        raise ValidationError("该标签已存在", details={"name": name})
    try:
        tag = await repository.create_tag(session, name)
    except IntegrityError:
        # Concurrent creation of the same tag: return the winner instead of 500.
        await session.rollback()
        existing = await repository.get_tag_by_name(session, name)
        if existing is None:
            raise
        return existing
    if cache is not None:
        await cache.invalidate("items:tags")
    return tag


async def delete_tag(session: AsyncSession, tag_id: int, *, cache: Any | None = None) -> None:
    tag = await repository.get_tag_by_id(session, tag_id)
    if tag is None:
        raise NotFoundError("标签不存在", details={"tag_id": tag_id})
    await repository.delete_tag(session, tag)
    if cache is not None:
        await cache.invalidate("items:tags")


async def _resolve_tags(session: AsyncSession, tag_ids: Sequence[int]) -> list[TagModel]:
    if not tag_ids:
        return []
    tags = await repository.get_tags_by_ids(session, list(tag_ids))
    found = {tag.id for tag in tags}
    missing = sorted(set(tag_ids) - found)
    if missing:
        raise ValidationError("部分标签不存在", details={"missing_tag_ids": missing})
    return tags


# --------------------------------------------------------------------------- #
# Search (vector when the database supports it, Python cosine otherwise)
# --------------------------------------------------------------------------- #
async def search_by_image(
    session: AsyncSession,
    image_bytes: bytes,
    *,
    vision: Any,
    limit: int = 5,
) -> tuple[list[tuple[ItemModel, float]], str]:
    if vision is None or not getattr(vision, "available", False):
        raise FeatureUnavailableError("以图搜图功能在当前部署中不可用")
    query_vector = await vision.image_embedding(image_bytes)
    items = await repository.list_with_image_embedding(session)
    scored = _score_candidates(query_vector, items, attribute="image_embedding")
    return scored[:limit], "python"


async def search_by_text_hybrid(
    session: AsyncSession,
    text: str,
    *,
    embeddings: Any,
    vision: Any,
    limit: int = 5,
    keyword: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_by: str = "relevance",
) -> tuple[list[HybridHit[ItemModel]], str]:
    """Hybrid retrieval: vector leg + keyword/structured leg fused with RRF."""

    cleaned = (text or keyword or "").strip()
    if not cleaned:
        raise ValidationError("搜索内容不能为空")

    vector: list[float] | None = None
    if (
        embeddings is not None
        and getattr(embeddings, "enabled", False)
        and session.bind is not None
        and session.bind.dialect.name == "postgresql"
    ):
        vector = await embeddings.embed(cleaned)

    hits = await repository.hybrid_search(
        session,
        keyword=keyword or cleaned,
        vector=vector,
        category=category,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        limit=limit,
    )

    # CLIP cross-modal fallback only when neither retriever found anything.
    if not hits and vision is not None and getattr(vision, "available", False):
        vector = await vision.text_embedding(cleaned)
        items = await repository.list_with_image_embedding(session)
        scored = _score_candidates(vector, items, attribute="image_embedding")
        if scored:
            return [
                HybridHit(
                    item=item,
                    score=score,
                    semantic_rank=rank,
                    lexical_rank=None,
                    match_reason="semantic",
                )
                for rank, (item, score) in enumerate(scored[:limit], start=1)
            ], "python"

    return hits, "hybrid" if vector is not None else "lexical"


async def search_by_text(
    session: AsyncSession,
    text: str,
    *,
    embeddings: Any,
    vision: Any,
    limit: int = 5,
) -> tuple[list[tuple[ItemModel, float]], str]:
    hits, mode = await search_by_text_hybrid(
        session, text, embeddings=embeddings, vision=vision, limit=limit
    )
    return [(hit.item, hit.score) for hit in hits], mode


def _score_candidates(
    query_vector: Sequence[float], items: Sequence[ItemModel], *, attribute: str
) -> list[tuple[ItemModel, float]]:
    import numpy as np

    query = np.asarray(query_vector, dtype=float)
    query_norm = float(np.linalg.norm(query)) or 1e-10
    scored: list[tuple[ItemModel, float]] = []
    for item in items:
        raw = getattr(item, attribute, None)
        if raw is None:
            continue
        candidate = np.asarray(list(raw), dtype=float)
        if candidate.shape != query.shape:
            continue
        score = float(
            np.dot(query, candidate) / (query_norm * (float(np.linalg.norm(candidate)) or 1e-10))
        )
        scored.append((item, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


async def _enqueue_embedding(dispatcher: Any | None, item_id: int) -> None:
    if dispatcher is None:
        return
    try:
        await dispatcher.enqueue("items.embed_item", item_id=item_id)
    except Exception:
        logger.exception("failed to enqueue embedding task", extra={"ctx_item_id": item_id})


# --------------------------------------------------------------------------- #
# Authorization helpers
# --------------------------------------------------------------------------- #
def _ensure_can_manage(item: ItemModel, actor: UserModel) -> None:
    if actor.role == "admin":
        return
    if item.owner_id != actor.id:
        raise PermissionDeniedError("无权操作该商品", details={"item_id": item.id})


def ensure_purchasable(item: ItemModel, *, quantity: int = 1) -> None:
    """Cheap pre-checks only.

    Stock itself is *not* validated here: availability must be decided by the
    atomic ``UPDATE ... WHERE inventory >= qty`` so two concurrent buyers cannot
    both pass a check that is already stale.  Sellers also cannot sell their own
    listing, which is enforced by the order service.
    """

    if item.is_offer is False:
        raise BusinessRuleViolation("求购贴不支持下单")
    if quantity < 1:
        raise BusinessRuleViolation("购买数量必须大于 0")


__all__ = [
    "create_item",
    "create_tag",
    "delete_item",
    "delete_tag",
    "ensure_purchasable",
    "get_item_or_404",
    "list_items",
    "list_tags",
    "search_by_image",
    "search_by_text",
    "search_by_text_hybrid",
    "toggle_favourite",
    "update_item",
]
