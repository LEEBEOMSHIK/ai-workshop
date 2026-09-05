from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError, replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    ConfigurationValidationError,
    ExternalTransferApprovalConfirmation,
    SavedRagConfiguration,
    validate_v1_retrieval_profile,
)
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationVersionRecord,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
    PromotionEvidence,
)
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.repository import (
    ApprovedWorkspacePolicySnapshot,
    ExternalConfigurationApproval,
)
from ai_workshop.shared.errors import AppError


def _policy(
    *,
    configuration_id=None,
    version: int = 1,
    mode: str = "extractive",
) -> AnswerPolicyVersion:
    return AnswerPolicyVersion.create(
        configuration_id=configuration_id or uuid4(),
        version=version,
        mode=mode,
        min_semantic_score=0.82,
        min_keyword_coverage=0.75,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )


def _configuration(
    *,
    evaluation_state: EvaluationState = EvaluationState.PENDING,
) -> SavedRagConfiguration:
    configuration_id = uuid4()
    indexing_profile_id = uuid4()
    return SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=uuid4(),
        name="내 검색 구성",
        version=1,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=None,
        answer_policy_version=_policy(configuration_id=configuration_id),
        workspace_ids=(uuid4(),),
        evaluation_state=evaluation_state,
    )


def test_retrieval_profile_must_reference_the_exact_indexing_profile() -> None:
    configuration_id = uuid4()
    with pytest.raises(ConfigurationValidationError, match="retrieval profile"):
        SavedRagConfiguration.create(
            configuration_id=configuration_id,
            configuration_version_id=uuid4(),
            owner_id=uuid4(),
            name="호환되지 않는 구성",
            version=1,
            indexing_profile_id=uuid4(),
            retrieval_profile_id=uuid4(),
            retrieval_indexing_profile_id=uuid4(),
            generation_profile_id=None,
            answer_policy_version=_policy(configuration_id=configuration_id),
            workspace_ids=(uuid4(),),
        )


def test_generation_profile_is_rejected_in_extractive_v1() -> None:
    configuration_id = uuid4()
    indexing_profile_id = uuid4()

    with pytest.raises(ConfigurationValidationError, match="Generation"):
        SavedRagConfiguration.create(
            configuration_id=configuration_id,
            configuration_version_id=uuid4(),
            owner_id=uuid4(),
            name="LLM 구성",
            version=1,
            indexing_profile_id=indexing_profile_id,
            retrieval_profile_id=uuid4(),
            retrieval_indexing_profile_id=indexing_profile_id,
            generation_profile_id=uuid4(),
            answer_policy_version=_policy(configuration_id=configuration_id),
            workspace_ids=(uuid4(),),
        )


def test_generation_profile_is_required_for_generative_configuration() -> None:
    configuration_id = uuid4()
    indexing_profile_id = uuid4()
    policy = _policy(configuration_id=configuration_id, mode="generative")

    with pytest.raises(ConfigurationValidationError, match="requires a Generation"):
        SavedRagConfiguration.create(
            configuration_id=configuration_id,
            configuration_version_id=uuid4(),
            owner_id=uuid4(),
            name="생성 구성",
            version=1,
            indexing_profile_id=indexing_profile_id,
            retrieval_profile_id=uuid4(),
            retrieval_indexing_profile_id=indexing_profile_id,
            generation_profile_id=None,
            answer_policy_version=policy,
            workspace_ids=(uuid4(),),
        )

    generation_profile_id = uuid4()
    configuration = SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=uuid4(),
        name="생성 구성",
        version=1,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=generation_profile_id,
        answer_policy_version=policy,
        workspace_ids=(uuid4(),),
    )

    assert configuration.generation_profile_id == generation_profile_id
    assert configuration.answer_policy_version.mode == "generative"


def test_answer_policy_rejects_unknown_mode() -> None:
    with pytest.raises(ConfigurationValidationError, match="mode"):
        _policy(mode="agentic")


def test_answer_policy_and_configuration_versions_are_immutable() -> None:
    policy = _policy()
    configuration = _configuration()

    with pytest.raises(FrozenInstanceError):
        policy.min_semantic_score = 0.1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        configuration.version = 2  # type: ignore[misc]


def test_extractive_policy_is_versioned_and_fail_closed() -> None:
    with pytest.raises(ValueError, match="complete provenance"):
        AnswerPolicyVersion.create(
            configuration_id=uuid4(),
            version=1,
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=False,
            conflict_mode="separate_sources",
        )

    policy = _policy(version=3)

    assert policy.version == 3
    assert policy.mode == "extractive"
    assert policy.to_answer_policy().conflict_mode == "separate_sources"


