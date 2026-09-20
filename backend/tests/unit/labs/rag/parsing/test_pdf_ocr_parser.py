from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceKind
from ai_workshop.labs.rag.ocr.contracts import (
    PP_STRUCTURE_V3_RUNTIME_ROLES,
    OcrProfileSpec,
    OcrRequest,
    OcrResult,
    OcrRuntimeError,
    OcrTableCell,
    OcrTextUnit,
)
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParsingError
from tests.fixtures.rag.sample_pdf import create_image_only_pdf, create_sample_pdf
from tests.fixtures.rag.scanned_pdf import create_scanned_pdf
from tests.unit.labs.rag.parsing.test_service import FakeWorkspace


def profile(tmp_path: Path) -> OcrProfileSpec:
    return OcrProfileSpec.create(
        pipeline_name="synthetic-ocr",
        pipeline_version="test-1",
        model_names={role: f"synthetic-{role}" for role in PP_STRUCTURE_V3_RUNTIME_ROLES},
        artifact_directories={role: tmp_path for role in PP_STRUCTURE_V3_RUNTIME_ROLES},
        languages=("en",),
        confidence_threshold=0.8,
    )


class SyntheticRuntime:
    def __init__(self, result: OcrResult | None = None, fail: bool = False) -> None:
        self.result = result or OcrResult(
            (OcrTextUnit("SCAN", 0.95, (0.1, 0.2, 0.5, 0.6), True),),
            (OcrTableCell("42", 0.9, (0.5, 0.6, 0.9, 0.8), 1, 2),),
        )
        self.fail = fail
        self.requests: list[OcrRequest] = []
        self.dimensions: list[tuple[int, int]] = []
        self.corner_pixels: list[tuple[tuple[int, ...], ...]] = []

    def recognize(self, request: OcrRequest, spec: OcrProfileSpec) -> OcrResult:
        self.requests.append(request)
        blob = request.image_path.read_bytes()
        assert request.image_sha256 == sha256(blob).hexdigest()
        assert request.media_type == "image/png"
        image = pymupdf.Pixmap(blob)
        assert image.n == 3
        assert image.alpha == 0
        assert (request.pixel_width, request.pixel_height) == (image.width, image.height)
        self.dimensions.append((image.width, image.height))
        self.corner_pixels.append(
            tuple(
                image.pixel(int(image.width * x), int(image.height * y))
                for x, y in ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))
            )
        )
        if self.fail:
            raise OcrRuntimeError("ocr_inference_failed", "PRIVATE SOURCE /private/path")
        return self.result


def parse(path: Path, runtime: SyntheticRuntime, **limits: int) -> ParsedDocument:
    from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser

    return PdfOcrParser(
        ocr_runtime=runtime,
        ocr_profile=profile(path.parent),
        raster_dpi=limits.get("raster_dpi", 144),
        max_page_pixels=limits.get("max_page_pixels", 16_000_000),
        max_pages=limits.get("max_pages", 200),
    ).parse(
        ParseRequest(path, "application/pdf", path.name, uuid4(),
                     FakeWorkspace(path.parent), lambda: None)
    )


