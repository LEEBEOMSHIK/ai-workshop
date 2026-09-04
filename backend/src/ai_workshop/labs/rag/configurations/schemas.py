from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    ExternalTransferApprovalConfirmation,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.generation.domain import (
    ExternalGenerationDisclosureVersion,
)
from ai_workshop.labs.rag.models.domain import EvaluationState


class AnswerPolicyCreate(BaseModel):
    mode: Literal["extractive", "generative"] = "extractive"
    min_semantic_score: float = Field(ge=0.0, le=1.0)
    min_keyword_coverage: float = Field(ge=0.0, le=1.0)
    require_complete_provenance: Literal[True] = True
    conflict_mode: Literal["separate_sources"] = "separate_sources"


class ExternalTransferApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    disclosure_version: ExternalGenerationDisclosureVersion

    def to_domain(self) -> ExternalTransferApprovalConfirmation:
        return ExternalTransferApprovalConfirmation(
            confirmed=self.confirmed,
            disclosure_version=self.disclosure_version,
        )


class SavedRagConfigurationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
    generation_profile_id: UUID | None = None
    answer_policy: AnswerPolicyCreate
    workspace_ids: list[UUID] = Field(min_length=1)
    external_transfer_approval: ExternalTransferApprovalInput | None = None


class AnswerPolicyVersionResponse(BaseModel):
    id: UUID
    version: int
    mode: Literal["extractive", "generative"]
    min_semantic_score: float
    min_keyword_coverage: float
    require_complete_provenance: Literal[True]
    conflict_mode: Literal["separate_sources"]

    @classmethod
    def from_domain(cls, policy: AnswerPolicyVersion) -> Self:
        return cls(
            id=policy.id,
            version=policy.version,
            mode=policy.mode,
            min_semantic_score=policy.min_semantic_score,
            min_keyword_coverage=policy.min_keyword_coverage,
            require_complete_provenance=policy.require_complete_provenance,
            conflict_mode=policy.conflict_mode,
        )


class SavedRagConfigurationResponse(BaseModel):
    id: UUID
    version_id: UUID
    owner_id: UUID | None
    name: str
    version: int
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
    generation_profile_id: UUID | None
    answer_policy: AnswerPolicyVersionResponse
    workspace_ids: list[UUID]
    evaluation_state: EvaluationState
    is_system: bool
    is_default: bool
    experimental: bool
    search_ready: bool
    answer_ready: bool
    service_ready: bool
    search_reasons: list[str]
    answer_reasons: list[str]

    @classmethod
    def from_domain(
        cls,
        configuration: SavedRagConfiguration,
        *,
        search_ready: bool,
        answer_ready: bool = False,
        service_ready: bool = False,
        search_reasons: tuple[str, ...] = (),
        answer_reasons: tuple[str, ...] = ("generation_not_configured",),
    ) -> Self:
        return cls(
            id=configuration.id,
            version_id=configuration.version_id,
            owner_id=configuration.owner_id,
            name=configuration.name,
            version=configuration.version,
            indexing_profile_id=configuration.indexing_profile_id,
            retrieval_profile_id=configuration.retrieval_profile_id,
            generation_profile_id=configuration.generation_profile_id,
            answer_policy=AnswerPolicyVersionResponse.from_domain(
                configuration.answer_policy_version
            ),
            workspace_ids=list(configuration.workspace_ids),
            evaluation_state=configuration.evaluation_state,
            is_system=configuration.is_system,
            is_default=configuration.is_default,
            experimental=configuration.experimental,
            search_ready=search_ready,
            answer_ready=answer_ready,
            service_ready=service_ready,
            search_reasons=list(search_reasons),
            answer_reasons=list(answer_reasons),
        )
