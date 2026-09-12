import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from ai_workshop.labs.rag.ocr.artifacts import verify_artifacts
from ai_workshop.labs.rag.ocr.contracts import OcrProfileSpec
from ai_workshop.labs.rag.ocr.paddle_structure import PaddleStructureV3Adapter
from ai_workshop.labs.rag.parsing.contracts import ParseRequest
from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser
from tests.integration.labs.rag.ocr.test_paddle_structure_smoke import (
    create_smoke_fixture,
    smoke_cache_root,
    smoke_device,
    smoke_manifest_path,
)


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AI_WORKSHOP_PDF_OCR_ACTUAL_SMOKE") != "1",
    reason="Set AI_WORKSHOP_PDF_OCR_ACTUAL_SMOKE=1 for actual scanned PDF inference.",
)
def test_actual_scanned_pdf_text_and_table_have_page_provenance(tmp_path: Path) -> None:
    manifest_path = smoke_manifest_path()
    cache_root = smoke_cache_root()
    verify_artifacts(manifest_path=manifest_path, cache_root=cache_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = manifest["models"]
    profile = OcrProfileSpec.create(
        pipeline_name=manifest["pipeline"]["name"],
        pipeline_version=manifest["pipeline"]["package_version"],
        model_names={model["runtime_role"]: model["name"] for model in models},
        languages=("ko", "en"), confidence_threshold=0.7,
        artifact_directories={
            model["runtime_role"]: (
                cache_root / "ocr" / model["model_kind"] / model["artifact_sha256"]
            )
            for model in models
        },
        device=smoke_device(),
    )
    fixture = create_smoke_fixture(
        tmp_path, platform="windows" if sys.platform == "win32" else "linux",
    )
    source_path = tmp_path / "scanned-policy.pdf"
    with pymupdf.open() as document:
        for image_path, height in ((fixture.text_image, 180), (fixture.table_image, 360)):
            page = document.new_page(width=600, height=height)
            page.insert_image(page.rect, filename=str(image_path))
        document.save(source_path)
    parsed = PdfOcrParser(
        ocr_runtime=PaddleStructureV3Adapter(), ocr_profile=profile,
        raster_dpi=144, max_page_pixels=16_000_000, max_pages=200,
    ).parse(ParseRequest(source_path, "application/pdf", source_path.name, uuid4()))
    text = " ".join(item.text for item in parsed.elements if item.location.page == 1)
    table = " ".join(
        item.text for item in parsed.elements
        if item.location.page == 2 and item.kind == "ocr_table_cell"
    )
    assert all(token in text for token in fixture.text_tokens)
    assert all(token in table for token in fixture.table_tokens)
    assert any(item.evidence_eligible for item in parsed.elements)
    for item in parsed.elements:
        assert item.location.page in (1, 2)
        assert item.location.bbox is not None
        left, top, right, bottom = item.location.bbox
        assert 0 <= left < right <= 600
        assert 0 <= top < bottom <= (180 if item.location.page == 1 else 360)