@pytest.mark.parametrize(
    ("rotation", "cropped", "pixels", "bbox"),
    [
        (0, False, (480, 320), (24, 32, 120, 96)),
        (90, False, (320, 480), (16, 48, 80, 144)),
        (0, True, (400, 240), (20, 24, 100, 72)),
        (90, True, (240, 400), (12, 40, 60, 120)),
        (180, True, (400, 240), (20, 24, 100, 72)),
        (270, True, (240, 400), (12, 40, 60, 120)),
    ],
)
def test_scanned_page_ocr_uses_displayed_crop_and_rotation_coordinates(
    tmp_path: Path,
    rotation: int,
    cropped: bool,
    pixels: tuple[int, int],
    bbox: tuple[int, int, int, int],
) -> None:
    source = create_scanned_pdf(tmp_path / "scan.pdf", rotation=rotation, cropped=cropped)
    runtime = SyntheticRuntime()
    parsed = parse(source, runtime)

    assert runtime.dimensions == [pixels]
    assert parsed.elements[0].location.bbox == pytest.approx(bbox)
    assert parsed.elements[0].location.source_kind is SourceKind.PDF_PAGE
    assert [element.location.page for element in parsed.elements] == [1, 1]
    assert [element.text for element in parsed.elements] == ["SCAN", "42"]
    assert parsed.elements[1].location.table_cell.row == 1
    assert parsed.elements[1].location.table_cell.column == 2
    assert runtime.requests[0].image_path.exists()
    assert runtime.requests[0].image_path.parent.exists()
    assert runtime.corner_pixels[0][rotation // 90] == (255, 0, 0)


def test_mixed_document_keeps_text_then_scanned_provenance_and_offsets(tmp_path: Path) -> None:
    source = create_scanned_pdf(tmp_path / "mixed.pdf", text_first=True)
    runtime = SyntheticRuntime()
    parsed = parse(source, runtime)

    assert [element.text for element in parsed.elements] == ["PUBLIC TEXT", "SCAN", "42"]
    assert [element.location.page for element in parsed.elements] == [1, 2, 2]
    assert [element.ordinal for element in parsed.elements] == [0, 1, 2]
    assert [(e.location.char_start, e.location.char_end) for e in parsed.elements] == [
        (0, 11),
        (11, 15),
        (15, 17),
    ]
    assert len(runtime.requests) == 1
    assert parsed.elements[0].confidence == 1.0


def test_text_document_preserves_extraction_without_ocr(tmp_path: Path) -> None:
    source = create_sample_pdf(tmp_path / "text.pdf")
    runtime = SyntheticRuntime(fail=True)
    parsed = parse(source, runtime)
    assert [e.text for e in parsed.elements] == [
        "PUBLIC RISK LIMIT",
        "Synthetic first page.",
        "PUBLIC REPORT DATE",
    ]
    assert not runtime.requests


def test_cropped_rotated_text_spans_align_with_displayed_page(tmp_path: Path) -> None:
    source = tmp_path / "rotated-text.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=160)
        page.insert_text((40, 50), "W", fontsize=10)
        page.set_cropbox(pymupdf.Rect(20, 20, 220, 140))
        page.set_rotation(90)
        document.save(source)
    parsed = parse(source, SyntheticRuntime(fail=True))
    assert parsed.elements[0].text == "W"
    assert parsed.elements[0].location.bbox == pytest.approx((87.01, 20, 100.75, 29.44), abs=0.001)


@pytest.mark.parametrize(
    "limits", [{"raster_dpi": 0}, {"raster_dpi": -1}, {"max_page_pixels": 0}, {"max_pages": 0}]
)
def test_invalid_limits_are_rejected_before_processing(tmp_path: Path, limits: dict[str, int]):
    from ai_workshop.labs.rag.ocr.contracts import OcrConfigurationError

    with pytest.raises(OcrConfigurationError):
        parse(tmp_path / "never-opened.pdf", SyntheticRuntime(), **limits)


def test_encrypted_pdf_is_a_safe_failure(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(
            source,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="synthetic-password",
            owner_pw="synthetic-owner",
        )
    with pytest.raises(ParsingError) as error:
        parse(source, SyntheticRuntime())
    assert error.value.code == "pdf_invalid"


def test_whitespace_only_spans_do_not_suppress_ocr(tmp_path: Path) -> None:
    source = create_scanned_pdf(tmp_path / "spaces.pdf", whitespace=True)
    parsed = parse(source, SyntheticRuntime())
    assert [e.text for e in parsed.elements] == ["SCAN", "42"]


def test_text_page_preserves_internal_whitespace_spans(tmp_path: Path) -> None:
    source = tmp_path / "spaced-text.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=160)
        page.insert_text((24, 32), "PUBLIC")
        page.insert_text((24, 64), "   ")
        page.insert_text((24, 96), "TEXT")
        document.save(source)
    parsed = parse(source, SyntheticRuntime(fail=True))
    assert [e.text for e in parsed.elements] == ["PUBLIC", "   ", "TEXT"]
    assert parsed.elements[-1].location.char_start == 9


def test_page_classification_does_not_expand_embedded_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = create_image_only_pdf(tmp_path / "image.pdf")
    original_get_text = pymupdf.Page.get_text

    def capped_get_text(page, *args, **kwargs):
        flags = kwargs.get("flags", pymupdf.TEXTFLAGS_DICT)
        if flags & pymupdf.TEXT_PRESERVE_IMAGES:
            pytest.fail("Page classification expanded embedded images before raster limits")
        return original_get_text(page, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "get_text", capped_get_text)
    parsed = parse(source, SyntheticRuntime())
    assert parsed.elements[0].text == "SCAN"


def test_low_confidence_and_runtime_rejection_are_retained_but_ineligible(tmp_path: Path) -> None:
    source = create_scanned_pdf(tmp_path / "scan.pdf")
    runtime = SyntheticRuntime(
        OcrResult(
            (
                OcrTextUnit("LOW", 0.2, (0, 0, 0.5, 0.2), True),
                OcrTextUnit("REJECTED", 0.95, (0, 0.2, 0.5, 0.4), False),
                OcrTextUnit("ACCEPTED", 0.8, (0, 0.4, 0.5, 0.6), True),
            ),
            (OcrTableCell("LOW CELL", 0.1, (0, 0.6, 0.5, 0.8), 0, 0),),
        )
    )
    parsed = parse(source, runtime)
    assert [e.evidence_eligible for e in parsed.elements] == [False, False, True, False]
    assert "ocr_confidence_below_threshold" in parsed.elements[0].warnings
    assert parsed.elements[1].warnings
    assert "ocr_confidence_below_threshold" in parsed.elements[3].warnings


@pytest.mark.parametrize(
    "result", [OcrResult((), ()), OcrResult((OcrTextUnit(" \n", 0.9, (0, 0, 1, 1), True),), ())]
)
def test_empty_ocr_page_is_an_explicit_failure(tmp_path: Path, result: OcrResult) -> None:
    source = create_scanned_pdf(tmp_path / "empty.pdf", text_first=True)
    runtime = SyntheticRuntime(result)
    with pytest.raises(ParsingError) as error:
        parse(source, runtime)
    assert error.value.code == "pdf_ocr_empty"
    assert runtime.requests[0].image_path.parent.exists()


def test_runtime_failure_is_safe_and_preserves_page_image(tmp_path: Path) -> None:
    source = create_scanned_pdf(tmp_path / "scan.pdf")
    runtime = SyntheticRuntime(fail=True)
    with pytest.raises(OcrRuntimeError) as error:
        parse(source, runtime)
    assert error.value.code == "ocr_inference_failed"
    assert "PRIVATE" not in str(error.value)
    assert runtime.requests[0].image_path.parent.exists()


@pytest.mark.parametrize("limits", [{"max_pages": 1}, {"max_page_pixels": 100}])
def test_limits_reject_before_allocating_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limits: dict[str, int]
) -> None:
    source = create_scanned_pdf(tmp_path / "large.pdf", text_first=True)

    def forbidden_render(*args: object, **kwargs: object) -> None:
        pytest.fail("Oversized document allocated a raster")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", forbidden_render)
    with pytest.raises(ParsingError) as error:
        parse(source, SyntheticRuntime(), **limits)
    assert error.value.code == "pdf_processing_limit_exceeded"


def test_malformed_pdf_is_a_safe_failure(tmp_path: Path) -> None:
    source = tmp_path / "invalid.pdf"
    source.write_bytes(b"not a PDF")
    with pytest.raises(ParsingError) as error:
        parse(source, SyntheticRuntime())
    assert error.value.code == "pdf_invalid"
    assert str(source) not in str(error.value)


def test_pdf_ocr_requires_explicit_workspace(tmp_path: Path) -> None:
    from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser

    path = create_scanned_pdf(tmp_path / "scan.pdf")
    runtime = SyntheticRuntime()
    with pytest.raises(ParsingError, match="Tracked temporary workspace required"):
        PdfOcrParser(ocr_runtime=runtime, ocr_profile=profile(tmp_path), raster_dpi=144,
                     max_page_pixels=16_000_000, max_pages=200).parse(
            ParseRequest(path, "application/pdf", path.name, uuid4())
        )
    assert runtime.requests == []


def test_pdf_marks_opaque_writer_before_runtime(tmp_path: Path) -> None:
    from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser

    started = []
    workspace = FakeWorkspace(tmp_path)

    class CheckedRuntime(SyntheticRuntime):
        def recognize(self, request, spec):
            assert started == [True]
            assert request.image_path.parent == workspace.root
            return super().recognize(request, spec)

    path = create_scanned_pdf(tmp_path / "scan.pdf")
    runtime = CheckedRuntime()
    PdfOcrParser(ocr_runtime=runtime, ocr_profile=profile(tmp_path), raster_dpi=144,
                 max_page_pixels=16_000_000, max_pages=200).parse(
        ParseRequest(path, "application/pdf", path.name, uuid4(), workspace,
                     lambda: started.append(True))
    )
    assert len(workspace.files) == 1
    assert workspace.files[0].exists()
