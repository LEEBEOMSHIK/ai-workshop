import math
import re
import unicodedata
from collections.abc import Sequence
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    AnswerStatus,
    ConflictState,
    EvidenceAnswer,
    EvidenceSelection,
    EvidenceSource,
    HighlightKind,
    HighlightSpan,
    KeywordHighlightResult,
)

_TOKEN_PATTERN = re.compile(r"\w+|[%]+", re.UNICODE)


def _normalize_with_original_offsets(
    text: str,
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    normalized: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    previous_was_space = False
    unit_start = 0
    units: list[tuple[int, int]] = []
    for index in range(1, len(text)):
        character = text[index]
        if unicodedata.combining(character) == 0 and not unicodedata.category(
            character
        ).startswith("M"):
            units.append((unit_start, index))
            unit_start = index
    if text:
        units.append((unit_start, len(text)))

    for start, end in units:
        value = unicodedata.normalize("NFKC", text[start:end]).casefold()
        for normalized_character in value:
            is_space = normalized_character.isspace()
            if is_space:
                if previous_was_space:
                    ends[-1] = end
                    continue
                normalized.append(" ")
                starts.append(start)
                ends.append(end)
            else:
                normalized.append(normalized_character)
                starts.append(start)
                ends.append(end)
            previous_was_space = is_space
    return "".join(normalized), tuple(starts), tuple(ends)


def _query_terms(query: str) -> tuple[str, ...]:
    normalized, _, _ = _normalize_with_original_offsets(query)
    return tuple(dict.fromkeys(_TOKEN_PATTERN.findall(normalized)))


def find_keyword_highlights(
    *,
    query: str,
    text: str,
    location: SourceLocation,
    evidence_unit_id: UUID,
) -> KeywordHighlightResult:
    terms = _query_terms(query)
    if not terms:
        return KeywordHighlightResult(0.0, ())
    normalized_text, original_starts, original_ends = _normalize_with_original_offsets(
        text
    )
    matched_terms = 0
    spans: list[HighlightSpan] = []
    for term in terms:
        position = 0
        term_matched = False
        while True:
            start = normalized_text.find(term, position)
            if start < 0:
                break
            end = start + len(term)
            original_start = original_starts[start]
            original_end = original_ends[end - 1]
            absolute_start = location.char_start + original_start
            absolute_end = location.char_start + original_end
            is_whole_unit = original_start == 0 and original_end == len(text)
            bbox = location.bbox if is_whole_unit else None
            warnings = (
                ("pdf_keyword_bbox_unavailable",)
                if location.bbox is not None and not is_whole_unit
                else ()
            )
            spans.append(
                HighlightSpan(
                    kind=HighlightKind.KEYWORD,
                    evidence_unit_id=evidence_unit_id,
                    text=text[original_start:original_end],
                    char_start=absolute_start,
                    char_end=absolute_end,
                    page=location.page,
                    bbox=bbox,
                    warnings=warnings,
                )
            )
            term_matched = True
            position = end
        matched_terms += int(term_matched)
    spans.sort(key=lambda item: (item.char_start, item.char_end, item.text))
    return KeywordHighlightResult(matched_terms / len(terms), tuple(spans))


def semantic_highlight(evidence: EvidenceUnit, *, score: float) -> HighlightSpan:
    warnings: tuple[str, ...] = ()
    if evidence.location.page is not None and evidence.location.bbox is None:
        warnings = ("pdf_bbox_unavailable",)
    elif evidence.location.page is None and evidence.location.bbox is not None:
        warnings = ("page_number_unavailable",)
    return HighlightSpan(
        kind=HighlightKind.SEMANTIC,
        evidence_unit_id=evidence.id,
        text=evidence.text,
        char_start=evidence.location.char_start,
        char_end=evidence.location.char_end,
        page=evidence.location.page,
        bbox=evidence.location.bbox,
        score=score,
        warnings=warnings,
    )


class EvidenceSelector:
    def __init__(self, embedding: EmbeddingPort) -> None:
        self.embedding = embedding

    def select(
        self,
        *,
        query: str,
        sources: tuple[EvidenceSource, ...],
        policy: AnswerPolicy,
    ) -> EvidenceSelection:
        candidates = tuple(
            (source, evidence, _provenance_warnings(source, evidence))
            for source in sources
            for evidence in source.chunk.evidence_units
        )
        eligible = tuple(
            (source, evidence)
            for source, evidence, warnings in candidates
            if not policy.require_complete_provenance or not warnings
        )
        selection_warnings = tuple(
            dict.fromkeys(
                warning
                for _, _, warnings in candidates
                if policy.require_complete_provenance and warnings
                for warning in warnings
            )
        )
        keyword_answers = self._keyword_answers(query, eligible, policy)
        answers = keyword_answers or self._semantic_answers(query, eligible, policy)
        if not answers:
            return EvidenceSelection(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer=None,
                conflict_state=ConflictState.NONE,
                conflicts=(),
                warnings=selection_warnings,
            )

        primary = answers[0]
        primary_text, _, _ = _normalize_with_original_offsets(primary.excerpt)
        seen_documents = {primary.source.document_id}
        conflicts: list[EvidenceAnswer] = []
        for answer in answers[1:]:
            if answer.source.document_id in seen_documents:
                continue
            seen_documents.add(answer.source.document_id)
            normalized, _, _ = _normalize_with_original_offsets(answer.excerpt)
            if normalized != primary_text:
                conflicts.append(answer)
        conflict_state = (
            ConflictState.SEPARATE_SOURCES if conflicts else ConflictState.NONE
        )
        return EvidenceSelection(
            status=AnswerStatus.SUPPORTED,
            answer=primary,
            conflict_state=conflict_state,
            conflicts=tuple(conflicts),
            warnings=selection_warnings,
        )

    @staticmethod
    def _keyword_answers(
        query: str,
        eligible: tuple[tuple[EvidenceSource, EvidenceUnit], ...],
        policy: AnswerPolicy,
    ) -> tuple[EvidenceAnswer, ...]:
        answers: list[EvidenceAnswer] = []
        for source, evidence in eligible:
            result = find_keyword_highlights(
                query=query,
                text=evidence.text,
                location=evidence.location,
                evidence_unit_id=evidence.id,
            )
            if not result.highlights or result.coverage < policy.min_keyword_coverage:
                continue
            answers.append(
                EvidenceAnswer(
                    source=source,
                    evidence=evidence,
                    excerpt=evidence.text,
                    highlights=result.highlights,
                    keyword_coverage=result.coverage,
                    semantic_score=None,
                    warnings=_provenance_warnings(source, evidence),
                )
            )
        return tuple(answers)

    def _semantic_answers(
        self,
        query: str,
        eligible: tuple[tuple[EvidenceSource, EvidenceUnit], ...],
        policy: AnswerPolicy,
    ) -> tuple[EvidenceAnswer, ...]:
        if not eligible:
            return ()
        query_vector = self.embedding.encode_query(query)
        document_vectors = self.embedding.encode_documents(
            [evidence.text for _, evidence in eligible]
        )
        if len(document_vectors) != len(eligible):
            raise ValueError("Evidence embedding count must match evidence units.")
        answers: list[EvidenceAnswer] = []
        for (source, evidence), vector in zip(eligible, document_vectors, strict=True):
            score = _cosine_similarity(query_vector, vector)
            if score < policy.min_semantic_score:
                continue
            answers.append(
                EvidenceAnswer(
                    source=source,
                    evidence=evidence,
                    excerpt=evidence.text,
                    highlights=(semantic_highlight(evidence, score=score),),
                    keyword_coverage=None,
                    semantic_score=score,
                    warnings=_provenance_warnings(source, evidence),
                )
            )
        answers.sort(
            key=lambda answer: (
                answer.semantic_score if answer.semantic_score is not None else -1.0,
                answer.source.fused_score,
            ),
            reverse=True,
        )
        return tuple(answers)


def _provenance_warnings(
    source: EvidenceSource,
    evidence: EvidenceUnit,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if evidence.chunk_id != source.chunk.chunk_id:
        warnings.append("chunk_provenance_incomplete")
    if evidence.projection_id != source.chunk.projection_id:
        warnings.append("projection_provenance_incomplete")
    if evidence.location.char_end <= evidence.location.char_start:
        warnings.append("text_offsets_incomplete")
    if source.media_type == "application/pdf":
        if evidence.location.page is None:
            warnings.append("pdf_page_incomplete")
        if evidence.location.bbox is None:
            warnings.append("pdf_bbox_incomplete")
    elif evidence.location.bbox is not None and evidence.location.page is None:
        warnings.append("page_number_incomplete")
    return tuple(warnings)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Evidence vectors must have matching non-zero dimensions.")
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(float(item) ** 2 for item in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