def test_orm_metadata_pairs_the_exact_policy_version_for_task11_promotion() -> None:
    configuration_table = RagConfigurationVersionRecord.__table__
    check_names = {
        constraint.name
        for constraint in configuration_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_rag_configuration_versions_default_passed" in check_names
    assert "ck_rag_config_versions_no_passed_pre_eval" not in check_names
    assert "ck_rag_config_versions_no_default_pre_eval" not in check_names

    policy_table = AnswerPolicyVersionRecord.__table__
    policy_foreign_key = next(
        constraint
        for constraint in configuration_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and "answer_policy_version_id"
        in {element.parent.name for element in constraint.elements}
    )
    assert [element.parent.name for element in policy_foreign_key.elements] == [
        "configuration_id",
        "answer_policy_version_id",
        "version",
    ]
    assert [element.target_fullname for element in policy_foreign_key.elements] == [
        f"{policy_table.name}.configuration_id",
        f"{policy_table.name}.id",
        f"{policy_table.name}.version",
    ]


def test_default_promotion_requires_passed_and_applicable_versioned_policy() -> None:
    pending = _configuration()
    dataset_id = uuid4()
    policy = EvaluationPolicy.create(
        owner_id=pending.owner_id or uuid4(),
        dataset_snapshot_id=dataset_id,
        version=1,
        metric_definition_version=1,
        retrieval_k=10,
        recall_at_k=0.8,
        mrr=0.8,
        ndcg=0.8,
        supported_precision=0.8,
        max_false_grounding_rate=0.0,
        min_highlight_iou=0.8,
        max_p50_latency_ms=100,
        max_p95_latency_ms=200,
        max_access_leaks=0,
        required_reproducibility=1.0,
    )
    metrics = EvaluationMetrics(0.9, 0.9, 0.9, 1.0, 0.0, 0.9, 50, 100, 0, 1.0)
    evidence = PromotionEvidence(
        configuration_version_id=pending.version_id,
        evaluated_configuration_version_id=pending.version_id,
        metric_definition_version=1,
        retrieval_k=10,
        run_status=EvaluationRunStatus.COMPLETED,
        candidate_status=CandidateStatus.COMPLETED,
        failure=None,
        metrics=metrics,
    )

    with pytest.raises(ConfigurationValidationError, match="passing"):
        pending.as_default(policy=None, evidence=evidence)
    with pytest.raises(ConfigurationValidationError, match="passing"):
        pending.as_default(
            policy=policy,
            evidence=replace(
                evidence,
                metrics=EvaluationMetrics(
                    0.7, 0.9, 0.9, 1.0, 0.0, 0.9, 50, 100, 0, 1.0
                ),
            ),
        )

    promoted = pending.as_default(
        policy=policy,
        evidence=evidence,
    )

    assert promoted.is_default is True
    assert promoted.evaluation_state is EvaluationState.PASSED


def test_configuration_requires_a_nonempty_unique_workspace_subscription() -> None:
    configuration_id = uuid4()
    indexing_profile_id = uuid4()
    common = {
        "configuration_id": configuration_id,
        "configuration_version_id": uuid4(),
        "owner_id": uuid4(),
        "name": "구독 구성",
        "version": 1,
        "indexing_profile_id": indexing_profile_id,
        "retrieval_profile_id": uuid4(),
        "retrieval_indexing_profile_id": indexing_profile_id,
        "generation_profile_id": None,
        "answer_policy_version": _policy(configuration_id=configuration_id),
    }

    with pytest.raises(ConfigurationValidationError, match="workspace"):
        SavedRagConfiguration.create(**common, workspace_ids=())
    workspace_id = uuid4()
    with pytest.raises(ConfigurationValidationError, match="unique"):
        SavedRagConfiguration.create(
            **common,
            workspace_ids=(workspace_id, workspace_id),
        )


class MemoryConfigurationRepository:
    def __init__(
        self,
        *,
        profiles: tuple[Profile, ...],
        accessible_workspace_ids: tuple[UUID, ...],
        active_asset_version_ids: tuple[UUID, ...] = (),
        ready_indexing_profile_ids: frozenset[UUID] = frozenset(),
        deployments: tuple[ModelDeploymentVersion, ...] = (),
        models: tuple[ModelDefinition, ...] = (),
        installation_policy: InstallationDataPolicyVersion | None = None,
        workspace_policies: tuple[WorkspaceDataPolicyVersion, ...] = (),
        reject_approval: bool = False,
    ) -> None:
        self.profiles = {profile.id: profile for profile in profiles}
        self.accessible = accessible_workspace_ids
        self.active_assets = active_asset_version_ids
        self.ready_profiles = ready_indexing_profile_ids
        self.identities: dict[tuple[UUID, str], UUID] = {}
        self.saved: list[SavedRagConfiguration] = []
        self.events: list[str] = []
        self.deployments = {item.id: item for item in deployments}
        self.models = {item.id: item for item in models}
        self.installation_policy = installation_policy
        self.workspace_policies = workspace_policies
        self.approvals: list[ExternalConfigurationApproval] = []
        self.reject_approval = reject_approval
        self.external_execution_locks = 0

    async def find_profile(self, profile_id: UUID) -> Profile | None:
        return self.profiles.get(profile_id)

    async def authorized_workspace_ids(
        self, owner_id: UUID, workspace_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        del owner_id
        return tuple(item for item in workspace_ids if item in self.accessible)

    async def get_or_create_identity(self, owner_id: UUID, name: str) -> tuple[UUID, int]:
        key = (owner_id, name)
        configuration_id = self.identities.setdefault(key, uuid4())
        versions = [item.version for item in self.saved if item.id == configuration_id]
        return configuration_id, max(versions, default=0) + 1

    async def add(self, configuration: SavedRagConfiguration) -> SavedRagConfiguration:
        self.events.append("configuration")
        self.saved.append(configuration)
        return configuration

    async def get_deployment_version(
        self, deployment_version_id: UUID
    ) -> ModelDeploymentVersion | None:
        return self.deployments.get(deployment_version_id)

    async def get_model_definition(
        self, model_definition_id: UUID
    ) -> ModelDefinition | None:
        return self.models.get(model_definition_id)

    async def lock_external_execution_policy(self) -> None:
        self.external_execution_locks += 1

    async def latest_installation_policy(self) -> InstallationDataPolicyVersion:
        if self.installation_policy is None:
            raise RuntimeError("Synthetic Installation policy is not configured.")
        return self.installation_policy

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]:
        return tuple(
            policy
            for workspace_id in workspace_ids
            for policy in self.workspace_policies
            if policy.workspace_id == workspace_id
        )

    async def add_external_approval(
        self, approval: ExternalConfigurationApproval
    ) -> ExternalConfigurationApproval:
        if self.reject_approval:
            raise ValueError("synthetic stale approval")
        self.events.append("approval")
        self.approvals.append(approval)
        return approval

    async def get_external_approval_for_configuration(
        self, configuration_version_id: UUID
    ) -> ExternalConfigurationApproval | None:
        return next(
            (
                approval
                for approval in self.approvals
                if approval.configuration_version_id == configuration_version_id
            ),
            None,
        )

    async def active_asset_version_ids(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        del workspace_ids
        return self.active_assets

    async def list_visible(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        return [item for item in self.saved if item.owner_id in {None, actor_id}]

    async def ready_indexing_profile_ids(
        self, indexing_profile_ids: tuple[UUID, ...]
    ) -> frozenset[UUID]:
        return frozenset(self.ready_profiles.intersection(indexing_profile_ids))

    async def find_visible(
        self, configuration_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration | None:
        matches = [
            item
            for item in self.saved
            if item.id == configuration_id and item.owner_id in {None, actor_id}
        ]
        return max(matches, key=lambda item: item.version) if matches else None


class RecordingIngestionJobs:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.commands: list[EnsureIndexedCommand] = []
        self.job_ids: list[UUID] = []

    async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
        self.events.append("job")
        self.commands.append(command)
        job_id = uuid4()
        self.job_ids.append(job_id)
        return job_id


class GenerationReadiness:
    def __init__(self, ready_profile_ids: set[UUID]) -> None:
        self.ready_profile_ids = ready_profile_ids
        self.checked_profile_ids: list[UUID] = []

    async def is_ready(self, profile_id: UUID) -> bool:
        self.checked_profile_ids.append(profile_id)
        return profile_id in self.ready_profile_ids


@pytest.mark.asyncio
async def test_search_readiness_is_mapped_by_immutable_configuration_version() -> None:
    ready = _configuration()
    pending = _configuration()
    repository = MemoryConfigurationRepository(
        profiles=(),
        accessible_workspace_ids=(),
        ready_indexing_profile_ids=frozenset({ready.indexing_profile_id}),
    )
    service = RagConfigurationService(repository, RecordingIngestionJobs(repository.events))

    result = await service.search_readiness((ready, pending))

    assert result == {ready.version_id: True, pending.version_id: False}


@pytest.mark.asyncio
async def test_service_readiness_treats_ready_extractive_answer_as_ready() -> None:
    extractive = _configuration()
    model = ModelDefinition(
        id=uuid4(),
        kind=ModelKind.LLM,
        name="Local model",
        version=1,
        config={},
    )
    deployment = _deployment(
        location=ExecutionLocation.LOCAL,
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        model_definition_id=model.id,
    )
    generation = _generation_profile(deployment.id)
    configuration_id = uuid4()
    indexing_profile_id = uuid4()
    generative = SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=uuid4(),
        name="생성 구성",
        version=1,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=generation.id,
        answer_policy_version=_policy(
            configuration_id=configuration_id,
            mode="generative",
        ),
        workspace_ids=(uuid4(),),
    )
    repository = MemoryConfigurationRepository(
        profiles=(generation,),
        accessible_workspace_ids=(),
        ready_indexing_profile_ids=frozenset(
            {extractive.indexing_profile_id, generative.indexing_profile_id}
        ),
        deployments=(deployment,),
        models=(model,),
    )
    generation_readiness = GenerationReadiness({generation.id})
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        generation_readiness=generation_readiness,
    )

    readiness = await service.readiness((extractive, generative))

    assert readiness[extractive.version_id].search_ready is True
    assert readiness[extractive.version_id].answer_ready is True
    assert readiness[extractive.version_id].service_ready is True
    assert readiness[extractive.version_id].answer_reasons == ()
    assert readiness[extractive.version_id].generation_execution_preview is None
    assert readiness[generative.version_id].search_ready is True
    assert readiness[generative.version_id].answer_ready is True
    assert readiness[generative.version_id].service_ready is True
    assert readiness[generative.version_id].answer_reasons == ()
    assert generation_readiness.checked_profile_ids == [generation.id]


@pytest.mark.asyncio
async def test_readiness_builds_safe_preview_from_exact_generation_join() -> None:
    indexing, _retrieval = _technical_profiles()
    model = ModelDefinition(
        id=uuid4(),
        kind=ModelKind.LLM,
        name="Public model name",
        version=7,
        config={},
    )
    deployment = _deployment(
        location=ExecutionLocation.EXTERNAL,
        provider=ProviderKind.OPENAI_RESPONSES,
        model_definition_id=model.id,
    )
    generation = _generation_profile(deployment.id)
    configuration_id = uuid4()
    configuration = SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=uuid4(),
        name="External generation",
        version=1,
        indexing_profile_id=indexing.id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing.id,
        generation_profile_id=generation.id,
        answer_policy_version=_policy(
            configuration_id=configuration_id,
            mode="generative",
        ),
        workspace_ids=(uuid4(),),
    )
    repository = MemoryConfigurationRepository(
        profiles=(generation,),
        accessible_workspace_ids=(),
        ready_indexing_profile_ids=frozenset({indexing.id}),
        deployments=(deployment,),
        models=(model,),
    )

    result = await RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
    ).readiness((configuration,))

    assert result[configuration.version_id].answer_ready is False
    assert result[configuration.version_id].answer_reasons == ("deployment_not_ready",)
    preview = result[configuration.version_id].generation_execution_preview
    assert preview is not None
    assert preview.provider is ProviderKind.OPENAI_RESPONSES
    assert preview.model_name == "Public model name"
    assert preview.model_version == 7
    assert preview.deployment_name == "Synthetic generation deployment"
    assert preview.location is ExecutionLocation.EXTERNAL
    assert preview.external_transfer is True
    assert preview.disclosure == (
        "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 전송됩니다."
    )


