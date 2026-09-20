from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from re import fullmatch
from types import MappingProxyType
from uuid import UUID, uuid4

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type FrozenJsonValue = JsonScalar | tuple[FrozenJsonValue, ...] | Mapping[str, FrozenJsonValue]


class ModelKind(StrEnum):
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    LLM = "llm"
    OCR_LAYOUT_DETECTION = "ocr_layout_detection"
    OCR_TEXT_DETECTION = "ocr_text_detection"
    OCR_TEXT_RECOGNITION = "ocr_text_recognition"
    OCR_TEXTLINE_ORIENTATION = "ocr_textline_orientation"
    OCR_TABLE_CLASSIFICATION = "ocr_table_classification"
    OCR_TABLE_STRUCTURE_WIRED = "ocr_table_structure_wired"
    OCR_TABLE_STRUCTURE = "ocr_table_structure"
    OCR_TABLE_CELLS_WIRED = "ocr_table_cells_wired"
    OCR_TABLE_CELLS_WIRELESS = "ocr_table_cells_wireless"
    OCR_TABLE_ORIENTATION = "ocr_table_orientation"


PP_STRUCTURE_V3_MODEL_KINDS = frozenset(
    {
        ModelKind.OCR_LAYOUT_DETECTION,
        ModelKind.OCR_TEXT_DETECTION,
        ModelKind.OCR_TEXT_RECOGNITION,
        ModelKind.OCR_TEXTLINE_ORIENTATION,
        ModelKind.OCR_TABLE_CLASSIFICATION,
        ModelKind.OCR_TABLE_STRUCTURE_WIRED,
        ModelKind.OCR_TABLE_STRUCTURE,
        ModelKind.OCR_TABLE_CELLS_WIRED,
        ModelKind.OCR_TABLE_CELLS_WIRELESS,
        ModelKind.OCR_TABLE_ORIENTATION,
    }
)


class ProfileKind(StrEnum):
    DOCUMENT_PROCESSING = "document_processing"
    INDEXING = "indexing"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"


