from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.models.domain import Profile
from ai_workshop.labs.rag.retrieval.domain import ActiveIndexAlias


@dataclass(frozen=True, slots=True)
class ResolvedSearchConfiguration:
    configuration_id: UUID
    configuration_version_id: UUID
    configuration_version: int
    indexing_profile_id: UUID
    retrieval_profile: Profile
    answer_policy_version_id: UUID | None
    answer_policy: AnswerPolicy | None
    active_index_alias: ActiveIndexAlias
    embedding: EmbeddingPort
    workspace_ids: tuple[UUID, ...] = ()
    experimental: bool = True

    def __post_init__(self) -> None:
        if self.configuration_version < 1:
            raise ValueError("A resolved search configuration requires a positive version.")
        if (
            self.answer_policy is not None
            and self.answer_policy.require_complete_provenance is not True
        ):
            raise ValueError("The extractive V1 policy requires complete provenance.")


class SearchConfigurationResolverPort(Protocol):
    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration: ...
