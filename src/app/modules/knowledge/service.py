"""Policy retrieval ("RAG") used by the agent's knowledge tool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.modules.knowledge import repository
from src.app.modules.knowledge.models import KnowledgeModel


async def search_policy(
    session: AsyncSession,
    query: str,
    *,
    embeddings: Any | None,
    limit: int = 3,
) -> tuple[list[KnowledgeModel], str]:
    cleaned = query.strip()
    if not cleaned:
        return [], "empty"

    if embeddings is not None and getattr(embeddings, "enabled", False):
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            vector = await embeddings.embed(cleaned)
            rows = await repository.search_by_embedding(session, vector, limit=limit)
            if rows:
                return [doc for doc, _score in rows], "pgvector"

    docs = await repository.search_lexical(session, cleaned, limit=limit)
    return docs, "lexical"


__all__ = ["search_policy"]