def _technical_profiles() -> tuple[Profile, Profile]:
    indexing_profile_id = uuid4()
    indexing = Profile.create(
        kind=ProfileKind.INDEXING,
        name="e5-structure-aware",
        version=2,
        config={
            "chunker": {"name": "structure-aware"},
            "embedding": {"batch_size": 32, "similarity": "cosine"},
        },
        bindings=(ProfileModelBinding(ModelKind.EMBEDDING, uuid4()),),
    )
    indexing = Profile(
        id=indexing_profile_id,
        kind=indexing.kind,
        name=indexing.name,
        version=indexing.version,
        config=indexing.config,
        bindings=indexing.bindings,
        evaluation_state=indexing.evaluation_state,
        is_default=indexing.is_default,
    )
    retrieval = Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-baseline",
        version=1,
        config={
            "bm25": {"analyzer": "standard", "top_k": 30},
            "indexing_profile_id": str(indexing_profile_id),
        },
        bindings=(),
    )
    return indexing, retrieval


def _generation_profile(deployment_version_id: UUID) -> Profile:
    return Profile.create(
        kind=ProfileKind.GENERATION,
        name="local-grounded-generation",
        version=1,
        config={
            "prompt_ref": "rag-answer-v1",
            "context_prompt_ref": "rag-contextualize-v1",
            "citation_mode": "required",
            "context_policy": {"max_history_turns": 6, "max_history_tokens": 1024},
            "generation": {
                "timeout_seconds": 30,
                "max_output_tokens": 512,
                "temperature": 0.1,
                "response_schema_version": 1,
            },
        },
        bindings=(),
        deployment_version_id=deployment_version_id,
    )


