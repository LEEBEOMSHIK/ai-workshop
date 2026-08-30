from pathlib import Path
from uuid import UUID

import pymupdf
import pytest

from ai_workshop.labs.rag.parsing.contracts import OcrRequiredError, ParseRequest, ParsingError
from ai_workshop.labs.rag.parsing.pdf import PdfParser
from tests.fixtures.rag.sample_pdf import create_image_only_pdf, create_sample_pdf


def test_pdf_parser_preserves_page_order_offsets_and_coordinates(tmp_path: Path) -> None:
    source = create_sample_pdf(tmp_path / "public.pdf")

    parsed = PdfParser().parse(
        ParseRequest(
            path=source,
            media_type="application/pdf",
            filename=source.name,
            asset_version_id=UUID("33333333-3333-3333-3333-333333333333"),
        )
    )

    assert [element.text for element in parsed.elements] == [
        "PUBLIC RISK LIMIT",
        "Synthetic first page.",
        "PUBLIC REPORT DATE",
    ]
    assert [element.location.page for element in parsed.elements] == [1, 1, 2]
    assert [element.ordinal for element in parsed.elements] == [0, 1, 2]
    assert [
        (element.location.char_start, element.location.char_end) for element in parsed.elements
    ] == [(0, 17), (17, 38), (38, 56)]

    pdf = pymupdf.open(source)
    try:
        for element in parsed.elements:
            page = pdf[element.location.page - 1]
            assert element.location.bbox is not None
            left, top, right, bottom = element.location.bbox
            assert 0 <= left <= right <= page.rect.width
            assert 0 <= top <= bottom <= page.rect.height
    finally:
        pdf.close()


def test_pdf_parser_marks_image_only_pages_as_ocr_required(tmp_path: Path) -> None:
    source = create_image_only_pdf(tmp_path / "scan.pdf")

    with pytest.raises(OcrRequiredError) as error:
        PdfParser().parse(
            ParseRequest(
                path=source,
                media_type="application/pdf",
                filename=source.name,
                asset_version_id=UUID("33333333-3333-3333-3333-333333333333"),
            )
        )

    assert error.value.code == "ocr_required"


def test_pdf_parser_rejects_a_text_span_with_coordinates_outside_its_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledPage:
        rect = pymupdf.Rect(0, 0, 240, 160)

        def get_text(self, option: str, *, sort: bool) -> dict[str, object]:
            assert option == "dict"
            assert sort is False
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "text": "EDGE",
                                        "bbox": (-0.25, 24.0, 32.0, 36.0),
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }

    class ControlledDocument:
        def __iter__(self) -> object:
            return iter((ControlledPage(),))

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "ai_workshop.labs.rag.parsing.pdf.pymupdf.open",
        lambda path: ControlledDocument(),
    )

    with pytest.raises(ParsingError) as error:
        PdfParser().parse(
            ParseRequest(
                path=tmp_path / "controlled.pdf",
                media_type="application/pdf",
                filename="controlled.pdf",
                asset_version_id=UUID("33333333-3333-3333-3333-333333333333"),
            )
        )

    assert error.value.code == "invalid_pdf_coordinates"
