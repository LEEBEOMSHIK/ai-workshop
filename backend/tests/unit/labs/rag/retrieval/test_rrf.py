import pytest

from ai_workshop.labs.rag.retrieval.domain import RankedHit
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse


def test_rrf_preserves_raw_branch_scores_without_inventing_missing_scores():
    from ai_workshop.labs.rag.retrieval.domain import DenseHit, SparseHit
    from tests.unit.labs.rag.highlighting.test_evidence_selector import _source

    chunk = _source(1, "synthetic").chunk
    hit = rrf_fuse([SparseHit(chunk, 2, 8.2)], [DenseHit(chunk, 1, 0.77)])[0]
    assert hit.sparse_score == 8.2
    assert hit.dense_score == 0.77
    assert hit.score == pytest.approx(1 / 62 + 1 / 61)
    assert rrf_fuse([RankedHit("unscored", 1)], [])[0].dense_score is None


def test_rrf_orders_disjoint_hits_by_rank_then_immutable_chunk_id() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("s1", 1), RankedHit("s2", 2)],
        dense=[RankedHit("d1", 1), RankedHit("d2", 2)],
        k=60,
    )

    assert [hit.chunk_id for hit in result] == ["d1", "s1", "d2", "s2"]


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


def test_rrf_breaks_all_numeric_ties_by_immutable_chunk_id() -> None:
    result = rrf_fuse(
        sparse=[RankedHit("z", 1), RankedHit("a", 1)],
        dense=[],
        k=60,
    )

    assert [hit.chunk_id for hit in result] == ["a", "z"]


def test_rrf_rejects_non_positive_rank() -> None:
    with pytest.raises(ValueError, match="positive"):
        rrf_fuse(sparse=[RankedHit("a", 0)], dense=[], k=60)