def _deployment(
    *,
    location: ExecutionLocation,
    provider: ProviderKind,
    model_definition_id: UUID | None = None,
    development_only: bool = False,
) -> ModelDeploymentVersion:
    external = location is ExecutionLocation.EXTERNAL
    return ModelDeploymentVersion.create(
        deployment_id=uuid4(),
        version=1,
        display_name="Synthetic generation deployment",
        description="Synthetic",
        model_definition_id=model_definition_id or uuid4(),
        provider=provider,
        location=location,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="exact-provider-model",
        endpoint_ref="synthetic-endpoint",
        secret_ref="synthetic-secret" if external else None,
        capabilities=(DeploymentCapability.STRUCTURED_OUTPUT,),
        external_transfer=external,
        transmitted_data_categories=("question", "evidence") if external else (),
        data_processing_notice_ref="public-notice-v1" if external else None,
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0.5,
        healthcheck_enabled=True,
        development_only=development_only,
        created_by=uuid4(),
    )


def _installation_policy(
    *, mode: OutboundMode = OutboundMode.APPROVED_PROVIDERS
) -> InstallationDataPolicyVersion:
    return InstallationDataPolicyVersion.create(
        policy_id=uuid4(),
        version=2,
        mode=mode,
        approved_providers=(
            (ProviderKind.OPENAI_RESPONSES,)
            if mode is OutboundMode.APPROVED_PROVIDERS
            else ()
        ),
        changed_by=uuid4(),
    )


