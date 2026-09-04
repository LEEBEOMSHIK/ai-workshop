from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast
from uuid import UUID, uuid4

from ai_workshop.labs.rag.evaluation.domain import (
    EvaluationPolicy,
    PromotionEvidence,
    PromotionGate,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelKind,
    Profile,
    ProfileKind,
)

E5_MODEL_DEFINITION_ID = UUID("00000000-0000-0000-0000-000000000101")
E5_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
BM25_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000202")
BM25_BASELINE_CONFIGURATION_ID = UUID("00000000-0000-0000-0000-000000000501")
BM25_BASELINE_ANSWER_POLICY_VERSION_ID = UUID(
    "00000000-0000-0000-0000-000000000502"
)
BM25_BASELINE_CONFIGURATION_VERSION_ID = UUID(
    "00000000-0000-0000-0000-000000000503"
)
BM25_BASELINE_NAME = "BM25 기준선"
EXTERNAL_GENERATION_DISCLOSURE_VERSION = "external-generation-v1"


class ConfigurationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalTransferApprovalConfirmation:
    confirmed: bool
    disclosure_version: str

    def __post_init__(self) -> None:
        if (
            self.confirmed is not True
            or self.disclosure_version != EXTERNAL_GENERATION_DISCLOSURE_VERSION
        ):
            raise ConfigurationValidationError(
                "External transfer approval must use the current disclosure."
            )


def validate_v1_retrieval_profile(profile: Profile) -> None:
    if profile.kind is not ProfileKind.RETRIEVAL:
        raise ConfigurationValidationError(
            "A Saved RAG Configuration requires a retrieval profile."
        )
    if any(binding.role is ModelKind.RERANKER for binding in profile.bindings):
        raise ConfigurationValidationError(
            "Extractive V1 does not allow a reranker binding."
        )
    if any(key.startswith("reranker") and key != "reranker" for key in profile.config):
        raise ConfigurationValidationError(
            "Extractive V1 does not allow a reranker selection."
        )
    reranker = profile.config.get("reranker")
    if reranker is None:
        return
    if (
        not isinstance(reranker, Mapping)
        or set(reranker) != {"enabled"}
        or reranker.get("enabled") is not False
    ):
        raise ConfigurationValidationError(
            "Extractive V1 accepts only disabled reranker metadata."
        )


@dataclass(frozen=True, slots=True)
class AnswerPolicyVersion:
    id: UUID
    configuration_id: UUID
    version: int
    mode: Literal["extractive", "generative"]
    min_semantic_score: float
    min_keyword_coverage: float
    require_complete_provenance: Literal[True]
    conflict_mode: Literal["separate_sources"]

    @classmethod
    def create(
        cls,
        *,
        configuration_id: UUID,
        version: int,
        mode: str = "extractive",
        min_semantic_score: float,
        min_keyword_coverage: float,
        require_complete_provenance: bool,
        conflict_mode: str,
    ) -> "AnswerPolicyVersion":
        if version < 1:
            raise ConfigurationValidationError(
                "An Answer Policy version must be positive."
            )
        if mode not in {"extractive", "generative"}:
            raise ConfigurationValidationError(
                "An Answer Policy mode must be extractive or generative."
            )
        policy = AnswerPolicy(
            min_semantic_score=min_semantic_score,
            min_keyword_coverage=min_keyword_coverage,
            require_complete_provenance=require_complete_provenance,
            conflict_mode=conflict_mode,
        )
        return cls(
            id=uuid4(),
            configuration_id=configuration_id,
            version=version,
            mode=cast(Literal["extractive", "generative"], mode),
            min_semantic_score=policy.min_semantic_score,
            min_keyword_coverage=policy.min_keyword_coverage,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
        )

    def to_answer_policy(self) -> AnswerPolicy:
        return AnswerPolicy(
            min_semantic_score=self.min_semantic_score,
            min_keyword_coverage=self.min_keyword_coverage,
            require_complete_provenance=self.require_complete_provenance,
            conflict_mode=self.conflict_mode,
        )


