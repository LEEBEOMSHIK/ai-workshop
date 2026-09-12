from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from PIL import Image

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig
from ai_workshop.labs.rag.chunking.service import StructuralChunker
from ai_workshop.labs.rag.documents.domain import SourceKind
from ai_workshop.labs.rag.highlighting.service import find_keyword_highlights, semantic_highlight
from ai_workshop.labs.rag.ingestion.serialization import serialize_parsed_document
from ai_workshop.labs.rag.ocr.contracts import OcrProfileSpec, OcrRequest, OcrResult, OcrTextUnit
from ai_workshop.labs.rag.parsing.contracts import ParseRequest
from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser
from ai_workshop.labs.rag.search.viewer import ViewerResource, ViewerService
from ai_workshop.shared.errors import AppError
from tests.e2e.test_rag_docx_ocr_flow import (
    _CharacterCounter,
    _MemoryObjectStore,
    _profile,
    _ViewerRepository,
)


class _SyntheticOcr:
    def recognize(self, request: OcrRequest, profile: OcrProfileSpec) -> OcrResult:
        assert request.image_path.is_file()
        return OcrResult(
            text_units=(
                OcrTextUnit("운용 한도 7%", 0.98, (0.1, 0.2, 0.9, 0.5), True),
                OcrTextUnit("불확실한 99%", 0.2, (0.1, 0.6, 0.9, 0.8), False),
            ),
            table_cells=(),
        )


@pytest.mark.parametrize(
    ("rotation", "dimensions", "expected_bbox"),
    [
        (0, (240, 160), (24.0, 32.0, 216.0, 80.0)),
        (90, (160, 240), (16.0, 48.0, 144.0, 120.0)),
        (180, (240, 160), (24.0, 32.0, 216.0, 80.0)),
        (270, (160, 240), (16.0, 48.0, 144.0, 120.0)),
    ],
)
@pytest.mark.asyncio
async def test_scan_evidence_highlight_returns_authorized_original_page(
    tmp_path: Path,
    rotation: int,
    dimensions: tuple[int, int],
    expected_bbox: tuple[float, float, float, float],
) -> None:
    source_path = tmp_path / "scan.pdf"
    with pymupdf.open() as source:
        page = source.new_page(width=240, height=160)
        page.draw_rect(pymupdf.Rect(24, 32, 216, 80), fill=(0, 0, 0))
        page.set_rotation(rotation)
        source.save(source_path)
    asset_id, projection_id, actor_id = uuid4(), uuid4(), uuid4()
    parsed = PdfOcrParser(
        ocr_runtime=_SyntheticOcr(),
        ocr_profile=_profile(tmp_path),
        raster_dpi=144,
        max_page_pixels=1_000_000,
        max_pages=5,
    ).parse(ParseRequest(source_path, "application/pdf", source_path.name, asset_id))
    chunked = StructuralChunker(_CharacterCounter()).chunk(
        parsed,
        projection_id=projection_id,
        config=ChunkingConfig(target_tokens=100, overlap_tokens=10, hard_ceiling_tokens=120),
    )
    assert [item.text for item in chunked.evidence_units] == ["운용 한도 7%"]
    evidence = chunked.evidence_units[0]
    assert evidence.location.source_kind is SourceKind.PDF_PAGE
    highlight = semantic_highlight(evidence, score=0.9)
    assert highlight.page == 1
    assert highlight.bbox == pytest.approx(expected_bbox)
    # A word inside an OCR line has no independently measured word rectangle.
    keyword = find_keyword_highlights(
        query="7%", text=evidence.text, location=evidence.location, evidence_unit_id=evidence.id,
    )
    assert keyword.highlights
    assert all(item.bbox is None for item in keyword.highlights)

    original = source_path.read_bytes()
    normalized = serialize_parsed_document(parsed)
    resource = ViewerResource(
        document_id=uuid4(), asset_version_id=asset_id, asset_version_number=1,
        workspace_id=uuid4(), folder_id=None, projection_id=projection_id,
        title="합성 스캔 운용 기준", media_type="application/pdf",
        original_object_key="original", original_size=len(original),
        original_sha256=sha256(original).hexdigest(), parsed_object_key="parsed",
        parsed_sha256=sha256(normalized).hexdigest(),
    )
    store = _MemoryObjectStore({"original": original, "parsed": normalized})
    viewer = ViewerService(_ViewerRepository(actor_id, resource), store)
    restored = await viewer.normalized_text(
        actor_id=actor_id, asset_version_id=asset_id, projection_id=projection_id,
    )
    assert restored.document.elements[0].location == evidence.location
    content = await viewer.pdf_page(
        actor_id=actor_id, asset_version_id=asset_id, projection_id=projection_id, page_number=1,
    )
    with Image.open(BytesIO(content)) as image:
        assert image.size == dimensions
    with pytest.raises(AppError) as unauthorized:
        await viewer.pdf_page(
            actor_id=uuid4(), asset_version_id=asset_id, projection_id=projection_id, page_number=1,
        )
    assert unauthorized.value.status_code == 404
    store.objects["original"] = b"tampered"
    with pytest.raises(AppError) as corrupt:
        await viewer.pdf_page(
            actor_id=actor_id, asset_version_id=asset_id,
            projection_id=projection_id, page_number=1,
        )
    assert corrupt.value.code == "source_artifact_invalid"