class EvaluationState(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ProfileValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PdfRasterSpec:
    raster_dpi: int
    max_page_pixels: int
    max_pages: int


def resolve_pdf_raster_spec(
    media_type: str,
    route: Mapping[str, object],
    *,
    ocr_enabled: bool,
) -> PdfRasterSpec | None:
    if route.get("name") != "pymupdf-ocr":
        return None
    if media_type != "application/pdf" or route.get("version") not in ("1", "2") or not ocr_enabled:
        raise ProfileValidationError("PDF OCR requires its supported route and enabled OCR.")
    options = route.get("options")
    bounds = {"raster_dpi": (72, 600), "max_page_pixels": (1, 100_000_000), "max_pages": (1, 2000)}
    if not isinstance(options, Mapping) or set(options) != set(bounds):
        raise ProfileValidationError("PDF OCR requires explicit raster options.")
    values: dict[str, int] = {}
    for name, (minimum, maximum) in bounds.items():
        value = options[name]
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ProfileValidationError("PDF OCR raster options exceed supported integer limits.")
        values[name] = value
    return PdfRasterSpec(**values)


def freeze_json(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: FrozenJsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _validate_environment_references(config: Mapping[str, JsonValue]) -> None:
    sensitive_suffixes = ("key", "secret", "token", "password", "credential")
    for key, value in config.items():
        normalized = key.casefold()
        if normalized.endswith("_env"):
            if not isinstance(value, str) or fullmatch(r"[A-Z][A-Z0-9_]*", value) is None:
                raise ProfileValidationError(
                    f"{key} must contain an environment variable reference."
                )
        elif normalized in sensitive_suffixes or normalized.endswith(
            tuple(f"_{suffix}" for suffix in sensitive_suffixes)
        ):
            raise ProfileValidationError(
                f"{key} must use an environment variable reference instead of a literal secret."
            )
        if isinstance(value, dict):
            _validate_environment_references(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _validate_environment_references(item)


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    id: UUID
    kind: ModelKind
    name: str
    version: int
    config: Mapping[str, FrozenJsonValue]

    @classmethod
    def create(
        cls,
        *,
        kind: ModelKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
    ) -> "ModelDefinition":
        if not name.strip() or version < 1:
            raise ProfileValidationError("Model name and positive version are required.")
        _validate_environment_references(config)
        _validate_model_shape(kind, config)
        frozen = freeze_json(config)
        if not isinstance(frozen, Mapping):
            raise TypeError("Model configuration must be a mapping.")
        return cls(uuid4(), kind, name.strip(), version, frozen)


@dataclass(frozen=True, slots=True)
class ProfileModelBinding:
    role: ModelKind
    model_id: UUID


@dataclass(frozen=True, slots=True)
class Profile:
    id: UUID
    kind: ProfileKind
    name: str
    version: int
    config: Mapping[str, FrozenJsonValue]
    bindings: tuple[ProfileModelBinding, ...]
    evaluation_state: EvaluationState
    is_default: bool = False
    deployment_version_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        kind: ProfileKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
        bindings: tuple[ProfileModelBinding, ...],
        deployment_version_id: UUID | None = None,
        evaluation_state: EvaluationState = EvaluationState.DRAFT,
        is_default: bool = False,
    ) -> "Profile":
        if not name.strip() or version < 1:
            raise ProfileValidationError("Profile name and positive version are required.")
        _validate_environment_references(config)
        _validate_profile_shape(kind, config, bindings, deployment_version_id)
        if is_default and evaluation_state is not EvaluationState.PASSED:
            raise ProfileValidationError("A default profile requires a passed evaluation.")
        frozen = freeze_json(config)
        if not isinstance(frozen, Mapping):
            raise TypeError("Profile configuration must be a mapping.")
        return cls(
            uuid4(),
            kind,
            name.strip(),
            version,
            frozen,
            tuple(bindings),
            evaluation_state,
            is_default,
            deployment_version_id,
        )

    def as_default(self) -> "Profile":
        if self.evaluation_state is not EvaluationState.PASSED:
            raise ProfileValidationError("A passed evaluation is required for default promotion.")
        return replace(self, is_default=True)

    @property
    def legacy(self) -> bool:
        return (
            self.kind is ProfileKind.GENERATION
            and self.deployment_version_id is None
            and any(binding.role is ModelKind.LLM for binding in self.bindings)
        )


def _validate_profile_shape(
    kind: ProfileKind,
    config: Mapping[str, JsonValue],
    bindings: tuple[ProfileModelBinding, ...],
    deployment_version_id: UUID | None,
) -> None:
    roles = {binding.role for binding in bindings}
    if kind is ProfileKind.DOCUMENT_PROCESSING:
        _validate_document_processing_profile(config, roles, deployment_version_id)
    elif kind is ProfileKind.INDEXING:
        if deployment_version_id is not None:
            raise ProfileValidationError("A non-generation profile cannot bind a Deployment.")
        if "chunker" not in config:
            raise ProfileValidationError("An indexing profile requires a chunker configuration.")
        if roles != {ModelKind.EMBEDDING}:
            raise ProfileValidationError("An indexing profile requires an embedding model.")
    elif kind is ProfileKind.RETRIEVAL:
        if deployment_version_id is not None:
            raise ProfileValidationError("A non-generation profile cannot bind a Deployment.")
        if "bm25" not in config:
            raise ProfileValidationError("A retrieval profile requires BM25 configuration.")
        if ModelKind.LLM in roles:
            raise ProfileValidationError("An LLM cannot be bound directly to retrieval.")
        has_dense = "dense" in config
        if has_dense and ("rrf" not in config or "indexing_profile_id" not in config):
            raise ProfileValidationError(
                "Dense retrieval requires RRF and an indexing profile reference."
            )
        if ModelKind.RERANKER in roles and "reranker" not in config:
            raise ProfileValidationError("A reranker binding requires reranker configuration.")
    else:
        _validate_generation_profile(config, bindings, deployment_version_id)


def _validate_model_shape(kind: ModelKind, config: Mapping[str, JsonValue]) -> None:
    if kind is ModelKind.LLM and "model_identifier" in config:
        identity = config["model_identifier"]
        if (
            set(config) != {"model_identifier"}
            or type(identity) is not str
            or not identity.strip()
            or len(identity) > 180
        ):
            raise ProfileValidationError("An LLM model requires an exact model identity.")
        return
    if kind is ModelKind.LLM and (
        config.get("provider") != "openai_compatible"
        or config.get("data_policy") != "local_only"
        or not isinstance(config.get("runtime_model"), str)
        or not str(config["runtime_model"]).strip()
    ):
        raise ProfileValidationError(
            "An LLM model requires a local OpenAI-compatible runtime identity."
        )
    if kind not in PP_STRUCTURE_V3_MODEL_KINDS:
        return
    required_strings = ("source", "revision", "artifact_sha256", "license")
    if (
        config.get("data_policy") != "local_only"
        or any(
            not isinstance(config.get(key), str) or not str(config[key]).strip()
            for key in required_strings
        )
        or fullmatch(r"[0-9a-f]{64}", str(config.get("artifact_sha256", ""))) is None
    ):
        raise ProfileValidationError("An OCR model requires immutable local artifact metadata.")


def _validate_document_processing_profile(
    config: Mapping[str, JsonValue],
    roles: set[ModelKind],
    deployment_version_id: UUID | None,
) -> None:
    if deployment_version_id is not None:
        raise ProfileValidationError("A non-generation profile cannot bind a Deployment.")
    parser_policy = config.get("parser_policy")
    if not isinstance(parser_policy, Mapping):
        raise ProfileValidationError("A document processing profile requires a parser policy.")
    routes = parser_policy.get("routes")
    if not isinstance(routes, Mapping) or not routes:
        raise ProfileValidationError("A document processing profile requires parser routes.")
    ocr = config.get("ocr")
    if not isinstance(ocr, Mapping) or not isinstance(ocr.get("enabled"), bool):
        raise ProfileValidationError("A document processing profile requires a typed OCR policy.")
    required_roles = PP_STRUCTURE_V3_MODEL_KINDS
    for media_type, route in routes.items():
        if isinstance(route, Mapping):
            resolve_pdf_raster_spec(media_type, route, ocr_enabled=ocr["enabled"] is True)
    if ocr["enabled"] is False:
        if roles:
            raise ProfileValidationError(
                "An OCR-disabled document processing profile cannot bind OCR models."
            )
        return
    if roles != required_roles:
        raise ProfileValidationError(
            "An OCR-enabled document processing profile requires all OCR model roles."
        )
    required_strings = ("pipeline_name", "pipeline_version", "data_policy")
    if (
        any(
            not isinstance(ocr.get(key), str) or not str(ocr[key]).strip()
            for key in required_strings
        )
        or ocr.get("data_policy") != "local_only"
    ):
        raise ProfileValidationError("An OCR policy requires a local pipeline identity.")
    languages = ocr.get("languages")
    threshold = ocr.get("confidence_threshold")
    schema_version = ocr.get("output_schema_version")
    if (
        not isinstance(languages, list)
        or not languages
        or any(not isinstance(item, str) or not item.strip() for item in languages)
        or not isinstance(threshold, int | float)
        or isinstance(threshold, bool)
        or not 0 <= threshold <= 1
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise ProfileValidationError(
            "An OCR policy requires languages, confidence, and output schema settings."
        )


def _validate_generation_profile(
    config: Mapping[str, JsonValue],
    bindings: tuple[ProfileModelBinding, ...],
    deployment_version_id: UUID | None,
) -> None:
    from ai_workshop.labs.rag.models.context_evidence import resolve_evidence_budget

    try:
        resolve_evidence_budget(config)
    except ValueError as exc:
        raise ProfileValidationError(str(exc)) from exc
    required = {
        "prompt_ref",
        "context_prompt_ref",
        "citation_mode",
        "context_policy",
        "generation",
    }
    if not required.issubset(config):
        raise ProfileValidationError(
            "A generation profile requires prompt, context, citation, and output settings."
        )
    if any(
        not isinstance(config[key], str) or not str(config[key]).strip()
        for key in ("prompt_ref", "context_prompt_ref")
    ):
        raise ProfileValidationError("A generation profile requires nonempty prompt references.")
    if config["citation_mode"] != "required":
        raise ProfileValidationError("A generation profile requires citation validation.")
    if deployment_version_id is None or bindings:
        raise ProfileValidationError(
            "A generation profile requires exactly one Deployment and no model binding."
        )

    context = config["context_policy"]
    generation = config["generation"]
    if not isinstance(context, Mapping) or not isinstance(generation, Mapping):
        raise ProfileValidationError("A generation profile requires structured settings.")
    max_turns = context.get("max_history_turns")
    max_context_tokens = context.get("max_history_tokens")
    if (
        not isinstance(max_turns, int)
        or isinstance(max_turns, bool)
        or max_turns < 1
        or not isinstance(max_context_tokens, int)
        or isinstance(max_context_tokens, bool)
        or max_context_tokens < 1
    ):
        raise ProfileValidationError("A generation profile requires positive context limits.")

    timeout = generation.get("timeout_seconds")
    max_output_tokens = generation.get("max_output_tokens")
    temperature = generation.get("temperature")
    schema_version = generation.get("response_schema_version")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ProfileValidationError("A generation profile requires a positive timeout.")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
    ):
        raise ProfileValidationError("A generation profile requires a positive output token limit.")
    if (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= temperature <= 2
    ):
        raise ProfileValidationError(
            "A generation profile temperature must be between zero and two."
        )
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise ProfileValidationError("A generation profile requires a response schema version.")
