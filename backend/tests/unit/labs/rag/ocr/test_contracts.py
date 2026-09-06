from pathlib import Path

import pytest

from ai_workshop.labs.rag.ocr.contracts import (
    OcrConfigurationError,
    OcrProfileSpec,
    OcrTextUnit,
)


def test_ocr_profile_rejects_a_missing_required_local_artifact() -> None:
    with pytest.raises(OcrConfigurationError, match="required local model artifacts"):
        OcrProfileSpec.create(
            pipeline_name="PP-StructureV3",
            pipeline_version="3.7.0",
            detection_model_name="PP-OCRv5_server_det",
            recognition_model_name="korean_PP-OCRv5_mobile_rec",
            table_model_name="SLANet_plus",
            languages=("ko", "en"),
            confidence_threshold=0.7,
            artifact_directories={
                "detection": Path("models/detection"),
                "recognition": Path("models/recognition"),
            },
        )


@pytest.mark.parametrize("threshold", [-0.01, 1.01])
def test_ocr_profile_rejects_confidence_threshold_outside_unit_interval(
    threshold: float,
) -> None:
    with pytest.raises(OcrConfigurationError, match="confidence threshold"):
        OcrProfileSpec.create(
            pipeline_name="PP-StructureV3",
            pipeline_version="3.7.0",
            detection_model_name="PP-OCRv5_server_det",
            recognition_model_name="korean_PP-OCRv5_mobile_rec",
            table_model_name="SLANet_plus",
            languages=("ko", "en"),
            confidence_threshold=threshold,
            artifact_directories={
                "detection": Path("models/detection"),
                "recognition": Path("models/recognition"),
                "table": Path("models/table"),
            },
        )


def test_ocr_text_unit_rejects_bbox_outside_normalized_image_bounds() -> None:
    with pytest.raises(OcrConfigurationError, match="normalized image bounds"):
        OcrTextUnit(
            text="운용 한도 7%",
            confidence=0.91,
            bbox=(0.1, 0.2, 1.1, 0.4),
            evidence_eligible=True,
        )
