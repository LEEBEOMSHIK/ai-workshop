from uuid import uuid4

import pytest

from ai_workshop.labs.rag.models.document_processing import (
    DocumentProcessingResolutionError,
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


def test_resolver_returns_typed_parser_and_ocr_model_details() -> None:
    models = (
        _model(ModelKind.OCR_TEXT_DETECTION, "PP-OCRv5_server_det"),
        _model(ModelKind.OCR_TEXT_RECOGNITION, "korean_PP-OCRv5_mobile_rec"),
        _model(ModelKind.OCR_TABLE_STRUCTURE, "SLANet_plus"),
    )

    resolved = resolve_document_processing_spec(_profile(models), models)

    assert resolved.parser_routes["text/plain"].name == "plain-text"
    assert resolved.ocr is not None
    assert resolved.ocr.pipeline_name == "PP-StructureV3"
    assert resolved.ocr.models[ModelKind.OCR_TEXT_RECOGNITION].name == (
        "korean_PP-OCRv5_mobile_rec"
    )


def test_resolver_rejects_an_unresolved_model_binding() -> None:
    models = (
        _model(ModelKind.OCR_TEXT_DETECTION, "PP-OCRv5_server_det"),
        _model(ModelKind.OCR_TEXT_RECOGNITION, "korean_PP-OCRv5_mobile_rec"),
        _model(ModelKind.OCR_TABLE_STRUCTURE, "SLANet_plus"),
    )
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
