from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from ai_workshop.labs.rag.models.domain import (
    FrozenJsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
)

LEGACY_DOCUMENT_PROCESSING_PROFILE_ID = UUID(
    "00000000-0000-0000-0000-000000000207"
)


def index_namespace_document_processing_profile_id(profile_id: UUID) -> UUID | None:
    """Keep migrated text indices on their legacy namespace; isolate newer processors."""
    if profile_id == LEGACY_DOCUMENT_PROCESSING_PROFILE_ID:
        return None
    return profile_id


class DocumentProcessingResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParserRouteSpec:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class OcrModelSpec:
    id: UUID
    kind: ModelKind
    name: str
    version: int
    source: str
    revision: str
    artifact_sha256: str
    license: str


@dataclass(frozen=True, slots=True)
class DocumentOcrSpec:
    pipeline_name: str
    pipeline_version: str
    languages: tuple[str, ...]
    confidence_threshold: float
    output_schema_version: int
    models: Mapping[ModelKind, OcrModelSpec]


@dataclass(frozen=True, slots=True)
class DocumentProcessingSpec:
    profile_id: UUID
    name: str
    version: int
    parser_routes: Mapping[str, ParserRouteSpec]
    ocr: DocumentOcrSpec | None


def resolve_document_processing_spec(
    profile: Profile,
    models: tuple[ModelDefinition, ...] | list[ModelDefinition],
) -> DocumentProcessingSpec:
    if profile.kind is not ProfileKind.DOCUMENT_PROCESSING:
        raise DocumentProcessingResolutionError(
            "A document processing specification requires a document processing profile."
        )
    parser_policy = _mapping(profile.config.get("parser_policy"))
    route_values = _mapping(parser_policy.get("routes"))
    routes = {
        media_type: ParserRouteSpec(
            name=_string(_mapping(value).get("name")),
            version=_string(_mapping(value).get("version")),
        )
        for media_type, value in route_values.items()
    }
    ocr_value = _mapping(profile.config.get("ocr"))
    ocr = _resolve_ocr(profile, models, ocr_value) if ocr_value.get("enabled") else None
    return DocumentProcessingSpec(
        profile_id=profile.id,
        name=profile.name,
        version=profile.version,
        parser_routes=MappingProxyType(routes),
        ocr=ocr,
    )


def _resolve_ocr(
    profile: Profile,
    models: tuple[ModelDefinition, ...] | list[ModelDefinition],
    config: Mapping[str, FrozenJsonValue],
) -> DocumentOcrSpec:
    by_id = {model.id: model for model in models}
    resolved: dict[ModelKind, OcrModelSpec] = {}
    for binding in profile.bindings:
        model = by_id.get(binding.model_id)
        if model is None or model.kind is not binding.role:
            raise DocumentProcessingResolutionError(
                "A document processing OCR model binding cannot be resolved."
            )
        resolved[binding.role] = OcrModelSpec(
            id=model.id,
            kind=model.kind,
            name=model.name,
            version=model.version,
            source=_string(model.config.get("source")),
            revision=_string(model.config.get("revision")),
            artifact_sha256=_string(model.config.get("artifact_sha256")),
            license=_string(model.config.get("license")),
        )
    return DocumentOcrSpec(
        pipeline_name=_string(config.get("pipeline_name")),
        pipeline_version=_string(config.get("pipeline_version")),
        languages=tuple(_string(item) for item in _sequence(config.get("languages"))),
        confidence_threshold=_float(config.get("confidence_threshold")),
        output_schema_version=_int(config.get("output_schema_version")),
        models=MappingProxyType(resolved),
    )


def _mapping(value: FrozenJsonValue | None) -> Mapping[str, FrozenJsonValue]:
    if not isinstance(value, Mapping):
        raise DocumentProcessingResolutionError("A document processing object is invalid.")
    return value


def _sequence(value: FrozenJsonValue | None) -> tuple[FrozenJsonValue, ...]:
    if not isinstance(value, tuple):
        raise DocumentProcessingResolutionError("A document processing list is invalid.")
    return value


def _string(value: FrozenJsonValue | None) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentProcessingResolutionError("A document processing string is invalid.")
    return value


def _float(value: FrozenJsonValue | None) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise DocumentProcessingResolutionError("A document processing number is invalid.")
    return float(value)


def _int(value: FrozenJsonValue | None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DocumentProcessingResolutionError("A document processing integer is invalid.")
    return value
