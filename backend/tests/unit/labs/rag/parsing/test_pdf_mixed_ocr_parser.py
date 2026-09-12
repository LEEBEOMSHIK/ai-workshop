from uuid import uuid4

import pymupdf
import pytest

from ai_workshop.labs.rag.ocr.contracts import (
    OcrConfigurationError,
    OcrResult,
    OcrRuntimeError,
    OcrTextUnit,
)
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParsingError
from ai_workshop.labs.rag.parsing.pdf_ocr import PdfOcrParser
from tests.fixtures.rag.scanned_pdf import create_mixed_page_pdf
from tests.unit.labs.rag.parsing.test_pdf_ocr_parser import SyntheticRuntime, profile


def parse_mixed(path, runtime, *, parser_version="2", max_page_pixels=16_000_000):
    return PdfOcrParser(
        ocr_runtime=runtime,
        ocr_profile=profile(path.parent),
        raster_dpi=144,
        max_page_pixels=max_page_pixels,
        max_pages=200,
        parser_version=parser_version,
    ).parse(ParseRequest(path, "application/pdf", path.name, uuid4()))


@pytest.mark.parametrize(
    ("rotation", "bbox"),
    [
        (0, (20.25, 40.25, 120.25, 100.25)),
        (90, (19.75, 20.25, 79.75, 120.25)),
        (180, (79.75, 19.75, 179.75, 79.75)),
        (270, (40.25, 79.75, 100.25, 179.75)),
    ],
)
def test_mixed_regions_map_fractional_rotated_crop_to_page(tmp_path, rotation, bbox):
    source = create_mixed_page_pdf(tmp_path / "mixed.pdf", rotation=rotation, cropped=True)
    runtime = SyntheticRuntime(OcrResult((OcrTextUnit("IMAGE", 0.95, (0, 0, 1, 1), True),), ()))
    result = parse_mixed(source, runtime)
    assert [e.text for e in result.elements] == ["PUBLIC TEXT", "IMAGE"]
    assert result.elements[1].location.bbox == pytest.approx(bbox)
    assert result.parser_version == "2"
    assert all(e.parser_version == "2" for e in result.elements)
    assert runtime.dimensions == ([(201, 121)] if rotation % 180 == 0 else [(121, 201)])
    assert not runtime.requests[0].image_path.parent.exists()


def test_v1_retains_text_only_semantics_for_mixed_page(tmp_path):
    source = create_mixed_page_pdf(tmp_path / "mixed.pdf")
    assert [
        e.text
        for e in parse_mixed(source, SyntheticRuntime(fail=True), parser_version="1").elements
    ] == ["PUBLIC TEXT"]


def test_unknown_version_fails_before_open(tmp_path):
    with pytest.raises(OcrConfigurationError):
        parse_mixed(tmp_path / "absent.pdf", SyntheticRuntime(), parser_version="99")


def test_empty_decorative_region_is_allowed_but_runtime_failure_propagates(tmp_path):
    source = create_mixed_page_pdf(tmp_path / "mixed.pdf")
    result = parse_mixed(source, SyntheticRuntime(OcrResult((), ())))
    assert [e.text for e in result.elements] == ["PUBLIC TEXT"]
    runtime = SyntheticRuntime(fail=True)
    with pytest.raises(OcrRuntimeError) as error:
        parse_mixed(source, runtime)
    assert "PRIVATE" not in str(error.value)
    assert not runtime.requests[0].image_path.parent.exists()


def test_overlapping_images_render_once_and_separate_occurrences_survive(tmp_path):
    source = create_mixed_page_pdf(
        tmp_path / "mixed.pdf",
        image_rects=(
            (40, 60, 100, 100),
            (80, 60, 140, 100),
            (160, 60, 220, 100),
        ),
    )
    runtime = SyntheticRuntime(OcrResult((OcrTextUnit("IMAGE", 0.95, (0, 0, 1, 1), True),), ()))
    result = parse_mixed(source, runtime)
    assert [e.text for e in result.elements] == ["PUBLIC TEXT", "IMAGE", "IMAGE"]
    assert [e.location.bbox for e in result.elements[1:]] == [
        (40, 60, 140, 100),
        (160, 60, 220, 100),
    ]
    assert runtime.dimensions == [(200, 80), (120, 80)]


