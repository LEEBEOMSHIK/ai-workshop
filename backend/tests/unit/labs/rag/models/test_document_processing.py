from dataclasses import replace
from typing import Any
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
    ProfileValidationError,
    freeze_json,
    thaw_json,
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
        bindings=tuple(ProfileModelBinding(role=model.kind, model_id=model.id) for model in models),
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
    assert resolved.ocr.models[ModelKind.OCR_LAYOUT_DETECTION].name == ("PP-DocLayout_plus-L")
    assert resolved.ocr.models[ModelKind.OCR_TABLE_STRUCTURE_WIRED].name == ("SLANeXt_wired")


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
        index_namespace_document_processing_profile_id(LEGACY_DOCUMENT_PROCESSING_PROFILE_ID)
        is None
    )
    ocr_profile_id = uuid4()
    assert index_namespace_document_processing_profile_id(ocr_profile_id) == ocr_profile_id


def _pdf_profile_config(models: tuple[ModelDefinition, ...]) -> dict[str, Any]:
    config = thaw_json(_profile(models).config)
    assert isinstance(config, dict)
    policy = config["parser_policy"]
    assert isinstance(policy, dict)
    routes = policy["routes"]
    assert isinstance(routes, dict)
    routes["application/pdf"] = {
        "name": "pymupdf-ocr",
        "version": "1",
        "options": {"raster_dpi": 144, "max_page_pixels": 16000000, "max_pages": 200},
    }
    return config


def _pdf_profile(config: dict[str, Any], models: tuple[ModelDefinition, ...]) -> Profile:
    return Profile.create(
        kind=ProfileKind.DOCUMENT_PROCESSING,
        name="pdf-ocr",
        version=1,
        config=config,
        bindings=_profile(models).bindings,
    )


@pytest.mark.parametrize("parser_version", ["1", "2"])
def test_pdf_ocr_resolver_preserves_raster_limits_for_worker(parser_version: str) -> None:
    models = _models()
    config = _pdf_profile_config(models)
    config["parser_policy"]["routes"]["application/pdf"]["version"] = parser_version
    spec = resolve_document_processing_spec(
        _pdf_profile(config, models), models
    )
    assert spec.parser_routes["application/pdf"].version == parser_version
    raster = spec.parser_routes["application/pdf"].pdf_raster
    assert raster is not None
    assert (raster.raster_dpi, raster.max_page_pixels, raster.max_pages) == (144, 16000000, 200)


@pytest.mark.parametrize(
    "key,value",
    [
        ("raster_dpi", True),
        ("raster_dpi", 0),
        ("raster_dpi", 601),
        ("raster_dpi", 144.5),
        ("raster_dpi", float("inf")),
        ("max_page_pixels", 0),
        ("max_page_pixels", 100000001),
        ("max_pages", 0),
        ("max_pages", 2001),
        ("max_pages", "200"),
    ],
)
@pytest.mark.parametrize("parser_version", ["1", "2"])
def test_pdf_ocr_profile_rejects_unsafe_raster_options(
    key: str, value: Any, parser_version: str
) -> None:
    models = _models()
    config = _pdf_profile_config(models)
    config["parser_policy"]["routes"]["application/pdf"]["version"] = parser_version
    config["parser_policy"]["routes"]["application/pdf"]["options"][key] = value
    with pytest.raises(ProfileValidationError, match="PDF OCR"):
        _pdf_profile(config, models)


@pytest.mark.parametrize("mutation", ["version", "missing_options", "disabled", "media"])
@pytest.mark.parametrize("parser_version", ["1", "2"])
def test_pdf_ocr_profile_fails_closed_for_invalid_route(mutation: str, parser_version: str) -> None:
    models = _models()
    config = _pdf_profile_config(models)
    routes = config["parser_policy"]["routes"]
    routes["application/pdf"]["version"] = parser_version
    if mutation == "version":
        routes["application/pdf"]["version"] = "3"
    elif mutation == "missing_options":
        del routes["application/pdf"]["options"]
    elif mutation == "disabled":
        config["ocr"]["enabled"] = False
    else:
        routes["text/plain"] = routes.pop("application/pdf")
    with pytest.raises(ProfileValidationError, match="PDF OCR"):
        _pdf_profile(config, models)


def test_saved_pdf_route_is_validated_when_resolving_an_existing_profile() -> None:
    models = _models()
    profile = _profile(models)
    config = _pdf_profile_config(models)
    config["parser_policy"]["routes"]["application/pdf"]["version"] = "future"
    frozen = freeze_json(config)
    from collections.abc import Mapping

    assert isinstance(frozen, Mapping)
    persisted = replace(profile, config=frozen)
    with pytest.raises(DocumentProcessingResolutionError, match="PDF OCR"):
        resolve_document_processing_spec(persisted, models)
