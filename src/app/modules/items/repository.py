"""Item persistence.

All writes go through explicit statements so the concurrency-sensitive ones
(stock decrement) are a single atomic ``UPDATE ... WHERE inventory >= :qty`` -
correct on PostgreSQL *and* SQLite, unlike ``SELECT ... FOR UPDATE`` which SQLite
silently ignores.
"""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.modules.items.models import ItemModel, TagModel, favourites


async def list_items(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None = None,
    is_offer: bool | None = None,
    owner_id: int | None = None,
    in_stock_only: bool = False,
) -> tuple[list[ItemModel], int]:
    filters = []
    if is_offer is not None:
        filters.append(ItemModel.is_offer == is_offer)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(or_(ItemModel.name.ilike(pattern), ItemModel.image_path.ilike(pattern)))
    if owner_id is not None:
        filters.append(ItemModel.owner_id == owner_id)
    if in_stock_only:
        filters.append(ItemModel.inventory > 0)

    total = int(
        await session.scalar(select(func.count()).select_from(ItemModel).where(*filters)) or 0
    )
    stmt = select(ItemModel).where(*filters).order_by(ItemModel.id.desc()).offset(skip).limit(limit)
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def get_by_id(session: AsyncSession, item_id: int) -> ItemModel | None:
    stmt = (
        select(ItemModel)
        .options(selectinload(ItemModel.tags), selectinload(ItemModel.favourited_by))
        .where(ItemModel.id == item_id)
    )
    return (await session.execute(stmt)).scalars().first()


async def list_for_owner(session: AsyncSession, owner_id: int) -> list[ItemModel]:
    stmt = select(ItemModel).where(ItemModel.owner_id == owner_id).order_by(ItemModel.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def create(session: AsyncSession, item: ItemModel) -> ItemModel:
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_item(session: AsyncSession, item: ItemModel) -> None:
    await session.delete(item)
    await session.commit()


async def update_fields(
    session: AsyncSession, item: ItemModel, values: dict[str, object]
) -> ItemModel:
    for key, value in values.items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


async def decrement_stock(session: AsyncSession, item_id: int, quantity: int = 1) -> bool:
    """Atomically reserve stock. Returns False when there is not enough left."""

    statement = (
        update(ItemModel)
        .where(ItemModel.id == item_id, ItemModel.inventory >= quantity)
        .values(
            inventory=ItemModel.inventory - quantity,
            # PostgreSQL/SQLite evaluate the right-hand side against the old row,
            # so this is "new inventory == 0".
            is_sold=(ItemModel.inventory - quantity) <= 0,
        )
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return bool(result.rowcount == 1)


async def set_embedding(session: AsyncSession, item_id: int, vector: list[float]) -> bool:
    result = await session.execute(
        update(ItemModel)
        .where(ItemModel.id == item_id)
        .values(embedding=vector)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return bool(result.rowcount == 1)


async def search_by_text_embedding(
    session: AsyncSession, vector: list[float], *, limit: int = 5
) -> list[tuple[ItemModel, float]]:
    """pgvector cosine search. Caller must ensure the dialect is PostgreSQL."""

    distance = ItemModel.embedding.cosine_distance(vector)
    stmt = (
        select(ItemModel, distance.label("distance"))
        .where(
            ItemModel.is_offer.is_(True),
            ItemModel.inventory > 0,
            ItemModel.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], float(1.0 - row[1])) for row in rows]


async def list_with_image_embedding(session: AsyncSession) -> list[ItemModel]:
    stmt = select(ItemModel).where(ItemModel.image_embedding.is_not(None)).order_by(ItemModel.id)
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #
async def list_tags(session: AsyncSession) -> list[TagModel]:
    return list((await session.execute(select(TagModel).order_by(TagModel.id))).scalars().all())


async def get_tag_by_name(session: AsyncSession, name: str) -> TagModel | None:
    stmt = select(TagModel).where(func.lower(TagModel.name) == name.strip().lower())
    return (await session.execute(stmt)).scalars().first()


async def get_tag_by_id(session: AsyncSession, tag_id: int) -> TagModel | None:
    return await session.get(TagModel, tag_id)


async def get_tags_by_ids(session: AsyncSession, tag_ids: list[int]) -> list[TagModel]:
    if not tag_ids:
        return []
    unique_ids = sorted({int(tag_id) for tag_id in tag_ids})
    stmt = select(TagModel).where(TagModel.id.in_(unique_ids))
    return list((await session.execute(stmt)).scalars().all())


async def create_tag(session: AsyncSession, name: str) -> TagModel:
    tag = TagModel(name=name.strip())
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


async def delete_tag(session: AsyncSession, tag: TagModel) -> None:
    from src.app.modules.items.models import item_tag

    # Delete the association rows with SQL instead of iterating ``tag.items``:
    # that relationship is lazy, and touching it inside async code raises
    # MissingGreenlet.
    await session.execute(delete(item_tag).where(item_tag.c.tag_id == tag.id))
    await session.delete(tag)
    await session.commit()


# --------------------------------------------------------------------------- #
# Favourites
# --------------------------------------------------------------------------- #
async def toggle_favourite(session: AsyncSession, item: ItemModel, user_id: int) -> bool:
    """Return True when the item is now favourited, False when removed."""

    existing_ids = {user.id for user in item.favourited_by}
    if user_id in existing_ids:
        await session.execute(
            delete(favourites).where(
                favourites.c.user_id == user_id,
                favourites.c.item_id == item.id,
            )
        )
        await session.commit()
        await session.refresh(item, attribute_names=["favourited_by"])
        return False
    await session.execute(favourites.insert().values(user_id=user_id, item_id=item.id))
    await session.commit()
    await session.refresh(item, attribute_names=["favourited_by"])
    return True


__all__ = [
    "create",
    "create_tag",
    "decrement_stock",
    "delete_item",
    "delete_tag",
    "get_by_id",
    "get_tag_by_id",
    "get_tag_by_name",
    "get_tags_by_ids",
    "list_for_owner",
    "list_items",
    "list_tags",
    "list_with_image_embedding",
    "search_by_text_embedding",
    "set_embedding",
    "toggle_favourite",
    "update_fields",
]
