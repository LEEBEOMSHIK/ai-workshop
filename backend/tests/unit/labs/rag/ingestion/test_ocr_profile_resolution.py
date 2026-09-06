from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from ai_workshop.config import Settings
from ai_workshop.labs.rag.ingestion.tasks import _profile_parser
from ai_workshop.labs.rag.models.document_processing import (
    DocumentOcrSpec,
    DocumentProcessingSpec,
    OcrModelSpec,
)
from ai_workshop.labs.rag.models.domain import PP_STRUCTURE_V3_MODEL_KINDS, ModelKind
from ai_workshop.labs.rag.parsing.docx import DOCX_MEDIA_TYPE

MODEL_NAMES = {
    ModelKind.OCR_LAYOUT_DETECTION: "PP-DocLayout_plus-L",
    ModelKind.OCR_TEXT_DETECTION: "PP-OCRv5_server_det",
    ModelKind.OCR_TEXT_RECOGNITION: "korean_PP-OCRv5_mobile_rec",
    ModelKind.OCR_TEXTLINE_ORIENTATION: "PP-LCNet_x1_0_textline_ori",
    ModelKind.OCR_TABLE_CLASSIFICATION: "PP-LCNet_x1_0_table_cls",
    ModelKind.OCR_TABLE_STRUCTURE_WIRED: "SLANeXt_wired",
    ModelKind.OCR_TABLE_STRUCTURE: "SLANet_plus",
    ModelKind.OCR_TABLE_CELLS_WIRED: "RT-DETR-L_wired_table_cell_det",
    ModelKind.OCR_TABLE_CELLS_WIRELESS: "RT-DETR-L_wireless_table_cell_det",
    ModelKind.OCR_TABLE_ORIENTATION: "PP-LCNet_x1_0_doc_ori",
}


def test_profile_parser_maps_every_pp_structure_model_to_an_immutable_cache_path(
    tmp_path: Path,
) -> None:
    models = {
        kind: OcrModelSpec(
            id=uuid4(),
            kind=kind,
            name=MODEL_NAMES[kind],
            version=1,
            source=f"PaddlePaddle/{MODEL_NAMES[kind]}",
            revision="a" * 40,
            artifact_sha256=(str(index) * 64),
            license="Apache-2.0",
        )
        for index, kind in enumerate(sorted(PP_STRUCTURE_V3_MODEL_KINDS), start=1)
    }
    processing = DocumentProcessingSpec(
        profile_id=uuid4(),
        name="pp-structure-v3-docx",
        version=1,
        parser_routes=MappingProxyType({}),
        ocr=DocumentOcrSpec(
            pipeline_name="PP-StructureV3",
            pipeline_version="3.7.0",
            languages=("ko", "en"),
            confidence_threshold=0.7,
            output_schema_version=1,
            models=MappingProxyType(models),
        ),
    )
    settings = Settings(
        secret_key="x" * 32,
        model_cache_root=tmp_path / "models",
    )

    parser = _profile_parser(DOCX_MEDIA_TYPE, processing, settings)

    assert parser is not None
    assert parser.ocr_profile is not None
    assert set(parser.ocr_profile.model_names.values()) == set(MODEL_NAMES.values())
    for runtime_role, directory in parser.ocr_profile.artifact_directories.items():
        kind = next(
            kind
            for kind, name in MODEL_NAMES.items()
            if name == parser.ocr_profile.model_names[runtime_role]
        )
        assert directory == (
            tmp_path
            / "models"
            / "ocr"
            / kind.value
            / models[kind].artifact_sha256
        )
