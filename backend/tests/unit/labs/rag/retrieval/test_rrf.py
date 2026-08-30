import pytest

from ai_workshop.labs.rag.retrieval.domain import RankedHit
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse


def test_rrf_orders_disjoint_hits_by_rank_then_branch_stably() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("s1", 1), RankedHit("s2", 2)],
        dense=[RankedHit("d1", 1), RankedHit("d2", 2)],
        k=60,
    )

    assert [hit.chunk_id for hit in result] == ["s1", "d1", "s2", "d2"]


def test_rrf_combines_duplicate_chunk() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("a", 1), RankedHit("b", 2)],
        dense=[RankedHit("b", 1), RankedHit("c", 2)],
        k=60,
    )

    assert result[0].chunk_id == "b"
    assert result[0].sparse_rank == 2
    assert result[0].dense_rank == 1
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_breaks_equal_score_by_best_individual_rank() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("best", 1), RankedHit("twice", 2)],
        dense=[RankedHit("twice", 2)],
        k=0,
    )

    assert [hit.chunk_id for hit in result] == ["best", "twice"]
    assert result[0].score == result[1].score == 1.0


def test_rrf_preserves_first_input_order_after_all_numeric_ties() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("z", 1), RankedHit("a", 1)],
        dense=[],
        k=60,
    )

    assert [hit.chunk_id for hit in result] == ["z", "a"]


def test_rrf_rejects_non_positive_rank() -> None:
    with pytest.raises(ValueError, match="positive"):
        rrf_fuse(sparse=[RankedHit("a", 0)], dense=[], k=60)
