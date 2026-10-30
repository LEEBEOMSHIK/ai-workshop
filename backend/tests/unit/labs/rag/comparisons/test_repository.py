from uuid import uuid4

import pytest

from ai_workshop.labs.rag.comparisons.repository import matches_evidence
from ai_workshop.labs.rag.comparisons.schemas import ComparisonImport
from ai_workshop.labs.rag.documents.models import EvidenceUnitRecord
from tests.unit.labs.rag.comparisons.support import payload


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", uuid4()),
        ("projection_id", uuid4()),
        ("retrieval_chunk_id", uuid4()),
        ("element_id", uuid4()),
        ("ordinal", 88),
        ("text", "다른 내용"),
        ("page", 3),
        ("char_start", 4),
        ("char_end", 20),
        ("bbox", [0.0, 0.0, 1.0, 1.0]),
        ("source_kind", "normalized_text"),
    ],
)
def test_every_saved_evidence_identity_content_and_position_is_checked(
    field: str, value: object
) -> None:
    evidence = ComparisonImport.model_validate(payload()).evidence[0]
    data = evidence.model_dump(
        exclude={
            "ref",
            "document_id",
            "asset_version_id",
            "index_build_id",
            "title",
            "evidence_id",
        }
    )
    row = EvidenceUnitRecord(id=evidence.evidence_id, **data)
    assert matches_evidence(row, evidence)
    setattr(row, field, value)
    assert not matches_evidence(row, evidence)