def _workspace_policy(workspace_id: UUID) -> WorkspaceDataPolicyVersion:
    return WorkspaceDataPolicyVersion.create(
        policy_id=uuid4(),
        workspace_id=workspace_id,
        version=3,
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        approved_providers=(ProviderKind.OPENAI_RESPONSES,),
        changed_by=uuid4(),
    )


def _approval() -> ExternalTransferApprovalConfirmation:
    return ExternalTransferApprovalConfirmation(
        confirmed=True,
        disclosure_version="external-generation-v1",
    )


async def _saved_external_configuration_for_readiness() -> tuple[
    SavedRagConfiguration,
    MemoryConfigurationRepository,
    RagConfigurationService,
    GenerationReadiness,
]:
    indexing, retrieval = _technical_profiles()
    model = ModelDefinition(
        id=uuid4(),
        kind=ModelKind.LLM,
        name="External model",
        version=1,
        config={},
    )
    deployment = _deployment(
        location=ExecutionLocation.EXTERNAL,
        provider=ProviderKind.OPENAI_RESPONSES,
        model_definition_id=model.id,
    )
    generation = _generation_profile(deployment.id)
    workspace_id = uuid4()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        ready_indexing_profile_ids=frozenset({indexing.id}),
        deployments=(deployment,),
        models=(model,),
        installation_policy=_installation_policy(),
        workspace_policies=(_workspace_policy(workspace_id),),
    )
    generation_readiness = GenerationReadiness({generation.id})
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        generation_readiness=generation_readiness,
    )
    result = await service.create(
        owner_id=uuid4(),
        name="External ready configuration",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=generation.id,
        answer_mode="generative",
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=(workspace_id,),
        external_transfer_approval=_approval(),
    )
    return result.configuration, repository, service, generation_readiness


@pytest.mark.asyncio
async def test_external_readiness_requires_exact_current_saved_approval() -> None:
    configuration, _repository, service, generation_readiness = (
        await _saved_external_configuration_for_readiness()
    )

    readiness = (await service.readiness((configuration,)))[configuration.version_id]

    assert readiness.answer_ready is True
    assert readiness.service_ready is True
    assert readiness.answer_reasons == ()
    assert generation_readiness.checked_profile_ids == [configuration.generation_profile_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy_change", "expected_reason"),
    [
        ("stale", "deployment_not_ready"),
        ("deny", "provider_not_allowed"),
        ("workspace_deny", "workspace_external_transfer_denied"),
    ],
)
async def test_external_readiness_fails_closed_for_stale_or_denied_policy(
    policy_change: str,
    expected_reason: str,
) -> None:
    configuration, repository, service, _generation_readiness = (
        await _saved_external_configuration_for_readiness()
    )
    repository.installation_policy = _installation_policy(
        mode=(OutboundMode.DENY if policy_change == "deny" else OutboundMode.APPROVED_PROVIDERS)
    )
    if policy_change == "workspace_deny":
        workspace_id = configuration.workspace_ids[0]
        repository.workspace_policies = (
            WorkspaceDataPolicyVersion.create(
                policy_id=uuid4(),
                workspace_id=workspace_id,
                version=4,
                mode=WorkspaceOutboundMode.DENY,
                approved_providers=(),
                changed_by=uuid4(),
            ),
        )

    readiness = (await service.readiness((configuration,)))[configuration.version_id]

    assert readiness.answer_ready is False
    assert readiness.service_ready is False
    assert readiness.answer_reasons == (expected_reason,)


