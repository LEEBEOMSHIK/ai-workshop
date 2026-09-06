from uuid import uuid4

import pytest

from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    DocumentProcessingResolutionError,
    index_namespace_document_processing_profile_id,
    resolve_document_processing_spec,
)
from ai_workshop.labs.rag.models.domain import (
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)


def _model(kind: ModelKind, name: str) -> ModelDefinition:
    return ModelDefinition.create(
        kind=kind,
        name=name,
        version=1,
        config={
            "source": f"PaddlePaddle/{name}",
            "revision": "approved-revision",
            "artifact_sha256": "a" * 64,
            "license": "Apache-2.0",
            "data_policy": "local_only",
        },
    )


def _profile(models: tuple[ModelDefinition, ...]) -> Profile:
    return Profile.create(
        kind=ProfileKind.DOCUMENT_PROCESSING,
        name="docx-ocr",
        version=1,
        config={
            "parser_policy": {
                "schema_version": 1,
                "routes": {
                    "text/plain": {"name": "plain-text", "version": "1"},
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
                        "name": "docx-structure",
                        "version": "1",
                    },
                },
            },
            "ocr": {
                "enabled": True,
                "pipeline_name": "PP-StructureV3",
                "pipeline_version": "3.7.0",
                "languages": ["ko", "en"],
                "confidence_threshold": 0.7,
                "output_schema_version": 1,
                "data_policy": "local_only",
            },
        },
        bindings=tuple(
            ProfileModelBinding(role=model.kind, model_id=model.id) for model in models
        ),
    )


def _models() -> tuple[ModelDefinition, ...]:
    return (
        _model(ModelKind.OCR_LAYOUT_DETECTION, "PP-DocLayout_plus-L"),
        _model(ModelKind.OCR_TEXT_DETECTION, "PP-OCRv5_server_det"),
        _model(ModelKind.OCR_TEXT_RECOGNITION, "korean_PP-OCRv5_mobile_rec"),
        _model(ModelKind.OCR_TEXTLINE_ORIENTATION, "PP-LCNet_x1_0_textline_ori"),
        _model(ModelKind.OCR_TABLE_CLASSIFICATION, "PP-LCNet_x1_0_table_cls"),
        _model(ModelKind.OCR_TABLE_STRUCTURE_WIRED, "SLANeXt_wired"),
        _model(ModelKind.OCR_TABLE_STRUCTURE, "SLANet_plus"),
        _model(
            ModelKind.OCR_TABLE_CELLS_WIRED,
            "RT-DETR-L_wired_table_cell_det",
        ),
        _model(
            ModelKind.OCR_TABLE_CELLS_WIRELESS,
            "RT-DETR-L_wireless_table_cell_det",
        ),
        _model(ModelKind.OCR_TABLE_ORIENTATION, "PP-LCNet_x1_0_doc_ori"),
    )


def test_resolver_returns_typed_parser_and_ocr_model_details() -> None:
    models = _models()

    resolved = resolve_document_processing_spec(_profile(models), models)

    assert resolved.parser_routes["text/plain"].name == "plain-text"
    assert resolved.ocr is not None
    assert resolved.ocr.pipeline_name == "PP-StructureV3"
    assert resolved.ocr.models[ModelKind.OCR_TEXT_RECOGNITION].name == (
        "korean_PP-OCRv5_mobile_rec"
    )
    assert resolved.ocr.models[ModelKind.OCR_LAYOUT_DETECTION].name == (
        "PP-DocLayout_plus-L"
    )
    assert resolved.ocr.models[ModelKind.OCR_TABLE_STRUCTURE_WIRED].name == (
        "SLANeXt_wired"
    )


def test_resolver_rejects_an_unresolved_model_binding() -> None:
    models = _models()
    profile = _profile(models)
    broken = Profile(
        id=profile.id,
        kind=profile.kind,
        name=profile.name,
        version=profile.version,
        config=profile.config,
        bindings=(
            *profile.bindings[:-1],
            ProfileModelBinding(role=ModelKind.OCR_TABLE_STRUCTURE, model_id=uuid4()),
        ),
        evaluation_state=profile.evaluation_state,
    )

    with pytest.raises(DocumentProcessingResolutionError, match="cannot be resolved"):
        resolve_document_processing_spec(broken, models)


def test_legacy_processing_profile_keeps_legacy_index_namespace() -> None:
    assert (
        index_namespace_document_processing_profile_id(
            LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
        )
        is None
    )
    ocr_profile_id = uuid4()
    assert index_namespace_document_processing_profile_id(ocr_profile_id) == ocr_profile_id
