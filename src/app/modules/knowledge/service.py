"""Policy retrieval ("RAG") used by the agent's knowledge tool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.modules.knowledge import repository
from src.app.modules.knowledge.models import KnowledgeModel
from src.app.shared.hybrid_rrf import HybridHit


async def search_policy_hybrid(
    session: AsyncSession,
    query: str,
    *,
    embeddings: Any | None,
    limit: int = 3,
) -> tuple[list[HybridHit[KnowledgeModel]], str]:
    """Semantic + lexical policy retrieval fused with RRF."""

    cleaned = query.strip()
    if not cleaned:
        return [], "empty"

    vector: list[float] | None = None
    if (
        embeddings is not None
        and getattr(embeddings, "enabled", False)
        and session.bind is not None
        and session.bind.dialect.name == "postgresql"
    ):
        vector = await embeddings.embed(cleaned)

    hits = await repository.hybrid_search(session, cleaned, vector=vector, limit=limit)
    return hits, "hybrid" if vector is not None else "lexical"


async def search_policy(
    session: AsyncSession,
    query: str,
    *,
    embeddings: Any | None,
    limit: int = 3,
) -> tuple[list[KnowledgeModel], str]:
    hits, mode = await search_policy_hybrid(session, query, embeddings=embeddings, limit=limit)
    return [hit.item for hit in hits], mode


__all__ = ["search_policy", "search_policy_hybrid"]