@pytest.mark.asyncio
async def test_service_saves_generative_configuration_with_exact_profile() -> None:
    indexing, retrieval = _technical_profiles()
    deployment = _deployment(
        location=ExecutionLocation.LOCAL,
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
    )
    generation = _generation_profile(deployment.id)
    workspace_id = uuid4()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        deployments=(deployment,),
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )

    result = await service.create(
        owner_id=uuid4(),
        name="대화형 생성 구성",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=generation.id,
        answer_mode="generative",
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=(workspace_id,),
    )

    assert result.configuration.generation_profile_id == generation.id
    assert result.configuration.answer_policy_version.mode == "generative"


@pytest.mark.asyncio
async def test_external_generation_requires_owner_confirmation_before_save() -> None:
    indexing, retrieval = _technical_profiles()
    deployment = _deployment(
        location=ExecutionLocation.EXTERNAL,
        provider=ProviderKind.OPENAI_RESPONSES,
    )
    generation = _generation_profile(deployment.id)
    workspace_id = uuid4()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        deployments=(deployment,),
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )

    with pytest.raises(AppError) as caught:
        await service.create(
            owner_id=uuid4(),
            name="외부 생성 구성",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=retrieval.id,
            generation_profile_id=generation.id,
            answer_mode="generative",
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
        )

    assert caught.value.code == "external_transfer_approval_required"
    assert repository.saved == []
    assert repository.approvals == []
    assert repository.events == []


@pytest.mark.asyncio
async def test_external_generation_persists_exact_current_policy_snapshot() -> None:
    indexing, retrieval = _technical_profiles()
    workspace_ids = (uuid4(), uuid4())
    deployment = _deployment(
        location=ExecutionLocation.EXTERNAL,
        provider=ProviderKind.OPENAI_RESPONSES,
    )
    generation = _generation_profile(deployment.id)
    installation = _installation_policy()
    workspace_policies = tuple(_workspace_policy(item) for item in workspace_ids)
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=workspace_ids,
        deployments=(deployment,),
        installation_policy=installation,
        workspace_policies=workspace_policies,
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )
    owner_id = uuid4()

    result = await service.create(
        owner_id=owner_id,
        name="외부 생성 구성",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=generation.id,
        answer_mode="generative",
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=workspace_ids,
        external_transfer_approval=_approval(),
    )

    approval = repository.approvals[0]
    assert approval.configuration_version_id == result.configuration.version_id
    assert approval.deployment_version_id == deployment.id
    assert approval.installation_policy_version_id == installation.id
    assert approval.approved_by == owner_id
    assert approval.disclosure_version == "external-generation-v1"
    assert approval.workspace_policies == tuple(
        (ApprovedWorkspacePolicySnapshot(policy.workspace_id, policy.id))
        for policy in workspace_policies
    )
    assert repository.external_execution_locks == 1
    assert repository.events == ["configuration", "approval", "commit"]


@pytest.mark.asyncio
async def test_external_generation_rejects_denied_or_stale_policy_before_commit() -> None:
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    deployment = _deployment(
        location=ExecutionLocation.EXTERNAL,
        provider=ProviderKind.OPENAI_RESPONSES,
    )
    generation = _generation_profile(deployment.id)

    for repository, expected_code in (
        (
            MemoryConfigurationRepository(
                profiles=(indexing, retrieval, generation),
                accessible_workspace_ids=(workspace_id,),
                deployments=(deployment,),
                installation_policy=_installation_policy(),
                workspace_policies=(),
            ),
            "workspace_external_transfer_denied",
        ),
        (
            MemoryConfigurationRepository(
            profiles=(indexing, retrieval, generation),
            accessible_workspace_ids=(workspace_id,),
            deployments=(deployment,),
            installation_policy=_installation_policy(mode=OutboundMode.DENY),
            workspace_policies=(_workspace_policy(workspace_id),),
            ),
            "provider_not_allowed",
        ),
        (
            MemoryConfigurationRepository(
                profiles=(indexing, retrieval, generation),
                accessible_workspace_ids=(workspace_id,),
                deployments=(deployment,),
                installation_policy=_installation_policy(),
                workspace_policies=(_workspace_policy(workspace_id),),
                reject_approval=True,
            ),
            "external_approval_stale",
        ),
    ):
        service = RagConfigurationService(
            repository,
            RecordingIngestionJobs(repository.events),
            commit=_commit(repository.events),
        )
        with pytest.raises(AppError) as caught:
            await service.create(
                owner_id=uuid4(),
                name="거절 구성",
                indexing_profile_id=indexing.id,
                retrieval_profile_id=retrieval.id,
                generation_profile_id=generation.id,
                answer_mode="generative",
                min_semantic_score=0.8,
                min_keyword_coverage=0.7,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(workspace_id,),
                external_transfer_approval=_approval(),
            )
        assert caught.value.code == expected_code
        assert "commit" not in repository.events


