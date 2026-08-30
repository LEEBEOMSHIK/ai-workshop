from collections.abc import Sequence
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    AnswerStatus,
    ConflictState,
    EvidenceSource,
    HighlightKind,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.retrieval.domain import RetrievedChunk

WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
INDEX_BUILD_ID = UUID("20000000-0000-0000-0000-000000000002")


class RecordingEmbedding:
    dimension = 2

    def __init__(
        self,
        *,
        query_vector: list[float] | None = None,
        document_vectors: list[list[float]] | None = None,
    ) -> None:
        self.query_vector = query_vector or [1.0, 0.0]
        self.document_vectors = document_vectors or []
        self.encoded_documents: list[str] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_query(self, text: str) -> list[float]:
        assert text
        return list(self.query_vector)

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.encoded_documents = list(texts)
        assert len(self.document_vectors) == len(self.encoded_documents)
        return [list(item) for item in self.document_vectors]


def _source(
    value: int,
    text: str,
    *,
    location: SourceLocation | None = None,
    projection_id: UUID | None = None,
) -> EvidenceSource:
    chunk_id = UUID(f"30000000-0000-0000-0000-{value:012d}")
    exact_projection_id = projection_id or UUID(
        f"40000000-0000-0000-0000-{value:012d}"
    )
    evidence = EvidenceUnit(
        id=UUID(f"50000000-0000-0000-0000-{value:012d}"),
        chunk_id=chunk_id,
        projection_id=exact_projection_id,
        ordinal=0,
        text=text,
        location=location
        or SourceLocation(
            element_id=UUID(f"60000000-0000-0000-0000-{value:012d}"),
            page=None,
            char_start=100 * value,
            char_end=100 * value + len(text),
            bbox=None,
        ),
    )
    chunk = RetrievedChunk(
        chunk_id=chunk_id,
        projection_id=exact_projection_id,
        asset_version_id=UUID(f"70000000-0000-0000-0000-{value:012d}"),
        workspace_id=WORKSPACE_ID,
        folder_id=None,
        index_build_id=INDEX_BUILD_ID,
        title=f"source-{value}.txt",
        section_path=("약관",),
        text=text,
        evidence_units=(evidence,),
    )
    return EvidenceSource(
        document_id=UUID(f"80000000-0000-0000-0000-{value:012d}"),
        asset_version_number=value,
        media_type="text/plain",
        chunk=chunk,
        fused_score=1.0 / value,
    )


def _policy(
    *,
    min_semantic_score: float = 0.8,
    min_keyword_coverage: float = 1.0,
) -> AnswerPolicy:
    return AnswerPolicy(
        min_semantic_score=min_semantic_score,
        min_keyword_coverage=min_keyword_coverage,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )


def test_v1_answer_policy_rejects_optional_provenance() -> None:
    with pytest.raises(ValueError, match="complete provenance"):
        AnswerPolicy(
            min_semantic_score=0.8,
            min_keyword_coverage=1.0,
            require_complete_provenance=False,
            conflict_mode="separate_sources",
        )


def test_selector_rejects_a_policy_mutated_outside_the_configuration_boundary() -> None:
    policy = _policy()
    object.__setattr__(policy, "require_complete_provenance", False)

    with pytest.raises(ValueError, match="complete provenance"):
        EvidenceSelector(RecordingEmbedding()).select(
            query="환매 수수료",
            sources=(_source(1, "환매 수수료는 1%입니다."),),
            policy=policy,
        )


