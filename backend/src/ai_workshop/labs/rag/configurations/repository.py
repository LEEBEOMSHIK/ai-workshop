from collections.abc import Callable, Mapping
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
    RagSystemIndexingSubscriptionRecord,
)
from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion
from ai_workshop.labs.rag.deployments.repository import SqlAlchemyDeploymentRepository
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingPort,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
    PromotionEvidence,
)
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationPolicyRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.generation.domain import GenerationProfile
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    JsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    freeze_json,
)
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileDeploymentBindingRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    WorkspaceDataPolicyVersion,
)
from ai_workshop.labs.rag.policies.repository import (
    ExternalConfigurationApproval,
    SqlAlchemyDataPolicyRepository,
)
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    FrozenIndexTarget,
    SearchIndexTarget,
)
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedExternalApproval,
    ResolvedSearchConfiguration,
    ResolvedWorkspacePolicyApproval,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.repository import workspace_is_active
from ai_workshop.shared.errors import AppError


def _profile_to_domain(
    record: ProfileRecord,
    deployment_version_id: UUID | None = None,
) -> Profile:
    config = cast(dict[str, JsonValue], record.config)
    frozen = freeze_json(config)
    if not isinstance(frozen, Mapping):
        raise TypeError("Stored profile configuration must be a mapping.")
    return Profile(
        id=record.id,
        kind=ProfileKind(record.kind),
        name=record.name,
        version=record.version,
        config=frozen,
        bindings=tuple(
            ProfileModelBinding(ModelKind(item.role), item.model_id)
            for item in record.bindings
        ),
        evaluation_state=EvaluationState(record.evaluation_state),
        is_default=record.is_default,
        deployment_version_id=deployment_version_id,
    )


def _model_to_domain(record: ModelDefinitionRecord) -> ModelDefinition:
    config = cast(dict[str, JsonValue], record.config)
    frozen = freeze_json(config)
    if not isinstance(frozen, Mapping):
        raise TypeError("Stored model configuration must be a mapping.")
    return ModelDefinition(
        id=record.id,
        kind=ModelKind(record.kind),
        name=record.name,
        version=record.version,
        config=frozen,
    )


class SqlAlchemyRagConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_profile(self, profile_id: UUID) -> Profile | None:
        record = await self.session.get(ProfileRecord, profile_id)
        if record is None:
            return None
        deployment_version_id = await self.session.scalar(
            select(ProfileDeploymentBindingRecord.deployment_version_id).where(
                ProfileDeploymentBindingRecord.profile_id == profile_id
            )
        )
        return _profile_to_domain(record, deployment_version_id)

    async def get_deployment_version(
        self, deployment_version_id: UUID
    ) -> ModelDeploymentVersion | None:
        return await SqlAlchemyDeploymentRepository(self.session).get_version(
            deployment_version_id
        )

    async def get_model_definition(
        self, model_definition_id: UUID
    ) -> ModelDefinition | None:
        record = await self.session.get(ModelDefinitionRecord, model_definition_id)
        return _model_to_domain(record) if record is not None else None

    async def lock_external_execution_policy(self) -> None:
        await SqlAlchemyDataPolicyRepository(
            self.session
        ).lock_external_execution_policy()

    async def latest_installation_policy(self) -> InstallationDataPolicyVersion:
        return await SqlAlchemyDataPolicyRepository(
            self.session
        ).latest_installation_policy()

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]:
        return await SqlAlchemyDataPolicyRepository(
            self.session
        ).latest_workspace_policies(workspace_ids)

    async def add_external_approval(
        self, approval: ExternalConfigurationApproval
    ) -> ExternalConfigurationApproval:
        return await SqlAlchemyDataPolicyRepository(
            self.session
        ).add_external_approval(approval)

    async def get_external_approval_for_configuration(
        self, configuration_version_id: UUID
    ) -> ExternalConfigurationApproval | None:
        return await SqlAlchemyDataPolicyRepository(
            self.session
        ).get_external_approval_for_configuration(configuration_version_id)

    async def authorized_workspace_ids(
        self,
        owner_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if not workspace_ids:
            return ()
        rows = set(
            await self.session.scalars(
                select(WorkspaceRecord.id)
                .join(
                    WorkspaceMembershipRecord,
                    and_(
                        WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                        WorkspaceMembershipRecord.user_id == owner_id,
                    ),
                )
                .where(
                    WorkspaceRecord.id.in_(workspace_ids),
                    workspace_is_active(),
                    or_(
                        WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                        WorkspaceRecord.created_by == owner_id,
                    ),
                )
            )
        )
        return tuple(item for item in workspace_ids if item in rows)

    async def all_authorized_workspace_ids(self, actor_id: UUID) -> tuple[UUID, ...]:
        result = await self.session.scalars(
            select(WorkspaceRecord.id)
            .join(
                WorkspaceMembershipRecord,
                and_(
                    WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                    WorkspaceMembershipRecord.user_id == actor_id,
                ),
            )
            .where(
                workspace_is_active(),
                or_(
                    WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                    WorkspaceRecord.created_by == actor_id,
                ),
            )
            .order_by(WorkspaceRecord.id)
        )
        return tuple(result)

    async def get_or_create_identity(
        self,
        owner_id: UUID,
        name: str,
    ) -> tuple[UUID, int]:
        record = await self.session.scalar(
            select(RagConfigurationRecord)
            .where(
                RagConfigurationRecord.owner_id == owner_id,
                RagConfigurationRecord.name == name,
                RagConfigurationRecord.is_system.is_(False),
            )
            .with_for_update()
        )
        if record is None:
            record = RagConfigurationRecord(
                owner_id=owner_id,
                name=name,
                is_system=False,
            )
            self.session.add(record)
            await self.session.flush()
            return record.id, 1
        latest = await self.session.scalar(
            select(RagConfigurationVersionRecord.version)
            .where(RagConfigurationVersionRecord.configuration_id == record.id)
            .order_by(RagConfigurationVersionRecord.version.desc())
            .limit(1)
        )
        return record.id, (latest or 0) + 1

    async def add(
        self,
        configuration: SavedRagConfiguration,
    ) -> SavedRagConfiguration:
        policy = configuration.answer_policy_version
        self.session.add(
            AnswerPolicyVersionRecord(
                id=policy.id,
                configuration_id=policy.configuration_id,
                version=policy.version,
                mode=policy.mode,
                min_semantic_score=policy.min_semantic_score,
                min_keyword_coverage=policy.min_keyword_coverage,
                require_complete_provenance=policy.require_complete_provenance,
                conflict_mode=policy.conflict_mode,
            )
        )
        await self.session.flush()
        self.session.add(
            RagConfigurationVersionRecord(
                id=configuration.version_id,
                configuration_id=configuration.id,
                version=configuration.version,
                indexing_profile_id=configuration.indexing_profile_id,
                retrieval_profile_id=configuration.retrieval_profile_id,
                generation_profile_id=configuration.generation_profile_id,
                answer_policy_version_id=configuration.answer_policy_version_id,
                evaluation_state=configuration.evaluation_state,
                is_default=configuration.is_default,
            )
        )
        await self.session.flush()
        self.session.add_all(
            [
                RagConfigurationWorkspaceSubscriptionRecord(
                    configuration_version_id=configuration.version_id,
                    workspace_id=workspace_id,
                )
                for workspace_id in configuration.workspace_ids
            ]
        )
        await self.session.flush()
        return configuration

    async def active_asset_version_ids(
        self,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if not workspace_ids:
            return ()
        result = await self.session.scalars(
            select(AssetVersionRecord.id)
            .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
            .where(
                DocumentRecord.workspace_id.in_(workspace_ids),
                DocumentRecord.active_version_id == AssetVersionRecord.id,
                AssetVersionRecord.status == VersionStatus.READY,
            )
            .order_by(AssetVersionRecord.id)
        )
        return tuple(result)

    async def list_visible(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        records = list(
            await self.session.scalars(
                select(RagConfigurationRecord)
                .where(
                    or_(
                        RagConfigurationRecord.is_system.is_(True),
                        RagConfigurationRecord.owner_id == actor_id,
                    )
                )
                .order_by(
                    RagConfigurationRecord.is_system.desc(),
                    RagConfigurationRecord.name,
                    RagConfigurationRecord.id,
                )
            )
        )
        return [await self._latest(record) for record in records]

    async def ready_indexing_profile_ids(
        self,
        indexing_profile_ids: tuple[UUID, ...],
    ) -> frozenset[UUID]:
        if not indexing_profile_ids:
            return frozenset()
        rows = (
            await self.session.execute(
                select(
                    RagIndexBuildRecord.indexing_profile_id,
                    RagIndexBuildRecord.vector_dimension,
                )
                .where(
                    RagIndexBuildRecord.indexing_profile_id.in_(indexing_profile_ids),
                    RagIndexBuildRecord.status == "ready",
                    RagIndexBuildRecord.is_active.is_(True),
                )
                .order_by(RagIndexBuildRecord.indexing_profile_id, RagIndexBuildRecord.id)
            )
        ).all()
        dimensions_by_profile: dict[UUID, set[int | None]] = {}
        for profile_id, dimension in rows:
            dimensions_by_profile.setdefault(profile_id, set()).add(dimension)
        return frozenset(
            profile_id
            for profile_id, dimensions in dimensions_by_profile.items()
            if None not in dimensions and len(dimensions) == 1
        )

    async def find_visible(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None:
        record = await self.session.scalar(
            select(RagConfigurationRecord).where(
                RagConfigurationRecord.id == configuration_id,
                or_(
                    RagConfigurationRecord.is_system.is_(True),
                    RagConfigurationRecord.owner_id == actor_id,
                ),
            )
        )
        return await self._latest(record) if record is not None else None

    async def find_version_visible(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None:
        row = (
            await self.session.execute(
                select(RagConfigurationRecord, RagConfigurationVersionRecord)
                .join(
                    RagConfigurationVersionRecord,
                    RagConfigurationVersionRecord.configuration_id
                    == RagConfigurationRecord.id,
                )
                .where(
                    RagConfigurationVersionRecord.id == configuration_version_id,
                    or_(
                        RagConfigurationRecord.is_system.is_(True),
                        RagConfigurationRecord.owner_id == actor_id,
                    ),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return await self._from_version(row[0], row[1])

    async def promote_default(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration:
        identity = await self.session.scalar(
            select(RagConfigurationRecord)
            .where(
                RagConfigurationRecord.id == configuration_id,
                or_(
                    RagConfigurationRecord.is_system.is_(True),
                    RagConfigurationRecord.owner_id == actor_id,
                ),
            )
            .with_for_update()
        )
        if identity is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        version = await self.session.scalar(
            select(RagConfigurationVersionRecord)
            .where(RagConfigurationVersionRecord.configuration_id == identity.id)
            .order_by(RagConfigurationVersionRecord.version.desc())
            .limit(1)
            .with_for_update()
        )
        if version is None:
            raise RuntimeError("A Saved RAG Configuration identity has no version.")
        evidence_rows = (
            await self.session.execute(
                select(
                    EvaluationRunConfigurationRecord,
                    EvaluationRunRecord,
                    EvaluationPolicyRecord,
                )
                .join(
                    EvaluationRunRecord,
                    EvaluationRunRecord.id
                    == EvaluationRunConfigurationRecord.run_id,
                )
                .join(
                    EvaluationPolicyRecord,
                    EvaluationPolicyRecord.id
                    == EvaluationRunRecord.evaluation_policy_version_id,
                )
                .where(
                    EvaluationRunConfigurationRecord.configuration_version_id
                    == version.id,
                    EvaluationRunRecord.owner_id == actor_id,
                    EvaluationPolicyRecord.owner_id == actor_id,
                    EvaluationPolicyRecord.dataset_snapshot_id
                    == EvaluationRunRecord.dataset_snapshot_id,
                )
                .order_by(EvaluationRunRecord.finished_at.desc().nullslast())
            )
        ).all()
        current = await self._from_version(identity, version)
        promoted: SavedRagConfiguration | None = None
        for candidate, run, policy_record in evidence_rows:
            metric_values = (
                candidate.recall_at_k,
                candidate.mrr,
                candidate.ndcg,
                candidate.supported_precision,
                candidate.false_grounding_rate,
                candidate.highlight_iou,
                candidate.p50_latency_ms,
                candidate.p95_latency_ms,
                candidate.access_leaks,
                candidate.reproducibility,
            )
            metrics = None
            if all(value is not None for value in metric_values):
                metrics = EvaluationMetrics(
                    recall_at_k=cast(float, candidate.recall_at_k),
                    mrr=cast(float, candidate.mrr),
                    ndcg=cast(float, candidate.ndcg),
                    supported_precision=cast(float, candidate.supported_precision),
                    false_grounding_rate=cast(float, candidate.false_grounding_rate),
                    highlight_iou=cast(float, candidate.highlight_iou),
                    p50_latency_ms=cast(float, candidate.p50_latency_ms),
                    p95_latency_ms=cast(float, candidate.p95_latency_ms),
                    access_leaks=cast(int, candidate.access_leaks),
                    reproducibility=cast(float, candidate.reproducibility),
                )
            policy = EvaluationPolicy(
                id=policy_record.id,
                owner_id=policy_record.owner_id,
                dataset_snapshot_id=policy_record.dataset_snapshot_id,
                version=policy_record.version,
                metric_definition_version=policy_record.metric_definition_version,
                retrieval_k=policy_record.retrieval_k,
                recall_at_k=policy_record.min_recall_at_k,
                mrr=policy_record.min_mrr,
                ndcg=policy_record.min_ndcg,
                supported_precision=policy_record.min_supported_precision,
                max_false_grounding_rate=policy_record.max_false_grounding_rate,
                min_highlight_iou=policy_record.min_highlight_iou,
                max_p50_latency_ms=policy_record.max_p50_latency_ms,
                max_p95_latency_ms=policy_record.max_p95_latency_ms,
                max_access_leaks=policy_record.max_access_leaks,
                required_reproducibility=policy_record.required_reproducibility,
            ).validate()
            evidence = PromotionEvidence(
                configuration_version_id=version.id,
                evaluated_configuration_version_id=candidate.configuration_version_id,
                metric_definition_version=run.metric_definition_version,
                retrieval_k=run.retrieval_k,
                run_status=EvaluationRunStatus(run.status),
                candidate_status=CandidateStatus(candidate.status),
                failure=candidate.failure,
                metrics=metrics,
            )
            try:
                promoted = current.as_default(policy=policy, evidence=evidence)
            except ValueError:
                continue
            break
        if promoted is None:
            raise AppError(
                "evaluation_policy_required",
                "An exact versioned Evaluation Policy and passing result are required.",
                409,
            )
        await self.session.execute(
            update(RagConfigurationVersionRecord)
            .where(
                RagConfigurationVersionRecord.is_default.is_(True),
                RagConfigurationVersionRecord.id != version.id,
            )
            .values(is_default=False)
        )
        version.evaluation_state = EvaluationState.PASSED
        version.is_default = True
        await self.session.flush()
        return promoted

    async def _latest(
        self,
        identity: RagConfigurationRecord,
    ) -> SavedRagConfiguration:
        version = await self.session.scalar(
            select(RagConfigurationVersionRecord)
            .where(RagConfigurationVersionRecord.configuration_id == identity.id)
            .order_by(RagConfigurationVersionRecord.version.desc())
            .limit(1)
        )
        if version is None:
            raise RuntimeError("A Saved RAG Configuration identity has no version.")
        return await self._from_version(identity, version)

    async def _from_version(
        self,
        identity: RagConfigurationRecord,
        version: RagConfigurationVersionRecord,
    ) -> SavedRagConfiguration:
        policy = await self.session.get(
            AnswerPolicyVersionRecord,
            version.answer_policy_version_id,
        )
        if policy is None or policy.configuration_id != identity.id:
            raise RuntimeError("A Saved RAG Configuration has no immutable Answer Policy.")
        if (
            policy.mode not in {"extractive", "generative"}
            or policy.require_complete_provenance is not True
            or policy.conflict_mode != "separate_sources"
        ):
            raise RuntimeError("A Saved RAG Configuration has an invalid Answer Policy.")
        workspace_ids = tuple(
            await self.session.scalars(
                select(RagConfigurationWorkspaceSubscriptionRecord.workspace_id)
                .where(
                    RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id
                    == version.id
                )
                .order_by(RagConfigurationWorkspaceSubscriptionRecord.workspace_id)
            )
        )
        answer_policy = AnswerPolicyVersion(
            id=policy.id,
            configuration_id=policy.configuration_id,
            version=policy.version,
            mode=cast(Literal["extractive", "generative"], policy.mode),
            min_semantic_score=policy.min_semantic_score,
            min_keyword_coverage=policy.min_keyword_coverage,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
        )
        retrieval = await self.find_profile(version.retrieval_profile_id)
        if retrieval is None:
            raise RuntimeError("A Saved RAG Configuration retrieval profile is missing.")
        retrieval_indexing_id = _retrieval_indexing_profile_id(retrieval)
        return SavedRagConfiguration.create(
            configuration_id=identity.id,
            configuration_version_id=version.id,
            owner_id=identity.owner_id,
            name=identity.name,
            version=version.version,
            indexing_profile_id=version.indexing_profile_id,
            retrieval_profile_id=version.retrieval_profile_id,
            retrieval_indexing_profile_id=retrieval_indexing_id,
            generation_profile_id=version.generation_profile_id,
            answer_policy_version=answer_policy,
            workspace_ids=workspace_ids,
            evaluation_state=EvaluationState(version.evaluation_state),
            is_system=identity.is_system,
            is_default=version.is_default,
        )

    async def subscriptions_for_asset(
        self,
        asset_version_id: UUID,
    ) -> tuple[tuple[UUID, UUID], ...]:
        membership = WorkspaceMembershipRecord
        system_rows = (
            await self.session.execute(
                select(
                    RagConfigurationVersionRecord.indexing_profile_id,
                    WorkspaceRecord.created_by,
                )
                .join(
                    RagSystemIndexingSubscriptionRecord,
                    RagSystemIndexingSubscriptionRecord.configuration_version_id
                    == RagConfigurationVersionRecord.id,
                )
                .join(
                    RagConfigurationRecord,
                    RagConfigurationRecord.id
                    == RagConfigurationVersionRecord.configuration_id,
                )
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == asset_version_id,
                )
                .join(
                    DocumentRecord,
                    DocumentRecord.id == AssetVersionRecord.document_id,
                )
                .join(
                    WorkspaceRecord,
                    WorkspaceRecord.id == DocumentRecord.workspace_id,
                )
                .where(
                    AssetVersionRecord.status == VersionStatus.READY,
                    DocumentRecord.active_version_id == AssetVersionRecord.id,
                    RagConfigurationRecord.is_system.is_(True),
                    RagConfigurationRecord.owner_id.is_(None),
                    workspace_is_active(),
                )
                .order_by(
                    RagConfigurationVersionRecord.indexing_profile_id,
                    WorkspaceRecord.created_by,
                )
            )
        ).all()
        user_rows = (
            await self.session.execute(
                select(
                    RagConfigurationVersionRecord.indexing_profile_id,
                    RagConfigurationRecord.owner_id,
                )
                .join(
                    RagConfigurationWorkspaceSubscriptionRecord,
                    RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id
                    == RagConfigurationVersionRecord.id,
                )
                .join(
                    RagConfigurationRecord,
                    RagConfigurationRecord.id
                    == RagConfigurationVersionRecord.configuration_id,
                )
                .join(
                    DocumentRecord,
                    DocumentRecord.workspace_id
                    == RagConfigurationWorkspaceSubscriptionRecord.workspace_id,
                )
                .join(
                    AssetVersionRecord,
                    and_(
                        AssetVersionRecord.document_id == DocumentRecord.id,
                        AssetVersionRecord.id == asset_version_id,
                    ),
                )
                .join(
                    WorkspaceRecord,
                    WorkspaceRecord.id == DocumentRecord.workspace_id,
                )
                .join(
                    membership,
                    and_(
                        membership.workspace_id == WorkspaceRecord.id,
                        membership.user_id == RagConfigurationRecord.owner_id,
                    ),
                )
                .where(
                    AssetVersionRecord.status == VersionStatus.READY,
                    DocumentRecord.active_version_id == AssetVersionRecord.id,
                    RagConfigurationRecord.is_system.is_(False),
                    RagConfigurationRecord.owner_id.is_not(None),
                    workspace_is_active(),
                    or_(
                        WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                        WorkspaceRecord.created_by == RagConfigurationRecord.owner_id,
                    ),
                )
                .order_by(
                    RagConfigurationVersionRecord.indexing_profile_id,
                    RagConfigurationRecord.owner_id,
                )
            )
        ).all()
        by_profile: dict[UUID, UUID] = {}
        for profile_id, owner_id in system_rows:
            by_profile.setdefault(profile_id, owner_id)
        for profile_id, owner_id in user_rows:
            if owner_id is not None:
                by_profile.setdefault(profile_id, owner_id)
        return tuple(by_profile.items())


class SqlAlchemySearchConfigurationResolver:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        embedding_factory: Callable[[EmbeddingModelConfig], EmbeddingPort] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repository = SqlAlchemyRagConfigurationRepository(session)
        self.embedding_factory = embedding_factory or (
            lambda config: SentenceTransformerEmbedding(
                config,
                cache_folder=self.settings.model_cache_root,
            )
        )

    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration:
        configuration = await self.repository.find_visible(configuration_id, actor_id)
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self._resolve(configuration, actor_id)

    async def resolve_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration:
        configuration = await self.repository.find_version_visible(
            configuration_version_id, actor_id
        )
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self._resolve(configuration, actor_id)

    async def resolve_frozen_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
        target: FrozenIndexTarget,
    ) -> ResolvedSearchConfiguration:
        configuration = await self.repository.find_version_visible(
            configuration_version_id, actor_id
        )
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self._resolve(configuration, actor_id, frozen_target=target)

    async def _resolve(
        self,
        configuration: SavedRagConfiguration,
        actor_id: UUID,
        *,
        frozen_target: FrozenIndexTarget | None = None,
    ) -> ResolvedSearchConfiguration:
        indexing = await self.repository.find_profile(configuration.indexing_profile_id)
        retrieval = await self.repository.find_profile(configuration.retrieval_profile_id)
        if (
            indexing is None
            or indexing.kind is not ProfileKind.INDEXING
            or retrieval is None
            or retrieval.kind is not ProfileKind.RETRIEVAL
        ):
            raise AppError(
                "configuration_invalid",
                "The immutable configuration components are unavailable.",
                409,
            )
        if _retrieval_indexing_profile_id(retrieval) != indexing.id:
            raise AppError(
                "configuration_invalid",
                "The immutable configuration components are incompatible.",
                409,
            )

        binding_rows = list(
            await self.session.scalars(
                select(ProfileModelBindingRecord).where(
                    ProfileModelBindingRecord.profile_id == indexing.id,
                    ProfileModelBindingRecord.role == ModelKind.EMBEDDING,
                )
            )
        )
        if len(binding_rows) != 1:
            raise AppError(
                "configuration_invalid",
                "The immutable indexing profile has no exact embedding binding.",
                409,
            )
        model_record = await self.session.get(
            ModelDefinitionRecord,
            binding_rows[0].model_id,
        )
        embedding_profile = indexing.config.get("embedding")
        if model_record is None or not isinstance(embedding_profile, Mapping):
            raise AppError(
                "configuration_invalid",
                "The immutable embedding definition is unavailable.",
                409,
            )
        try:
            embedding_config = EmbeddingModelConfig.from_definition(
                _model_to_domain(model_record),
                profile_config=cast(Mapping[str, object], embedding_profile),
            )
        except EmbeddingValidationError as exc:
            raise AppError("configuration_invalid", str(exc), 409) from exc

        generation_profile: GenerationProfile | None = None
        external_approval: ResolvedExternalApproval | None = None
        if configuration.generation_profile_id is not None:
            generation = await self.repository.find_profile(
                configuration.generation_profile_id
            )
            if generation is None or generation.kind is not ProfileKind.GENERATION:
                raise AppError(
                    "configuration_invalid",
                    "The immutable generation profile is unavailable.",
                    409,
                )
            if generation.deployment_version_id is None or generation.bindings:
                raise AppError(
                    "configuration_invalid",
                    "The immutable generation profile has no exact Deployment binding.",
                    409,
                )
            deployment = await self.repository.get_deployment_version(
                generation.deployment_version_id
            )
            if deployment is None:
                raise AppError(
                    "configuration_invalid",
                    "The immutable Generation Deployment is unavailable.",
                    409,
                )
            llm_record = await self.session.get(
                ModelDefinitionRecord, deployment.model_definition_id
            )
            if llm_record is None:
                raise AppError(
                    "configuration_invalid",
                    "The immutable generation model is unavailable.",
                    409,
                )
            try:
                generation_profile = resolve_generation_profile(
                    generation,
                    deployment,
                    _model_to_domain(llm_record),
                )
            except ValueError as exc:
                raise AppError("configuration_invalid", str(exc), 409) from exc
            stored_approval = await SqlAlchemyDataPolicyRepository(
                self.session
            ).get_external_approval_for_configuration(configuration.version_id)
            if stored_approval is not None:
                external_approval = ResolvedExternalApproval(
                    configuration_version_id=stored_approval.configuration_version_id,
                    deployment_version_id=stored_approval.deployment_version_id,
                    installation_policy_version_id=(
                        stored_approval.installation_policy_version_id
                    ),
                    disclosure_version=stored_approval.disclosure_version,
                    workspace_policies=tuple(
                        ResolvedWorkspacePolicyApproval(
                            workspace_id=snapshot.workspace_id,
                            policy_version_id=snapshot.policy_version_id,
                        )
                        for snapshot in stored_approval.workspace_policies
                    ),
                )

        if frozen_target is None:
            builds = list(
                await self.session.scalars(
                    select(RagIndexBuildRecord)
                    .where(
                        RagIndexBuildRecord.indexing_profile_id == indexing.id,
                        RagIndexBuildRecord.status == "ready",
                        RagIndexBuildRecord.is_active.is_(True),
                    )
                    .order_by(RagIndexBuildRecord.id)
                )
            )
            dimensions = {build.vector_dimension for build in builds}
            if not builds or None in dimensions or len(dimensions) != 1:
                raise AppError(
                    "configuration_not_ready",
                    "The selected configuration requires compatible READY active indices.",
                    409,
                )
            vector_dimension = next(iter(dimensions))
            assert vector_dimension is not None
            target: SearchIndexTarget = ActiveIndexAlias(
                IndexDescriptor(vector_dimension, "cosine"),
                self.settings.elasticsearch_index_prefix,
                indexing.id,
            )
        else:
            target = frozen_target
            if target.indexing_profile_id != indexing.id:
                raise AppError(
                    "evaluation_snapshot_drift",
                    "The frozen index target profile does not match the configuration.",
                    409,
                )
        if target.descriptor.vector_dimension != embedding_config.dimension:
            raise AppError(
                "configuration_invalid",
                "The exact index dimension does not match the immutable embedding.",
                409,
            )
        workspace_ids = configuration.workspace_ids
        if configuration.is_system:
            workspace_ids = await self.repository.all_authorized_workspace_ids(actor_id)
        return ResolvedSearchConfiguration(
            configuration_id=configuration.id,
            configuration_version_id=configuration.version_id,
            configuration_version=configuration.version,
            indexing_profile_id=indexing.id,
            retrieval_profile=retrieval,
            answer_policy_version_id=configuration.answer_policy_version_id,
            answer_policy=configuration.answer_policy_version.to_answer_policy(),
            active_index_alias=target,
            embedding=self.embedding_factory(embedding_config),
            query_max_tokens=embedding_config.max_tokens,
            workspace_ids=workspace_ids,
            experimental=configuration.experimental,
            generation_profile=generation_profile,
            external_approval=external_approval,
        )


def _retrieval_indexing_profile_id(profile: Profile) -> UUID:
    value = profile.config.get("indexing_profile_id")
    if not isinstance(value, str):
        raise RuntimeError("A retrieval profile has no exact indexing reference.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError("A retrieval profile indexing reference is invalid.") from exc
