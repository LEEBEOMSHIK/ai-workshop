from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.generation.contracts import GenerationRuntimePort
from ai_workshop.labs.rag.generation.domain import GenerationProfile
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.models.domain import Profile
from ai_workshop.labs.rag.retrieval.domain import SearchIndexTarget


@dataclass(frozen=True, slots=True)
class ResolvedWorkspacePolicyApproval:
    workspace_id: UUID
    policy_version_id: UUID


@dataclass(frozen=True, slots=True)
class ResolvedExternalApproval:
    configuration_version_id: UUID
    deployment_version_id: UUID
    installation_policy_version_id: UUID
    disclosure_version: str
    workspace_policies: tuple[ResolvedWorkspacePolicyApproval, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSearchConfiguration:
    configuration_id: UUID
    configuration_version_id: UUID
    configuration_version: int
    indexing_profile_id: UUID
    retrieval_profile: Profile
    answer_policy_version_id: UUID | None
    answer_policy: AnswerPolicy | None
    active_index_alias: SearchIndexTarget
    embedding: EmbeddingPort
    query_max_tokens: int = 512
    workspace_ids: tuple[UUID, ...] = ()
    experimental: bool = True
    generation_profile: GenerationProfile | None = None
    generation_runtime: GenerationRuntimePort | None = None
    external_approval: ResolvedExternalApproval | None = None

    def __post_init__(self) -> None:
        if self.configuration_version < 1:
            raise ValueError("A resolved search configuration requires a positive version.")
        if self.query_max_tokens < 1:
            raise ValueError("A resolved search configuration requires a token limit.")
        if (
            self.answer_policy is not None
            and self.answer_policy.require_complete_provenance is not True
        ):
            raise ValueError("The extractive V1 policy requires complete provenance.")
        if self.generation_profile is None and self.generation_runtime is not None:
            raise ValueError(
                "A resolved generation runtime requires its exact profile."
            )
        if self.generation_profile is None and self.external_approval is not None:
            raise ValueError(
                "A resolved external approval requires its exact generation profile."
            )


class SearchConfigurationResolverPort(Protocol):
    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration: ...

    async def resolve_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration: ...
