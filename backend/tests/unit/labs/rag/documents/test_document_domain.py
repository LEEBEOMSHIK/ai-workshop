from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ProvenanceError,
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