def test_exact_keyword_evidence_is_supported_without_semantic_embedding() -> None:
    embedding = RecordingEmbedding()
    selector = EvidenceSelector(embedding)

    result = selector.select(
        query="환매 수수료",
        sources=(_source(1, "환매 수수료는 1%입니다."),),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.answer is not None
    assert result.answer.excerpt == "환매 수수료는 1%입니다."
    assert all(item.kind is HighlightKind.KEYWORD for item in result.answer.highlights)
    assert embedding.encoded_documents == []


def test_semantic_evidence_selects_and_highlights_the_whole_unit() -> None:
    source = _source(1, "가입 후 해지 조건입니다.")
    embedding = RecordingEmbedding(document_vectors=[[0.9, 0.1]])

    result = EvidenceSelector(embedding).select(
        query="환매 요건",
        sources=(source,),
        policy=_policy(min_semantic_score=0.85),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.answer is not None
    assert len(result.answer.highlights) == 1
    highlight = result.answer.highlights[0]
    assert highlight.kind is HighlightKind.SEMANTIC
    assert (highlight.char_start, highlight.char_end) == (
        source.chunk.evidence_units[0].location.char_start,
        source.chunk.evidence_units[0].location.char_end,
    )
    assert embedding.encoded_documents == ["가입 후 해지 조건입니다."]


def test_semantic_evidence_selects_the_highest_scoring_qualifying_unit() -> None:
    lower = _source(1, "가입 후 해지 조건입니다.")
    higher = _source(2, "중도 환매가 가능한 요건입니다.")
    embedding = RecordingEmbedding(
        document_vectors=[[0.8, 0.6], [0.99, 0.01]],
    )

    result = EvidenceSelector(embedding).select(
        query="상품 유동성",
        sources=(lower, higher),
        policy=_policy(min_semantic_score=0.75),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.answer is not None
    assert result.answer.excerpt == higher.chunk.evidence_units[0].text
    assert result.answer.semantic_score is not None
    assert result.answer.semantic_score > 0.99


def test_missing_provenance_is_normal_insufficient_evidence() -> None:
    source = _source(1, "환매 수수료는 1%입니다.")
    incomplete = EvidenceUnit(
        id=source.chunk.evidence_units[0].id,
        chunk_id=source.chunk.chunk_id,
        projection_id=None,
        ordinal=0,
        text=source.chunk.evidence_units[0].text,
        location=source.chunk.evidence_units[0].location,
    )
    source = EvidenceSource(
        document_id=source.document_id,
        asset_version_number=source.asset_version_number,
        media_type=source.media_type,
        chunk=RetrievedChunk(
            chunk_id=source.chunk.chunk_id,
            projection_id=source.chunk.projection_id,
            asset_version_id=source.chunk.asset_version_id,
            workspace_id=source.chunk.workspace_id,
            folder_id=source.chunk.folder_id,
            index_build_id=source.chunk.index_build_id,
            title=source.chunk.title,
            section_path=source.chunk.section_path,
            text=source.chunk.text,
            evidence_units=(incomplete,),
        ),
        fused_score=source.fused_score,
    )

    result = EvidenceSelector(RecordingEmbedding()).select(
        query="환매 수수료",
        sources=(source,),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.answer is None
    assert result.warnings == ("projection_provenance_incomplete",)


def test_incomplete_pdf_location_never_supports_direct_keyword_evidence() -> None:
    source = _source(
        1,
        "환매 수수료는 1%입니다.",
        location=SourceLocation(
            element_id=UUID("60000000-0000-0000-0000-000000000001"),
            page=1,
            char_start=0,
            char_end=15,
            bbox=None,
        ),
    )
    source = EvidenceSource(
        document_id=source.document_id,
        asset_version_number=source.asset_version_number,
        media_type="application/pdf",
        chunk=source.chunk,
        fused_score=source.fused_score,
    )

    result = EvidenceSelector(RecordingEmbedding()).select(
        query="환매 수수료",
        sources=(source,),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.answer is None
    assert result.warnings == ("pdf_bbox_incomplete",)


def test_conflicting_qualifying_sources_remain_separate() -> None:
    result = EvidenceSelector(RecordingEmbedding()).select(
        query="최소 가입 금액",
        sources=(
            _source(1, "최소 가입 금액은 100만원입니다."),
            _source(2, "최소 가입 금액은 200만원입니다."),
        ),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.answer is not None
    assert result.answer.excerpt == "최소 가입 금액은 100만원입니다."
    assert result.conflict_state is ConflictState.SEPARATE_SOURCES
    assert [item.excerpt for item in result.conflicts] == [
        "최소 가입 금액은 200만원입니다."
    ]


def test_same_numeric_conclusion_with_different_wording_is_not_a_conflict() -> None:
    result = EvidenceSelector(RecordingEmbedding()).select(
        query="최소 가입 금액",
        sources=(
            _source(1, "최소 가입 금액은 100만원입니다."),
            _source(2, "100만원이 최소 가입 금액으로 적용됩니다."),
        ),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.conflict_state is ConflictState.NONE
    assert result.conflicts == ()


def test_shared_query_words_without_the_same_claim_phrase_are_not_a_conflict() -> None:
    result = EvidenceSelector(RecordingEmbedding()).select(
        query="최소 가입 금액",
        sources=(
            _source(1, "최소 가입 금액 100만원"),
            _source(2, "최소 조건 가입 대상 금액 200만원"),
        ),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.conflict_state is ConflictState.NONE
    assert result.conflicts == ()


def test_explicit_opposite_polarity_for_the_same_claim_is_a_conflict() -> None:
    result = EvidenceSelector(RecordingEmbedding()).select(
        query="중도 환매 신청",
        sources=(
            _source(1, "중도 환매 신청은 가능합니다."),
            _source(2, "중도 환매 신청은 불가능합니다."),
        ),
        policy=_policy(),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.conflict_state is ConflictState.SEPARATE_SOURCES
    assert [item.excerpt for item in result.conflicts] == [
        "중도 환매 신청은 불가능합니다."
    ]


def test_keyword_primary_is_compared_with_semantic_only_conflicting_evidence() -> None:
    primary = _source(1, "최소 가입 금액 기준은 100만원입니다.")
    semantic_conflict = _source(2, "최소 가입 금액은 200만원입니다.")
    embedding = RecordingEmbedding(document_vectors=[[0.99, 0.01]])

    result = EvidenceSelector(embedding).select(
        query="최소 가입 금액 기준",
        sources=(primary, semantic_conflict),
        policy=_policy(min_semantic_score=0.8),
    )

    assert result.status is AnswerStatus.SUPPORTED
    assert result.answer is not None
    assert result.answer.excerpt == primary.chunk.evidence_units[0].text
    assert result.answer.keyword_coverage == 1.0
    assert [item.excerpt for item in result.conflicts] == [
        semantic_conflict.chunk.evidence_units[0].text
    ]
    assert embedding.encoded_documents == [semantic_conflict.chunk.evidence_units[0].text]


def test_related_but_subthreshold_evidence_stays_insufficient() -> None:
    embedding = RecordingEmbedding(document_vectors=[[0.0, 1.0]])

    result = EvidenceSelector(embedding).select(
        query="환매 수수료",
        sources=(_source(1, "관련 운용 지침입니다."),),
        policy=_policy(min_semantic_score=0.8),
    )

    assert result.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.answer is None
    assert result.conflicts == ()