def test_native_duplicate_suppressed_only_at_same_position(tmp_path):
    source = create_mixed_page_pdf(
        tmp_path / "mixed.pdf", overlay=True, image_rects=((40, 60, 140, 120),)
    )
    runtime = SyntheticRuntime(
        OcrResult(
            (
                OcrTextUnit("SAME  TEXT", 0.95, (0.1, 0.3, 0.8, 0.6), True),
                OcrTextUnit("SAME TEXT", 0.95, (0.1, 0.8, 0.8, 1), True),
                OcrTextUnit("SOME TEXT", 0.95, (0.1, 0.3, 0.8, 0.6), True),
            ),
            (),
        )
    )
    result = parse_mixed(source, runtime)
    assert [e.evidence_eligible for e in result.elements] == [True, True, False, True, True]
    assert "pdf_ocr_native_duplicate" in result.elements[2].warnings
    assert result.elements[2].text == "SAME  TEXT"


def test_aggregate_region_pixel_limit_checked_before_any_render(tmp_path, monkeypatch):
    source = create_mixed_page_pdf(
        tmp_path / "mixed.pdf",
        image_rects=(
            (40, 60, 100, 100),
            (160, 60, 220, 100),
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Aggregate raster budget must be checked before allocation")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", forbidden)
    with pytest.raises(ParsingError) as error:
        parse_mixed(source, SyntheticRuntime(), max_page_pixels=15_000)
    assert error.value.code == "pdf_processing_limit_exceeded"


def test_fractional_region_maps_inner_bbox_using_actual_pixel_origin(tmp_path):
    source = create_mixed_page_pdf(tmp_path / "mixed.pdf")
    runtime = SyntheticRuntime(
        OcrResult((OcrTextUnit("IMAGE", 0.95, (0.1, 0.2, 0.5, 0.6), True),), ())
    )
    result = parse_mixed(source, runtime)
    assert result.elements[1].location.bbox == pytest.approx((50.05, 72.1, 90.25, 96.3))


def test_native_text_split_across_font_spans_is_still_duplicate(tmp_path):
    source = create_mixed_page_pdf(tmp_path / "mixed.pdf", image_rects=((40, 60, 140, 120),))
    with pymupdf.open(source) as document:
        page = document[0]
        page.insert_text((50, 90), "SAME ", fontsize=10)
        page.insert_text((82, 90), "TEXT", fontsize=10, fontname="hebo")
        document.saveIncr()
    runtime = SyntheticRuntime(
        OcrResult((OcrTextUnit("SAME TEXT", 0.95, (0.1, 0.3, 0.8, 0.6), True),), ())
    )
    result = parse_mixed(source, runtime)
    assert not result.elements[-1].evidence_eligible
    assert "pdf_ocr_native_duplicate" in result.elements[-1].warnings


def test_adjacent_identical_text_with_slight_bbox_overlap_remains_eligible(tmp_path):
    source = create_mixed_page_pdf(
        tmp_path / "mixed.pdf", overlay=True, image_rects=((40, 60, 140, 120),)
    )
    runtime = SyntheticRuntime(
        OcrResult(
            (
                OcrTextUnit("SAME TEXT", 0.95, (0.1, 31 / 60, 0.8, 40 / 60), True),
                OcrTextUnit("SAME TEXT", 0.95, (0.1, 19 / 60, 0.8, 33 / 60), True),
            ),
            (),
        )
    )
    result = parse_mixed(source, runtime)
    adjacent, same_position = result.elements[-2:]
    assert adjacent.location.bbox == pytest.approx((50, 91, 120, 100))
    assert adjacent.evidence_eligible
    assert "pdf_ocr_native_duplicate" not in adjacent.warnings
    assert not same_position.evidence_eligible
    assert "pdf_ocr_native_duplicate" in same_position.warnings


def test_off_crop_image_is_not_ocr_input(tmp_path):
    source = create_mixed_page_pdf(
        tmp_path / "mixed.pdf", cropped=True, image_rects=((0, 0, 10, 10), (200, 80, 240, 160))
    )
    runtime = SyntheticRuntime(OcrResult((OcrTextUnit("IMAGE", 0.95, (0, 0, 1, 1), True),), ()))
    result = parse_mixed(source, runtime)
    assert runtime.dimensions == [(40, 120)]
    assert result.elements[-1].location.bbox == (180, 60, 200, 120)