@pytest.mark.asyncio
async def test_local_generation_rejects_external_approval_payload() -> None:
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    deployment = _deployment(
        location=ExecutionLocation.LOCAL,
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
    )
    generation = _generation_profile(deployment.id)
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        deployments=(deployment,),
    )

    with pytest.raises(AppError) as caught:
        await RagConfigurationService(
            repository,
            RecordingIngestionJobs(repository.events),
        ).create(
            owner_id=uuid4(),
            name="로컬 구성",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=retrieval.id,
            generation_profile_id=generation.id,
            answer_mode="generative",
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
            external_transfer_approval=_approval(),
        )

    assert caught.value.code == "external_transfer_approval_not_allowed"
    assert repository.saved == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "provider"),
    [
        (ExecutionLocation.LOCAL, ProviderKind.LOCAL_OPENAI_COMPATIBLE),
        (ExecutionLocation.EXTERNAL, ProviderKind.OPENAI_RESPONSES),
    ],
)
async def test_development_only_deployment_is_rejected_in_production(
    location: ExecutionLocation,
    provider: ProviderKind,
) -> None:
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    deployment = _deployment(
        location=location,
        provider=provider,
        development_only=True,
    )
    # Simulate contradictory metadata already persisted before the domain hardening.
    object.__setattr__(
        deployment,
        "allowed_environments",
        (DeploymentEnvironment.PRODUCTION,),
    )
    generation = _generation_profile(deployment.id)
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        deployments=(deployment,),
        installation_policy=_installation_policy(),
        workspace_policies=(_workspace_policy(workspace_id),),
    )

    with pytest.raises(AppError) as caught:
        await RagConfigurationService(
            repository,
            RecordingIngestionJobs(repository.events),
            environment="production",
        ).create(
            owner_id=uuid4(),
            name="production forbidden development Deployment",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=retrieval.id,
            generation_profile_id=generation.id,
            answer_mode="generative",
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
            external_transfer_approval=(
                _approval() if location is ExecutionLocation.EXTERNAL else None
            ),
        )

    assert caught.value.code == "deployment_not_allowed_in_environment"
    assert repository.saved == []
    assert repository.approvals == []


def _retrieval_with_reranker(
    *,
    reranker: dict[str, object],
    with_binding: bool,
) -> Profile:
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="hybrid-disabled-v1",
        version=1,
        config={
            "bm25": {"analyzer": "standard", "top_k": 30},
            "dense": {"top_k": 30},
            "rrf": {"k": 60},
            "indexing_profile_id": str(uuid4()),
            "reranker": reranker,
        },
        bindings=(
            (ProfileModelBinding(ModelKind.RERANKER, uuid4()),)
            if with_binding
            else ()
        ),
    )


def test_v1_retrieval_accepts_only_non_executable_disabled_reranker_metadata() -> None:
    disabled = _retrieval_with_reranker(
        reranker={"enabled": False},
        with_binding=False,
    )

    validate_v1_retrieval_profile(disabled)

    enabled = _retrieval_with_reranker(
        reranker={"enabled": True},
        with_binding=False,
    )
    with pytest.raises(ConfigurationValidationError, match="reranker"):
        validate_v1_retrieval_profile(enabled)

    selected = _retrieval_with_reranker(
        reranker={"enabled": False, "model_id": str(uuid4())},
        with_binding=False,
    )
    with pytest.raises(ConfigurationValidationError, match="reranker"):
        validate_v1_retrieval_profile(selected)

    bound = _retrieval_with_reranker(
        reranker={"enabled": False},
        with_binding=True,
    )
    with pytest.raises(ConfigurationValidationError, match="binding"):
        validate_v1_retrieval_profile(bound)


def _commit(events: list[str]) -> Callable[[], Awaitable[None]]:
    async def commit() -> None:
        events.append("commit")

    return commit


