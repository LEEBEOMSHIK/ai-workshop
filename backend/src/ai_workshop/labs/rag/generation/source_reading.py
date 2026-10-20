"""Parser-order hints only: no semantic classification or answer construction."""

from typing import Literal, TypedDict

from ai_workshop.labs.rag.generation.domain import GroundingEvidence


class SourceReading(TypedDict):
    version: Literal[1]
    basis: Literal["parser_source_order_only"]
    semantic_roles: Literal["not_assigned"]
    contiguous_spans: list[list[str]]


def build_source_reading(evidence: tuple[GroundingEvidence, ...]) -> SourceReading:
    """Add ID-only hints without sorting, selecting, rewriting, or classifying text.

    Parser offsets establish reading order, not grammatical or semantic relations.
    Distinct element IDs are preserved in evidence but may have adjacent document
    offsets (e.g. two PDF spans). Never merge their text or invent a joint citation.
    """
    result: SourceReading = {
        "version": 1,
        "basis": "parser_source_order_only",
        "semantic_roles": "not_assigned",
        "contiguous_spans": [],
    }
    if len({item.evidence_id for item in evidence}) != len(evidence):
        # Ambiguous identities cannot produce an unambiguous reading hint.
        return result
    run: list[str] = []
    previous: GroundingEvidence | None = None
    for item in evidence:
        if previous is None or not _adjacent(previous, item):
            if len(run) > 1:
                result["contiguous_spans"].append(run)
            run = []
        run.append(str(item.evidence_id))
        previous = item
    if len(run) > 1:
        result["contiguous_spans"].append(run)
    return result


def _adjacent(left: GroundingEvidence, right: GroundingEvidence) -> bool:
    for item in (left, right):
        if (
            item.projection_id is None
            or item.chunk_id is None
            or item.ordinal < 0
            or item.char_start < 0
            or item.char_end <= item.char_start
        ):
            return False
    return (
        _scope(left) == _scope(right)
        and right.ordinal == left.ordinal + 1
        and right.char_start == left.char_end
    )


def _scope(item: GroundingEvidence) -> tuple[object, ...]:
    return (
        item.document_id,
        item.asset_version_id,
        item.projection_id,
        item.chunk_id,
        item.page,
        item.source_kind,
        item.source_part,
        item.table_cell,
        item.section_path,
    )