@dataclass(frozen=True, slots=True)
class SavedRagConfiguration:
    id: UUID
    version_id: UUID
    owner_id: UUID | None
    name: str
    version: int
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
    generation_profile_id: UUID | None
    answer_policy_version_id: UUID
    answer_policy_version: AnswerPolicyVersion
    workspace_ids: tuple[UUID, ...]
    evaluation_state: EvaluationState
    is_system: bool
    is_default: bool

    @classmethod
    def create(
        cls,
        *,
        configuration_id: UUID,
        configuration_version_id: UUID,
        owner_id: UUID | None,
        name: str,
        version: int,
        indexing_profile_id: UUID,
        retrieval_profile_id: UUID,
        retrieval_indexing_profile_id: UUID,
        generation_profile_id: UUID | None,
        answer_policy_version: AnswerPolicyVersion,
        workspace_ids: tuple[UUID, ...],
        evaluation_state: EvaluationState = EvaluationState.PENDING,
        is_system: bool = False,
        is_default: bool = False,
    ) -> "SavedRagConfiguration":
        clean_name = name.strip()
        if not clean_name or version < 1:
            raise ConfigurationValidationError(
                "A Saved RAG Configuration requires a name and positive version."
            )
        if retrieval_indexing_profile_id != indexing_profile_id:
            raise ConfigurationValidationError(
                "The retrieval profile must reference the selected indexing profile."
            )
        if (
            answer_policy_version.mode == "extractive"
            and generation_profile_id is not None
        ):
            raise ConfigurationValidationError(
                "Generation Profiles are not supported by extractive V1."
            )
        if (
            answer_policy_version.mode == "generative"
            and generation_profile_id is None
        ):
            raise ConfigurationValidationError(
                "A generative configuration requires a Generation Profile."
            )
        if answer_policy_version.configuration_id != configuration_id:
            raise ConfigurationValidationError(
                "The Answer Policy version must belong to the Saved RAG Configuration."
            )
        if answer_policy_version.version != version:
            raise ConfigurationValidationError(
                "Answer Policy and Saved RAG Configuration versions must match."
            )
        answer_policy_version.to_answer_policy()
        if len(set(workspace_ids)) != len(workspace_ids):
            raise ConfigurationValidationError(
                "Workspace subscriptions must contain unique workspace IDs."
            )
        if not is_system and not workspace_ids:
            raise ConfigurationValidationError(
                "A user configuration requires at least one workspace subscription."
            )
        if is_system != (owner_id is None):
            raise ConfigurationValidationError(
                "Only an ownerless configuration can be a system configuration."
            )
        if is_default and evaluation_state is not EvaluationState.PASSED:
            raise ConfigurationValidationError(
                "A default configuration requires a passed evaluation."
            )
        return cls(
            id=configuration_id,
            version_id=configuration_version_id,
            owner_id=owner_id,
            name=clean_name,
            version=version,
            indexing_profile_id=indexing_profile_id,
            retrieval_profile_id=retrieval_profile_id,
            generation_profile_id=generation_profile_id,
            answer_policy_version_id=answer_policy_version.id,
            answer_policy_version=answer_policy_version,
            workspace_ids=workspace_ids,
            evaluation_state=evaluation_state,
            is_system=is_system,
            is_default=is_default,
        )

    @property
    def experimental(self) -> bool:
        return not (
            self.evaluation_state is EvaluationState.PASSED and self.is_default
        )

    def as_default(
        self,
        *,
        policy: EvaluationPolicy | None,
        evidence: PromotionEvidence,
    ) -> "SavedRagConfiguration":
        if evidence.configuration_version_id != self.version_id or not PromotionGate.qualifies(
            policy, evidence
        ):
            raise ConfigurationValidationError(
                "An exact policy-backed passing evaluation is required for promotion."
            )
        return replace(self, evaluation_state=EvaluationState.PASSED, is_default=True)