@pytest.mark.asyncio
async def test_saving_same_owner_name_creates_immutable_next_version_and_jobs() -> None:
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    asset_ids = (uuid4(), uuid4())
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval),
        accessible_workspace_ids=(workspace_id,),
        active_asset_version_ids=asset_ids,
    )
    jobs = RecordingIngestionJobs(repository.events)
    service = RagConfigurationService(repository, jobs, commit=_commit(repository.events))
    owner_id = uuid4()

    first = await service.create(
        owner_id=owner_id,
        name="내 구성",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=None,
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=(workspace_id,),
    )
    second = await service.create(
        owner_id=owner_id,
        name="내 구성",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=None,
        min_semantic_score=0.85,
        min_keyword_coverage=0.75,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=(workspace_id,),
    )

    assert first.configuration.id == second.configuration.id
    assert first.configuration.version == 1
    assert second.configuration.version == 2
    assert first.configuration.version_id != second.configuration.version_id
    assert first.configuration.answer_policy_version_id != (
        second.configuration.answer_policy_version_id
    )
    assert first.configuration.is_default is second.configuration.is_default is False
    assert [command.asset_version_id for command in jobs.commands] == [*asset_ids, *asset_ids]
    assert all(command.indexing_profile_id == indexing.id for command in jobs.commands)
    assert all(command.requested_by == owner_id for command in jobs.commands)
    assert repository.events == [
        "configuration",
        "job",
        "job",
        "commit",
        "configuration",
        "job",
        "job",
        "commit",
    ]


@pytest.mark.asyncio
async def test_unauthorized_workspace_fails_before_identity_or_enqueue() -> None:
    indexing, retrieval = _technical_profiles()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval),
        accessible_workspace_ids=(),
        active_asset_version_ids=(uuid4(),),
    )
    jobs = RecordingIngestionJobs(repository.events)
    service = RagConfigurationService(repository, jobs, commit=_commit(repository.events))

    with pytest.raises(AppError) as caught:
        await service.create(
            owner_id=uuid4(),
            name="권한 없음",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=retrieval.id,
            generation_profile_id=None,
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(uuid4(),),
        )

    assert caught.value.status_code == 404
    assert repository.identities == {}
    assert jobs.commands == []
    assert repository.events == []


@pytest.mark.asyncio
async def test_user_cannot_create_a_version_of_the_system_baseline() -> None:
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval),
        accessible_workspace_ids=(workspace_id,),
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )

    with pytest.raises(AppError) as caught:
        await service.create(
            owner_id=uuid4(),
            name=" BM25 기준선 ",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=retrieval.id,
            generation_profile_id=None,
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
        )

    assert caught.value.code == "system_configuration_reserved"
    assert repository.identities == {}
    assert repository.events == []


@pytest.mark.asyncio
async def test_incompatible_or_generation_profile_is_rejected_before_save() -> None:
    indexing, retrieval = _technical_profiles()
    wrong_retrieval = Profile(
        id=retrieval.id,
        kind=retrieval.kind,
        name=retrieval.name,
        version=retrieval.version,
        config={
            "bm25": {"top_k": 30},
            "indexing_profile_id": str(uuid4()),
        },
        bindings=retrieval.bindings,
        evaluation_state=retrieval.evaluation_state,
        is_default=False,
    )
    workspace_id = uuid4()
    repository = MemoryConfigurationRepository(
        profiles=(indexing, wrong_retrieval),
        accessible_workspace_ids=(workspace_id,),
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )

    with pytest.raises(AppError) as incompatible:
        await service.create(
            owner_id=uuid4(),
            name="불일치",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=wrong_retrieval.id,
            generation_profile_id=None,
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
        )
    assert incompatible.value.code == "incompatible_profiles"

    with pytest.raises(AppError) as generation:
        await service.create(
            owner_id=uuid4(),
            name="생성 사용",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=wrong_retrieval.id,
            generation_profile_id=uuid4(),
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
        )
    assert generation.value.code == "generation_not_supported"


@pytest.mark.asyncio
async def test_enabled_or_bound_reranker_is_rejected_before_save() -> None:
    indexing, _ = _technical_profiles()
    workspace_id = uuid4()
    enabled = Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="enabled-reranker",
        version=1,
        config={
            "bm25": {"top_k": 30},
            "indexing_profile_id": str(indexing.id),
            "reranker": {"enabled": True},
        },
        bindings=(),
    )
    repository = MemoryConfigurationRepository(
        profiles=(indexing, enabled),
        accessible_workspace_ids=(workspace_id,),
    )
    service = RagConfigurationService(
        repository,
        RecordingIngestionJobs(repository.events),
        commit=_commit(repository.events),
    )

    with pytest.raises(AppError) as caught:
        await service.create(
            owner_id=uuid4(),
            name="reranker 사용",
            indexing_profile_id=indexing.id,
            retrieval_profile_id=enabled.id,
            generation_profile_id=None,
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
            workspace_ids=(workspace_id,),
        )

    assert caught.value.code == "reranker_not_supported"
    assert repository.identities == {}
    assert repository.events == []
