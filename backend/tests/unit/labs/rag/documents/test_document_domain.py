from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ProvenanceError,
    RetrievalChunk,
    SourceLocation,
)


def test_evidence_requires_a_source_location() -> None:
    with pytest.raises(ProvenanceError):
        EvidenceUnit.create(text="public evidence", location=None, ordinal=0)


def test_source_location_retains_pdf_coordinates_and_character_offsets() -> None:
    element_id = UUID("11111111-1111-1111-1111-111111111111")
    location = SourceLocation(
        element_id=element_id,
        page=3,
        char_start=14,
        char_end=37,
        bbox=(10.5, 20.25, 210.75, 42.0),
    )

    assert location.element_id == element_id
    assert location.page == 3
    assert location.char_start == 14
    assert location.char_end == 37
    assert location.bbox == (10.5, 20.25, 210.75, 42.0)


def test_retrieval_chunk_requires_evidence_to_declare_its_projection() -> None:
    location = SourceLocation(
        element_id=UUID("22222222-2222-2222-2222-222222222222"),
        page=1,
        char_start=0,
        char_end=8,
        bbox=None,
    )
    evidence = EvidenceUnit(
        id=UUID("22222222-2222-2222-2222-222222222223"),
        chunk_id=UUID("22222222-2222-2222-2222-222222222224"),
        ordinal=0,
        text="fixture",
        location=location,
    )

    with pytest.raises(ProvenanceError, match="projection"):
        RetrievalChunk(
            id=UUID("22222222-2222-2222-2222-222222222224"),
            projection_id=UUID("22222222-2222-2222-2222-222222222225"),
            ordinal=0,
            text="fixture",
            section_path=("Scope",),
            evidence_units=(evidence,),
        )


def test_retrieval_chunk_rejects_evidence_from_another_projection() -> None:
    chunk_id = UUID("33333333-3333-3333-3333-333333333333")
    evidence = EvidenceUnit(
        id=UUID("33333333-3333-3333-3333-333333333334"),
        chunk_id=chunk_id,
        ordinal=0,
        text="fixture",
        location=SourceLocation(
            element_id=UUID("33333333-3333-3333-3333-333333333335"),
            page=None,
            char_start=0,
            char_end=8,
            bbox=None,
        ),
        projection_id=UUID("33333333-3333-3333-3333-333333333336"),
    )

    with pytest.raises(ProvenanceError, match="projection"):
        RetrievalChunk(
            id=chunk_id,
            projection_id=UUID("33333333-3333-3333-3333-333333333337"),
            ordinal=0,
            text="fixture",
            section_path=("Scope",),
            evidence_units=(evidence,),
        )
