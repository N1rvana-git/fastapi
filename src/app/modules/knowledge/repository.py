"""Knowledge-base persistence."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.modules.knowledge.models import KnowledgeModel
from src.app.shared.hybrid_rrf import HybridHit, fuse_ranked


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


async def hybrid_search(
    session: AsyncSession,
    query: str,
    *,
    vector: list[float] | None = None,
    limit: int = 3,
    pool_size: int = 10,
) -> list[HybridHit[KnowledgeModel]]:
    cleaned = query.strip()
    if not cleaned:
        return []

    semantic_docs: list[KnowledgeModel] = []
    if vector is not None:
        semantic_rows = await search_by_embedding(session, vector, limit=max(pool_size, limit))
        semantic_docs = [doc for doc, _score in semantic_rows]

    lexical_docs = await search_lexical(session, cleaned, limit=max(pool_size, limit))
    fused = fuse_ranked(semantic_docs, lexical_docs, key=lambda doc: doc.id)
    return fused[:limit]


async def create(session: AsyncSession, doc: KnowledgeModel) -> KnowledgeModel:
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


__all__ = ["create", "hybrid_search", "list_all", "search_by_embedding", "search_lexical"]
