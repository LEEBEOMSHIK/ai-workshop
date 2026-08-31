from dataclasses import dataclass
from uuid import UUID, uuid4

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig, ChunkingResult, TokenCounter
from ai_workshop.labs.rag.chunking.sentences import SentenceSpan, split_sentences
from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    RetrievalChunk,
    SourceLocation,
)


class ChunkOverflowError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _EvidenceSource:
    element_id: UUID
    text: str
    location: SourceLocation
    section_path: tuple[str, ...]


class StructuralChunker:
    def __init__(self, token_counter: TokenCounter) -> None:
        self._token_counter = token_counter

    def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        config: ChunkingConfig,
    ) -> ChunkingResult:
        sources = _evidence_sources(document)
        chunks: list[RetrievalChunk] = []
        evidence_units: list[EvidenceUnit] = []
        current: list[_EvidenceSource] = []
        current_path: tuple[str, ...] = ()

        def flush() -> None:
            if not current:
                return
            chunk_id = uuid4()
            units = tuple(
                EvidenceUnit.create(
                    text=source.text,
                    location=source.location,
                    ordinal=ordinal,
                    chunk_id=chunk_id,
                    projection_id=projection_id,
                )
                for ordinal, source in enumerate(current)
            )
            chunk = RetrievalChunk(
                id=chunk_id,
                projection_id=projection_id,
                ordinal=len(chunks),
                text=_render_chunk(current_path, current),
                section_path=current_path,
                evidence_units=units,
            )
            chunks.append(chunk)
            evidence_units.extend(units)

        for source in sources:
            _raise_if_overflow(source, self._token_counter, config)
            if not current:
                current = [source]
                current_path = source.section_path
                continue
            if source.section_path != current_path:
                flush()
                current = [source]
                current_path = source.section_path
                continue
            proposed = [*current, source]
            if self._count_rendered(current_path, proposed) <= config.target_tokens:
                current = proposed
                continue
            flush()
            current = _overlap_tail(current, self._token_counter, config.overlap_tokens)
            while (
                current
                and self._count_rendered(current_path, [*current, source])
                > config.hard_ceiling_tokens
            ):
                current.pop(0)
            current.append(source)

        flush()
        return ChunkingResult(tuple(chunks), tuple(evidence_units))

    def _count_rendered(self, section_path: tuple[str, ...], sources: list[_EvidenceSource]) -> int:
        return self._token_counter.count(_render_chunk(section_path, sources))


def _evidence_sources(document: ParsedDocument) -> tuple[_EvidenceSource, ...]:
    sources: list[_EvidenceSource] = []
    for element in document.elements:
        spans = (
            split_sentences(element.text)
            if element.kind == "paragraph" and element.location.bbox is None
            else (_whole_element_span(element.text),)
        )
        for span in spans:
            if span is not None:
                sources.append(
                    _EvidenceSource(
                        element_id=element.id,
                        text=span.text,
                        location=_source_location_for_span(element.location, span),
                        section_path=element.section_path,
                    )
                )
    return tuple(sources)


def _whole_element_span(text: str) -> SentenceSpan | None:
    start = 0
    end = len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return None
    return SentenceSpan(text=text[start:end], start=start, end=end)


def _source_location_for_span(location: SourceLocation, span: SentenceSpan) -> SourceLocation:
    if location.bbox is not None:
        # A parser-provided PDF bbox covers the structural element. Without
        # character-level geometry, splitting it would invent sub-box coordinates.
        return location
    return SourceLocation(
        element_id=location.element_id,
        page=location.page,
        char_start=location.char_start + span.start,
        char_end=location.char_start + span.end,
        bbox=None,
    )


def _render_chunk(section_path: tuple[str, ...], sources: list[_EvidenceSource]) -> str:
    body = "\n".join(source.text for source in sources)
    if not section_path:
        return body
    return f"{' > '.join(section_path)}\n\n{body}"


def _overlap_tail(
    sources: list[_EvidenceSource], token_counter: TokenCounter, overlap_tokens: int
) -> list[_EvidenceSource]:
    tail: list[_EvidenceSource] = []
    for source in reversed(sources):
        proposed = [source, *tail]
        if token_counter.count("\n".join(item.text for item in proposed)) > overlap_tokens:
            break
        tail = proposed
    return tail


def _raise_if_overflow(
    source: _EvidenceSource, token_counter: TokenCounter, config: ChunkingConfig
) -> None:
    if (
        token_counter.count(_render_chunk(source.section_path, [source]))
        > config.hard_ceiling_tokens
    ):
        raise ChunkOverflowError(
            "Evidence unit from structural element "
            f"{source.element_id} exceeds the {config.hard_ceiling_tokens} token chunk ceiling."
        )
