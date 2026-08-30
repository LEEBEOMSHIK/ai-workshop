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

    def __post_init__(self) -> None:
        if self.configuration_version < 1:
            raise ValueError("A resolved search configuration requires a positive version.")


class SearchConfigurationResolverPort(Protocol):
    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration: ...
