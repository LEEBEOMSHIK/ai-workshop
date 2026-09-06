from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_workshop.labs.rag.ocr import paddle_structure
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
    model_names = {
        "layout": "PP-DocLayout_plus-L",
        "detection": "PP-OCRv5_server_det",
        "recognition": "korean_PP-OCRv5_mobile_rec",
        "textline_orientation": "PP-LCNet_x1_0_textline_ori",
        "table_classification": "PP-LCNet_x1_0_table_cls",
        "wired_table_structure": "SLANeXt_wired",
        "wireless_table_structure": "SLANet_plus",
        "wired_table_cells": "RT-DETR-L_wired_table_cell_det",
        "wireless_table_cells": "RT-DETR-L_wireless_table_cell_det",
        "table_orientation": "PP-LCNet_x1_0_doc_ori",
    }
    artifacts: dict[str, Path] = {}
    for role in model_names:
        directory = tmp_path / role
        directory.mkdir()
        artifacts[role] = directory
    return OcrProfileSpec.create(
        pipeline_name="PP-StructureV3",
        pipeline_version="3.7.0",
        model_names=model_names,
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
    profile.artifact_directories["wired_table_cells"].rmdir()
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


def test_adapter_accepts_a_normal_text_result_without_a_table_result_key(
    tmp_path: Path,
) -> None:
    raw = {
        "res": {
            "overall_ocr_res": {
                "rec_texts": ["운용 한도 7%"],
                "rec_scores": [0.98],
                "rec_boxes": [[10, 20, 110, 60]],
            }
        }
    }
    adapter = PaddleStructureV3Adapter(
        runtime_factory=lambda _: _Runtime([_Prediction(raw)])
    )

    result = adapter.recognize(_request(tmp_path), _profile(tmp_path))

    assert result.text_units[0].text == "운용 한도 7%"
    assert result.table_cells == ()


def test_runtime_factory_passes_the_complete_local_pp_structure_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Runtime:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        paddle_structure,
        "import_module",
        lambda _: SimpleNamespace(PPStructureV3=Runtime),
    )

    paddle_structure._create_runtime(_profile(tmp_path))

    assert captured["device"] == "cpu"
    assert captured["use_table_recognition"] is True
    assert captured["use_region_detection"] is False
    assert captured["layout_detection_model_name"] == "PP-DocLayout_plus-L"
    assert captured["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert (
        captured["text_recognition_model_name"]
        == "korean_PP-OCRv5_mobile_rec"
    )
    assert (
        captured["textline_orientation_model_name"]
        == "PP-LCNet_x1_0_textline_ori"
    )
    assert (
        captured["table_classification_model_name"]
        == "PP-LCNet_x1_0_table_cls"
    )
    assert captured["wired_table_structure_recognition_model_name"] == "SLANeXt_wired"
    assert (
        captured["wireless_table_structure_recognition_model_name"]
        == "SLANet_plus"
    )
    assert (
        captured["wired_table_cells_detection_model_name"]
        == "RT-DETR-L_wired_table_cell_det"
    )
    assert (
        captured["wireless_table_cells_detection_model_name"]
        == "RT-DETR-L_wireless_table_cell_det"
    )
    assert captured["table_orientation_classify_model_name"] == "PP-LCNet_x1_0_doc_ori"
    assert "table_structure_recognition_model_name" not in captured


def test_adapter_reuses_one_initialized_runtime_for_multiple_images(
    tmp_path: Path,
) -> None:
    raw = {
        "res": {
            "overall_ocr_res": {
                "rec_texts": ["운용"],
                "rec_scores": [0.99],
                "rec_boxes": [[10, 10, 50, 40]],
            }
        }
    }
    calls = 0

    def factory(_: OcrProfileSpec) -> _Runtime:
        nonlocal calls
        calls += 1
        return _Runtime([_Prediction(raw)])

    adapter = PaddleStructureV3Adapter(runtime_factory=factory)
    profile = _profile(tmp_path)

    adapter.recognize(_request(tmp_path), profile)
    adapter.recognize(_request(tmp_path), profile)

    assert calls == 1
