from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.indexing.contracts import IndexDocument


def test_projection_document_preserves_provenance_and_optional_embedding() -> None:
    element_id = UUID("00000000-0000-0000-0000-000000000401")
    chunk_id = UUID("00000000-0000-0000-0000-000000000402")
    projection_id = UUID("00000000-0000-0000-0000-000000000403")
    evidence = EvidenceUnit(
        id=UUID("00000000-0000-0000-0000-000000000404"),
        chunk_id=chunk_id,
        ordinal=0,
        text="한국상품",
        location=SourceLocation(element_id, 3, 10, 14, (1.0, 2.0, 3.0, 4.0)),
        projection_id=projection_id,
    )
    document = IndexDocument(
        chunk_id=chunk_id,
        projection_id=projection_id,
        asset_version_id=UUID("00000000-0000-0000-0000-000000000405"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000406"),
        folder_id=UUID("00000000-0000-0000-0000-000000000407"),
        allowed_user_ids=(UUID("00000000-0000-0000-0000-000000000408"),),
        status="ready",
        title="상품 설명서",
        section_path=("상품", "개요"),
        text="한국상품 설명",
        evidence_units=(evidence,),
        embedding=None,
        index_build_id=UUID("00000000-0000-0000-0000-000000000409"),
    )

    projection = document.to_projection()

    assert set(projection) == {
        "chunk_id",
        "projection_id",
        "asset_version_id",
        "workspace_id",
        "folder_id",
        "allowed_user_ids",
        "status",
        "title",
        "section_path",
        "text",
        "evidence_units",
        "embedding",
        "index_build_id",
    }
    assert projection["chunk_id"] == str(chunk_id)
    assert projection["embedding"] is None
    assert projection["evidence_units"] == [
        {
            "id": "00000000-0000-0000-0000-000000000404",
            "ordinal": 0,
            "text": "한국상품",
            "element_id": "00000000-0000-0000-0000-000000000401",
            "page": 3,
            "char_start": 10,
            "char_end": 14,
            "bbox": [1.0, 2.0, 3.0, 4.0],
        }
    ]
