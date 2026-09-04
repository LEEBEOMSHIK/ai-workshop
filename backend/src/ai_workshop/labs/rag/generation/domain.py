from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)

type ExternalGenerationDisclosureVersion = Literal["external-generation-v1"]
type NonExternalGenerationDisclosureVersion = Literal[
    "local-generation-v1", "on-premise-generation-v1"
]
type GenerationDisclosureVersion = (
    ExternalGenerationDisclosureVersion | NonExternalGenerationDisclosureVersion
)

EXTERNAL_GENERATION_DISCLOSURE_VERSION: ExternalGenerationDisclosureVersion = (
    "external-generation-v1"
)

_DISCLOSURES: dict[ExecutionLocation, tuple[GenerationDisclosureVersion, str]] = {
    ExecutionLocation.LOCAL: (
        "local-generation-v1",
        "사내 로컬 모델에서 처리됩니다.",
    ),
    ExecutionLocation.ON_PREMISE: (
        "on-premise-generation-v1",
        "사내 온프레미스 모델에서 처리됩니다.",
    ),
    ExecutionLocation.EXTERNAL: (
        EXTERNAL_GENERATION_DISCLOSURE_VERSION,
        "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 전송됩니다.",
    ),
}


@dataclass(frozen=True, slots=True)
class GenerationDisclosure:
    required: bool
    version: GenerationDisclosureVersion
    text: str
    transmitted_data_categories: tuple[str, ...]


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class GenerationStatus(StrEnum):
    ANSWERED = "answered"
    NOT_REQUESTED = "not_requested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"


@dataclass(frozen=True, slots=True)
class GenerationExecutionSnapshot:
    provider: ProviderKind
    model_name: str
    model_version: int
    deployment_name: str
    location: ExecutionLocation
    external_transfer: bool
    disclosure: str
    disclosure_version: str


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    role: ConversationRole
    content: str
    turn_id: UUID | None = None
    validation_token: str | None = None

    def __post_init__(self) -> None:
        clean_content = self.content.strip()
        if not clean_content:
            raise ValueError("A conversation turn requires content.")
        if self.role is ConversationRole.ASSISTANT and not self.validation_token:
            raise ValueError("An assistant turn requires a validation token.")
        object.__setattr__(self, "content", clean_content)


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    max_history_turns: int
    max_history_tokens: int

    def __post_init__(self) -> None:
        if self.max_history_turns < 1 or self.max_history_tokens < 1:
            raise ValueError("Context policy limits must be positive.")

    def select(
        self,
        history: tuple[ConversationTurn, ...],
        *,
        token_counter: Callable[[str], int],
    ) -> tuple[ConversationTurn, ...]:
        selected: list[ConversationTurn] = []
        token_total = 0
        for turn in reversed(history[-self.max_history_turns :]):
            turn_tokens = token_counter(turn.content)
            if turn_tokens < 0:
                raise ValueError("Token counts cannot be negative.")
            if token_total + turn_tokens > self.max_history_tokens:
                break
            selected.append(turn)
            token_total += turn_tokens
        selected.reverse()
        return tuple(selected)


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    profile_id: UUID
    profile_name: str
    profile_version: int
    model_id: UUID
    model_name: str
    model_version: int
    runtime_model: str
    prompt_ref: str
    context_prompt_ref: str
    context_policy: ContextPolicy
    timeout_seconds: float
    max_output_tokens: int
    temperature: float
    response_schema_version: int
    deployment: ModelDeploymentVersion | None = None

    def __post_init__(self) -> None:
        string_fields = (
            ("profile name", self.profile_name),
            ("model name", self.model_name),
            ("runtime model", self.runtime_model),
            ("prompt", self.prompt_ref),
            ("context prompt", self.context_prompt_ref),
        )
        for label, value in string_fields:
            if not value.strip():
                raise ValueError(f"Generation {label} is required.")
        if self.profile_version < 1 or self.model_version < 1:
            raise ValueError("Generation profile and model versions must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("Generation timeout must be positive.")
        if self.max_output_tokens < 1:
            raise ValueError("Generation output token limit must be positive.")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("Generation temperature must be between zero and two.")
        if self.response_schema_version < 1:
            raise ValueError("Generation response schema version must be positive.")
        if self.deployment is not None and (
            self.deployment.model_definition_id != self.model_id
            or self.deployment.provider_model_id != self.runtime_model
        ):
            raise ValueError("Generation Deployment identity must match the model contract.")


@dataclass(frozen=True, slots=True)
class ContextualizationRequest:
    question: str
    history: tuple[ConversationTurn, ...]
    profile: GenerationProfile


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    question: str
    resolved_query: str
    history: tuple[ConversationTurn, ...]
    evidence: tuple["GroundingEvidence", ...]
    profile: GenerationProfile
    correlation_id: str


@dataclass(frozen=True, slots=True)
class GroundingEvidence:
    evidence_id: UUID
    text: str
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID | None
    chunk_id: UUID | None
    element_id: UUID
    page: int | None
    char_start: int
    char_end: int
    bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    text: str
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        clean_text = self.text.strip()
        if not clean_text:
            raise ValueError("A generated claim requires text.")
        object.__setattr__(self, "text", clean_text)


@dataclass(frozen=True, slots=True)
class StructuredGeneration:
    schema_version: int
    claims: tuple[GeneratedClaim, ...]

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("Generation schema version must be positive.")


@dataclass(frozen=True, slots=True)
class GeneratedCitation:
    claim_index: int
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    status: GenerationStatus
    text: str | None = None
    citations: tuple[GeneratedCitation, ...] = ()
    reason_codes: tuple[str, ...] = ()
    turn_id: UUID | None = None
    validation_token: str | None = None
    execution: GenerationExecutionSnapshot | None = None


def generation_execution_snapshot(
    profile: GenerationProfile,
) -> GenerationExecutionSnapshot:
    deployment = profile.deployment
    if deployment is None:
        raise ValueError("Generation execution requires an exact Deployment.")
    disclosure = generation_disclosure(deployment)
    return GenerationExecutionSnapshot(
        provider=deployment.provider,
        model_name=profile.model_name,
        model_version=profile.model_version,
        deployment_name=deployment.display_name,
        location=deployment.location,
        external_transfer=deployment.external_transfer,
        disclosure=disclosure.text,
        disclosure_version=disclosure.version,
    )


def generation_disclosure(
    deployment: ModelDeploymentVersion,
) -> GenerationDisclosure:
    version, text = _DISCLOSURES[deployment.location]
    return GenerationDisclosure(
        required=deployment.external_transfer,
        version=version,
        text=text,
        transmitted_data_categories=(
            deployment.transmitted_data_categories
            if deployment.external_transfer
            else ()
        ),
    )
