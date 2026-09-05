from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_NAME,
    AnswerPolicyVersion,
    ConfigurationValidationError,
    ExternalTransferApprovalConfirmation,
    SavedRagConfiguration,
    validate_v1_retrieval_profile,
)
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
)
from ai_workshop.labs.rag.generation.domain import (
    GenerationExecutionSnapshot,
    generation_execution_snapshot,
)
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelDefinition,
    Profile,
    ProfileKind,
)
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    WorkspaceDataPolicyVersion,
    exact_external_approval_is_current,
)
from ai_workshop.labs.rag.policies.repository import (
    ApprovedWorkspacePolicySnapshot,
    ExternalConfigurationApproval,
)
from ai_workshop.labs.rag.policies.service import GenerationPolicyResolver
from ai_workshop.shared.errors import AppError


class RagConfigurationRepository(Protocol):
    async def find_profile(self, profile_id: UUID) -> Profile | None: ...

    async def authorized_workspace_ids(
        self,
        owner_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]: ...

    async def get_or_create_identity(
        self,
        owner_id: UUID,
        name: str,
    ) -> tuple[UUID, int]: ...

    async def add(
        self,
        configuration: SavedRagConfiguration,
    ) -> SavedRagConfiguration: ...

    async def get_deployment_version(
        self, deployment_version_id: UUID
    ) -> ModelDeploymentVersion | None: ...

    async def get_model_definition(
        self, model_definition_id: UUID
    ) -> ModelDefinition | None: ...

    async def lock_external_execution_policy(self) -> None: ...

    async def latest_installation_policy(self) -> InstallationDataPolicyVersion: ...

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]: ...

    async def add_external_approval(
        self, approval: ExternalConfigurationApproval
    ) -> ExternalConfigurationApproval: ...

    async def get_external_approval_for_configuration(
        self, configuration_version_id: UUID
    ) -> ExternalConfigurationApproval | None: ...

    async def active_asset_version_ids(
        self,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]: ...

    async def list_visible(self, actor_id: UUID) -> list[SavedRagConfiguration]: ...

    async def ready_indexing_profile_ids(
        self,
        indexing_profile_ids: tuple[UUID, ...],
    ) -> frozenset[UUID]: ...

    async def find_visible(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None: ...

    async def promote_default(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration: ...


class IngestionJobCreatorPort(Protocol):
    async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID: ...


class GenerationReadinessPort(Protocol):
    async def is_ready(self, profile_id: UUID) -> bool: ...


async def _no_op_commit() -> None:
    return None


@dataclass(frozen=True, slots=True)
class ConfigurationSaveResult:
    configuration: SavedRagConfiguration
    indexing_job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ConfigurationReadiness:
    search_ready: bool
    answer_ready: bool
    service_ready: bool
    search_reasons: tuple[str, ...] = ()
    answer_reasons: tuple[str, ...] = ()
    generation_execution_preview: GenerationExecutionSnapshot | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedGenerationExecution:
    deployment: ModelDeploymentVersion
    snapshot: GenerationExecutionSnapshot


class RagConfigurationService:
    def __init__(
        self,
        repository: RagConfigurationRepository,
        ingestion_jobs: IngestionJobCreatorPort,
        *,
        commit: Callable[[], Awaitable[None]] = _no_op_commit,
        generation_readiness: GenerationReadinessPort | None = None,
        environment: str = "local",
    ) -> None:
        self.repository = repository
        self.ingestion_jobs = ingestion_jobs
        self.commit = commit
        self.generation_readiness = generation_readiness
        self.environment = environment
        self.policy_resolver = GenerationPolicyResolver(repository)

    async def create(
        self,
        *,
        owner_id: UUID,
        name: str,
        indexing_profile_id: UUID,
        retrieval_profile_id: UUID,
        generation_profile_id: UUID | None,
        min_semantic_score: float,
        min_keyword_coverage: float,
        require_complete_provenance: bool,
        conflict_mode: str,
        workspace_ids: tuple[UUID, ...],
        answer_mode: str = "extractive",
        external_transfer_approval: ExternalTransferApprovalConfirmation | None = None,
    ) -> ConfigurationSaveResult:
        clean_name = name.strip()
        if not clean_name:
            raise AppError(
                "invalid_configuration",
                "A Saved RAG Configuration name is required.",
                422,
            )
        if clean_name == BM25_BASELINE_NAME:
            raise AppError(
                "system_configuration_reserved",
                "The system baseline identity cannot be overwritten or versioned.",
                409,
            )
        if answer_mode not in {"extractive", "generative"}:
            raise AppError(
                "invalid_answer_mode",
                "The answer mode must be extractive or generative.",
                422,
            )
        if answer_mode == "extractive" and generation_profile_id is not None:
            raise AppError(
                "generation_not_supported",
                "Generation Profiles are not supported by extractive V1.",
                422,
            )
        if answer_mode == "generative" and generation_profile_id is None:
            raise AppError(
                "generation_profile_required",
                "A generative configuration requires a Generation Profile.",
                422,
            )
        if not workspace_ids or len(set(workspace_ids)) != len(workspace_ids):
            raise AppError(
                "invalid_workspace_subscriptions",
                "Workspace subscriptions must be nonempty and unique.",
                422,
            )

        indexing = await self.repository.find_profile(indexing_profile_id)
        retrieval = await self.repository.find_profile(retrieval_profile_id)
        if indexing is None or indexing.kind is not ProfileKind.INDEXING:
            raise AppError("not_found", "The requested resource was not found.", 404)
        if retrieval is None or retrieval.kind is not ProfileKind.RETRIEVAL:
            raise AppError("not_found", "The requested resource was not found.", 404)
        generation = None
        deployment: ModelDeploymentVersion | None = None
        policy_decision = None
        if generation_profile_id is not None:
            generation = await self.repository.find_profile(generation_profile_id)
            if generation is None or generation.kind is not ProfileKind.GENERATION:
                raise AppError("not_found", "The requested resource was not found.", 404)
            if generation.deployment_version_id is None or generation.bindings:
                raise AppError(
                    "deployment_not_ready",
                    "The Generation Profile has no executable Deployment binding.",
                    422,
                )
            deployment = await self.repository.get_deployment_version(
                generation.deployment_version_id
            )
            if deployment is None:
                raise AppError(
                    "deployment_not_ready",
                    "The Generation Deployment is unavailable.",
                    422,
                )
            environment = _deployment_environment(self.environment)
            if (
                environment not in deployment.allowed_environments
                or deployment.development_only
                and environment is not DeploymentEnvironment.DEVELOPMENT
            ):
                raise AppError(
                    "deployment_not_allowed_in_environment",
                    "The Generation Deployment is not allowed in this environment.",
                    422,
                )
            if deployment.location is ExecutionLocation.EXTERNAL:
                if external_transfer_approval is None:
                    raise AppError(
                        "external_transfer_approval_required",
                        "External generation requires current owner approval.",
                        422,
                    )
            elif external_transfer_approval is not None:
                raise AppError(
                    "external_transfer_approval_not_allowed",
                    "A local Generation Deployment cannot store external approval.",
                    422,
                )
        elif external_transfer_approval is not None:
            raise AppError(
                "external_transfer_approval_not_allowed",
                "External approval requires a Generation Deployment.",
                422,
            )
        try:
            validate_v1_retrieval_profile(retrieval)
        except ConfigurationValidationError as exc:
            raise AppError("reranker_not_supported", str(exc), 422) from exc
        retrieval_indexing_profile_id = _retrieval_indexing_profile_id(retrieval)
        if retrieval_indexing_profile_id != indexing.id:
            raise AppError(
                "incompatible_profiles",
                "The retrieval profile does not reference the selected indexing profile.",
                422,
            )

        authorized = await self.repository.authorized_workspace_ids(
            owner_id,
            workspace_ids,
        )
        if set(authorized) != set(workspace_ids):
            raise AppError("not_found", "The requested resource was not found.", 404)

        if deployment is not None and deployment.location is ExecutionLocation.EXTERNAL:
            policy_decision = await self.policy_resolver.resolve(
                deployment=deployment,
                workspace_ids=authorized,
            )
            if not policy_decision.allowed:
                assert policy_decision.reason_code is not None
                raise AppError(
                    policy_decision.reason_code.value,
                    "External generation is not allowed by the current data policy.",
                    422,
                )

        configuration_id, version = await self.repository.get_or_create_identity(
            owner_id,
            clean_name,
        )
        try:
            policy = AnswerPolicyVersion.create(
                configuration_id=configuration_id,
                version=version,
                mode=answer_mode,
                min_semantic_score=min_semantic_score,
                min_keyword_coverage=min_keyword_coverage,
                require_complete_provenance=require_complete_provenance,
                conflict_mode=conflict_mode,
            )
            configuration = SavedRagConfiguration.create(
                configuration_id=configuration_id,
                configuration_version_id=uuid4(),
                owner_id=owner_id,
                name=clean_name,
                version=version,
                indexing_profile_id=indexing.id,
                retrieval_profile_id=retrieval.id,
                retrieval_indexing_profile_id=retrieval_indexing_profile_id,
                generation_profile_id=(generation.id if generation is not None else None),
                answer_policy_version=policy,
                workspace_ids=authorized,
                evaluation_state=EvaluationState.PENDING,
            )
        except (ConfigurationValidationError, ValueError) as exc:
            raise AppError("invalid_configuration", str(exc), 422) from exc

        saved = await self.repository.add(configuration)
        if deployment is not None and deployment.location is ExecutionLocation.EXTERNAL:
            assert external_transfer_approval is not None
            assert policy_decision is not None
            if len(policy_decision.workspace_policy_version_ids) != len(authorized):
                raise AppError(
                    "external_approval_stale",
                    "External generation approval no longer matches current policies.",
                    409,
                )
            approval = ExternalConfigurationApproval(
                id=uuid4(),
                configuration_version_id=saved.version_id,
                deployment_version_id=deployment.id,
                installation_policy_version_id=(
                    policy_decision.installation_policy_version_id
                ),
                approved_by=owner_id,
                disclosure_version=external_transfer_approval.disclosure_version,
                workspace_policies=tuple(
                    ApprovedWorkspacePolicySnapshot(workspace_id, policy_version_id)
                    for workspace_id, policy_version_id in zip(
                        authorized,
                        policy_decision.workspace_policy_version_ids,
                        strict=True,
                    )
                ),
                created_at=datetime.now(UTC),
            )
            try:
                await self.repository.add_external_approval(approval)
            except (ValueError, SQLAlchemyError) as exc:
                raise AppError(
                    "external_approval_stale",
                    "External generation approval no longer matches current policies.",
                    409,
                ) from exc
        job_ids: list[UUID] = []
        for asset_version_id in await self.repository.active_asset_version_ids(authorized):
            job_ids.append(
                await self.ingestion_jobs.ensure_indexed(
                    EnsureIndexedCommand(
                        asset_version_id=asset_version_id,
                        indexing_profile_id=indexing.id,
                        requested_by=owner_id,
                    )
                )
            )
        await self.commit()
        return ConfigurationSaveResult(saved, tuple(job_ids))

    async def list(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        return await self.repository.list_visible(actor_id)

    async def search_readiness(
        self,
        configurations: tuple[SavedRagConfiguration, ...],
    ) -> dict[UUID, bool]:
        profile_ids = tuple(dict.fromkeys(item.indexing_profile_id for item in configurations))
        ready_profile_ids = await self.repository.ready_indexing_profile_ids(profile_ids)
        return {
            item.version_id: item.indexing_profile_id in ready_profile_ids
            for item in configurations
        }

    async def readiness(
        self,
        configurations: tuple[SavedRagConfiguration, ...],
    ) -> dict[UUID, ConfigurationReadiness]:
        search = await self.search_readiness(configurations)
        result: dict[UUID, ConfigurationReadiness] = {}
        for item in configurations:
            search_ready = search[item.version_id]
            answer_ready = False
            answer_reasons: tuple[str, ...]
            resolved_execution = await self._resolve_generation_execution(item)
            if item.generation_profile_id is None:
                answer_ready = True
                answer_reasons = ()
            elif (
                resolved_execution is None
                or self.generation_readiness is None
                or not await self.generation_readiness.is_ready(
                    item.generation_profile_id
                )
            ):
                answer_reasons = ("deployment_not_ready",)
            elif resolved_execution.deployment.location is not ExecutionLocation.EXTERNAL:
                answer_ready = True
                answer_reasons = ()
            else:
                policy = await self.policy_resolver.resolve(
                    deployment=resolved_execution.deployment,
                    workspace_ids=item.workspace_ids,
                )
                if not policy.allowed:
                    answer_reasons = (
                        policy.reason_code.value
                        if policy.reason_code is not None
                        else "provider_not_allowed",
                    )
                else:
                    approval = (
                        await self.repository.get_external_approval_for_configuration(
                            item.version_id
                        )
                    )
                    answer_ready = approval is not None and (
                        exact_external_approval_is_current(
                            approval_configuration_version_id=(
                                approval.configuration_version_id
                            ),
                            approval_deployment_version_id=(
                                approval.deployment_version_id
                            ),
                            approval_installation_policy_version_id=(
                                approval.installation_policy_version_id
                            ),
                            approval_disclosure_version=approval.disclosure_version,
                            approval_workspace_policy_snapshots=tuple(
                                (snapshot.workspace_id, snapshot.policy_version_id)
                                for snapshot in approval.workspace_policies
                            ),
                            configuration_version_id=item.version_id,
                            deployment_version_id=resolved_execution.deployment.id,
                            workspace_ids=item.workspace_ids,
                            policy=policy,
                            disclosure_version=(
                                resolved_execution.snapshot.disclosure_version
                            ),
                        )
                    )
                    answer_reasons = (() if answer_ready else ("deployment_not_ready",))
            result[item.version_id] = ConfigurationReadiness(
                search_ready=search_ready,
                answer_ready=answer_ready,
                service_ready=search_ready and answer_ready,
                search_reasons=(() if search_ready else ("active_index_unavailable",)),
                answer_reasons=answer_reasons,
                generation_execution_preview=(
                    resolved_execution.snapshot
                    if resolved_execution is not None
                    else None
                ),
            )
        return result

    async def _resolve_generation_execution(
        self,
        configuration: SavedRagConfiguration,
    ) -> _ResolvedGenerationExecution | None:
        if configuration.generation_profile_id is None:
            return None
        profile = await self.repository.find_profile(
            configuration.generation_profile_id
        )
        if (
            profile is None
            or profile.kind is not ProfileKind.GENERATION
            or profile.deployment_version_id is None
            or profile.bindings
        ):
            return None
        deployment = await self.repository.get_deployment_version(
            profile.deployment_version_id
        )
        if deployment is None:
            return None
        model = await self.repository.get_model_definition(
            deployment.model_definition_id
        )
        if model is None:
            return None
        try:
            resolved = resolve_generation_profile(profile, deployment, model)
            return _ResolvedGenerationExecution(
                deployment=deployment,
                snapshot=generation_execution_snapshot(resolved),
            )
        except (TypeError, ValueError):
            return None

    async def detail(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration:
        configuration = await self.repository.find_visible(configuration_id, actor_id)
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return configuration

    async def promote_default(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration:
        promoted = await self.repository.promote_default(configuration_id, actor_id)
        await self.commit()
        return promoted


def _deployment_environment(environment: str) -> DeploymentEnvironment:
    if environment in {"local", "test"}:
        return DeploymentEnvironment.DEVELOPMENT
    if environment == "production":
        return DeploymentEnvironment.PRODUCTION
    raise AppError(
        "deployment_not_allowed_in_environment",
        "The application environment cannot run this Deployment.",
        422,
    )


def _retrieval_indexing_profile_id(profile: Profile) -> UUID:
    value = profile.config.get("indexing_profile_id")
    if not isinstance(value, str):
        raise AppError(
            "incompatible_profiles",
            "The retrieval profile has no exact indexing profile reference.",
            422,
        )
    try:
        return UUID(value)
    except ValueError as exc:
        raise AppError(
            "incompatible_profiles",
            "The retrieval profile indexing reference is invalid.",
            422,
        ) from exc
