from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_NAME,
    AnswerPolicyVersion,
    ConfigurationValidationError,
    SavedRagConfiguration,
    validate_v1_retrieval_profile,
)
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.models.domain import EvaluationState, Profile, ProfileKind
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

    async def active_asset_version_ids(
        self,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]: ...

    async def list_visible(self, actor_id: UUID) -> list[SavedRagConfiguration]: ...

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


async def _no_op_commit() -> None:
    return None


@dataclass(frozen=True, slots=True)
class ConfigurationSaveResult:
    configuration: SavedRagConfiguration
    indexing_job_ids: tuple[UUID, ...]


class RagConfigurationService:
    def __init__(
        self,
        repository: RagConfigurationRepository,
        ingestion_jobs: IngestionJobCreatorPort,
        *,
        commit: Callable[[], Awaitable[None]] = _no_op_commit,
    ) -> None:
        self.repository = repository
        self.ingestion_jobs = ingestion_jobs
        self.commit = commit

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
        if generation_profile_id is not None:
            raise AppError(
                "generation_not_supported",
                "Generation Profiles are not supported by extractive V1.",
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

        configuration_id, version = await self.repository.get_or_create_identity(
            owner_id,
            clean_name,
        )
        try:
            policy = AnswerPolicyVersion.create(
                configuration_id=configuration_id,
                version=version,
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
                generation_profile_id=None,
                answer_policy_version=policy,
                workspace_ids=authorized,
                evaluation_state=EvaluationState.PENDING,
            )
        except (ConfigurationValidationError, ValueError) as exc:
            raise AppError("invalid_configuration", str(exc), 422) from exc

        saved = await self.repository.add(configuration)
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
