from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_workshop.labs.rag.ocr.contracts import (
    OcrProfileSpec,
    OcrRequest,
    OcrRuntimeError,
)
from ai_workshop.labs.rag.ocr.paddle_structure import PaddleStructureV3Adapter


class _Prediction:
    def __init__(self, value: dict[str, object]) -> None:
        self.json = value


class _Runtime:
    def __init__(self, results: list[_Prediction]) -> None:
        self.results = results

    def predict(self, *, input: str) -> Iterator[_Prediction]:
        assert input.endswith("source.png")
        yield from self.results


def _profile(tmp_path: Path) -> OcrProfileSpec:
    artifacts: dict[str, Path] = {}
    for role in ("detection", "recognition", "table"):
        directory = tmp_path / role
        directory.mkdir()
        artifacts[role] = directory
    return OcrProfileSpec.create(
        pipeline_name="PP-StructureV3",
        pipeline_version="3.7.0",
        detection_model_name="PP-OCRv5_server_det",
        recognition_model_name="korean_PP-OCRv5_mobile_rec",
        table_model_name="SLANet_plus",
        languages=("ko", "en"),
        confidence_threshold=0.7,
        artifact_directories=artifacts,
    )


def _request(tmp_path: Path) -> OcrRequest:
    image_path = tmp_path / "source.png"
    image_path.write_bytes(b"synthetic-image")
    return OcrRequest(
        image_path=image_path,
        media_type="image/png",
        source_part="word/media/image1.png",
        image_sha256="a" * 64,
        pixel_width=200,
        pixel_height=100,
    )


def test_adapter_fails_before_runtime_creation_when_an_artifact_directory_is_missing(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    profile.artifact_directories["table"].rmdir()
    factory_called = False

    def factory(_: OcrProfileSpec) -> Any:
        nonlocal factory_called
        factory_called = True
        return _Runtime([])

    adapter = PaddleStructureV3Adapter(runtime_factory=factory)

    with pytest.raises(OcrRuntimeError) as caught:
        adapter.recognize(_request(tmp_path), profile)

    assert caught.value.code == "ocr_model_artifact_missing"
    assert factory_called is False


def test_adapter_normalizes_paddle_text_boxes_and_marks_low_confidence_units(
    tmp_path: Path,
) -> None:
    raw = {
        "res": {
            "overall_ocr_res": {
                "rec_texts": ["운용 한도 7%", "검토 필요"],
                "rec_scores": [0.92, 0.41],
                "rec_boxes": [[10, 20, 110, 60], [20, 65, 180, 95]],
            },
            "table_res_list": [],
        }
    }
    adapter = PaddleStructureV3Adapter(
        runtime_factory=lambda _: _Runtime([_Prediction(raw)])
    )

    result = adapter.recognize(_request(tmp_path), _profile(tmp_path))

    assert result.text_units[0].text == "운용 한도 7%"
    assert result.text_units[0].bbox == (0.05, 0.2, 0.55, 0.6)
    assert result.text_units[0].evidence_eligible is True
    assert result.text_units[1].evidence_eligible is False
    assert result.warnings == ("ocr_confidence_below_threshold",)


def test_adapter_normalizes_table_cell_text_and_boxes(tmp_path: Path) -> None:
    raw = {
        "res": {
            "overall_ocr_res": {
                "rec_texts": [],
                "rec_scores": [],
                "rec_boxes": [],
            },
            "table_res_list": [
                {
                    "table_ocr_pred": {
                        "rec_texts": ["기준가"],
                        "rec_scores": [0.96],
                        "rec_boxes": [[20, 10, 120, 40]],
                    }
                }
            ],
        }
    }
    adapter = PaddleStructureV3Adapter(
        runtime_factory=lambda _: _Runtime([_Prediction(raw)])
    )

    result = adapter.recognize(_request(tmp_path), _profile(tmp_path))

    assert len(result.table_cells) == 1
    assert result.table_cells[0].text == "기준가"
    assert result.table_cells[0].bbox == (0.1, 0.1, 0.6, 0.4)
    assert result.table_cells[0].evidence_eligible is True
