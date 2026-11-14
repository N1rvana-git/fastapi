"""Knowledge-base persistence."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.modules.knowledge.models import KnowledgeModel


async def search_lexical(
    session: AsyncSession, query: str, *, limit: int = 3
) -> list[KnowledgeModel]:
    pattern = f"%{query.strip()}%"
    stmt = (
        select(KnowledgeModel)
        .where(or_(KnowledgeModel.title.ilike(pattern), KnowledgeModel.content.ilike(pattern)))
        .order_by(KnowledgeModel.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def search_by_embedding(
    session: AsyncSession, vector: list[float], *, limit: int = 3
) -> list[tuple[KnowledgeModel, float]]:
    distance = KnowledgeModel.embedding.cosine_distance(vector)
    stmt = (
        select(KnowledgeModel, distance.label("distance"))
        .where(KnowledgeModel.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], float(1.0 - row[1])) for row in rows]


async def list_all(session: AsyncSession, *, limit: int = 100) -> list[KnowledgeModel]:
    return list((await session.execute(select(KnowledgeModel).limit(limit))).scalars().all())


async def create(session: AsyncSession, doc: KnowledgeModel) -> KnowledgeModel:
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


__all__ = ["create", "list_all", "search_by_embedding", "search_lexical"]
