"""RRF fusion is pure maths, so it gets exhaustive edge-case tests."""

from __future__ import annotations

import pytest
from src.app.shared.hybrid_rrf import fuse_ranked


def _key(value: str) -> str:
    return value


def test_empty_inputs_produce_no_hits() -> None:
    assert fuse_ranked([], [], key=_key) == []


def test_single_retriever_keeps_order_and_marks_reason() -> None:
    hits = fuse_ranked(["a", "b"], [], key=_key)
    assert [hit.item for hit in hits] == ["a", "b"]
    assert [hit.match_reason for hit in hits] == ["semantic", "semantic"]
    assert hits[0].score == pytest.approx(1 / 61)

    lexical = fuse_ranked([], ["b", "a"], key=_key)
    assert [hit.item for hit in lexical] == ["b", "a"]
    assert all(hit.match_reason == "lexical" for hit in lexical)


def test_overlap_is_hybrid_and_beats_single_retriever_hits() -> None:
    hits = fuse_ranked(["a", "shared"], ["shared", "b"], key=_key)
    by_item = {hit.item: hit for hit in hits}

    assert by_item["shared"].match_reason == "hybrid"
    assert by_item["shared"].semantic_rank == 2
    assert by_item["shared"].lexical_rank == 1
    assert by_item["shared"].score == pytest.approx(1 / 62 + 1 / 61)
    assert hits[0].item == "shared"
    assert by_item["a"].match_reason == "semantic"
    assert by_item["b"].match_reason == "lexical"


def test_duplicate_keys_are_deduplicated_and_first_item_wins() -> None:
    class Doc:
        def __init__(self, doc_id: str, label: str) -> None:
            self.doc_id = doc_id
            self.label = label

    semantic = [Doc("1", "from-semantic")]
    lexical = [Doc("1", "from-lexical"), Doc("2", "second")]
    hits = fuse_ranked(semantic, lexical, key=lambda doc: doc.doc_id)

    assert len(hits) == 2
    first = next(hit for hit in hits if hit.item.doc_id == "1")
    assert first.item.label == "from-semantic"
    assert first.match_reason == "hybrid"


def test_k_controls_dampening_and_must_be_positive() -> None:
    low_k = fuse_ranked(["a"], [], key=_key, k=1)
    high_k = fuse_ranked(["a"], [], key=_key, k=100)
    assert low_k[0].score > high_k[0].score
    assert low_k[0].score == pytest.approx(0.5)

    with pytest.raises(ValueError, match="k must be >= 1"):
        fuse_ranked(["a"], [], key=_key, k=0)
