"""Reciprocal Rank Fusion (RRF) for hybrid retrieval.

Pure Python, no DB/LLM imports: repositories feed it ranked id/object lists and
the fusion logic stays trivially unit-testable.  Score for a document is
``sum(1 / (k + rank_i))`` over the lists it appears in (rank is 1-based), the
standard Cormack et al. formulation with ``k=60`` as the default dampening.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")
MatchReason = Literal["semantic", "lexical", "hybrid"]


@dataclass(frozen=True)
class HybridHit(Generic[T]):
    item: T
    score: float
    semantic_rank: int | None
    lexical_rank: int | None
    match_reason: MatchReason


def fuse_ranked(
    semantic: Sequence[T],
    lexical: Sequence[T],
    *,
    key: Callable[[T], Hashable],
    k: int = 60,
) -> list[HybridHit[T]]:
    """Fuse two ranked lists, deduplicating by ``key``.

    The lists are already ordered best-first (rank 1 = first element).  A hit
    found by both retrievers is reported as ``hybrid`` and receives both RRF
    contributions, which is what makes it outrank single-retriever results.
    """

    if k < 1:
        raise ValueError("k must be >= 1")

    scores: dict[Hashable, float] = {}
    items: dict[Hashable, T] = {}
    semantic_ranks: dict[Hashable, int] = {}
    lexical_ranks: dict[Hashable, int] = {}

    for rank, item in enumerate(semantic, start=1):
        doc_key = key(item)
        items.setdefault(doc_key, item)
        semantic_ranks[doc_key] = rank
        scores[doc_key] = scores.get(doc_key, 0.0) + 1.0 / (k + rank)

    for rank, item in enumerate(lexical, start=1):
        doc_key = key(item)
        items.setdefault(doc_key, item)
        lexical_ranks[doc_key] = rank
        scores[doc_key] = scores.get(doc_key, 0.0) + 1.0 / (k + rank)

    hits: list[HybridHit[T]] = []
    for doc_key, score in scores.items():
        in_semantic = doc_key in semantic_ranks
        in_lexical = doc_key in lexical_ranks
        reason: MatchReason
        if in_semantic and in_lexical:
            reason = "hybrid"
        elif in_semantic:
            reason = "semantic"
        else:
            reason = "lexical"
        hits.append(
            HybridHit(
                item=items[doc_key],
                score=score,
                semantic_rank=semantic_ranks.get(doc_key),
                lexical_rank=lexical_ranks.get(doc_key),
                match_reason=reason,
            )
        )

    hits.sort(
        key=lambda hit: (
            -hit.score,
            hit.semantic_rank if hit.semantic_rank is not None else 10**9,
            hit.lexical_rank if hit.lexical_rank is not None else 10**9,
        )
    )
    return hits


__all__ = ["HybridHit", "MatchReason", "fuse_ranked"]
