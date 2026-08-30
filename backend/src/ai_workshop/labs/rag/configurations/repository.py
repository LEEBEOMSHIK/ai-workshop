from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select
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
)
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
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
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.retrieval.domain import ActiveIndexAlias
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.repository import workspace_is_active
from ai_workshop.shared.errors import AppError


def _profile_to_domain(record: ProfileRecord) -> Profile:
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
        return _profile_to_domain(record) if record is not None else None

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
        policy = await self.session.get(
            AnswerPolicyVersionRecord,
            version.answer_policy_version_id,
        )
        if policy is None or policy.configuration_id != identity.id:
            raise RuntimeError("A Saved RAG Configuration has no immutable Answer Policy.")
        if (
            policy.mode != "extractive"
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
            mode="extractive",
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
        rows = (
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
        for profile_id, owner_id in rows:
            if owner_id is not None:
                by_profile.setdefault(profile_id, owner_id)
        return tuple(by_profile.items())


class SqlAlchemySearchConfigurationResolver:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repository = SqlAlchemyRagConfigurationRepository(session)

    async def resolve(
        self,
        configuration_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration:
        configuration = await self.repository.find_visible(configuration_id, actor_id)
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
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

        build = await self.session.scalar(
            select(RagIndexBuildRecord).where(
                RagIndexBuildRecord.indexing_profile_id == indexing.id,
                RagIndexBuildRecord.status == "ready",
                RagIndexBuildRecord.is_active.is_(True),
            )
        )
        if build is None or build.vector_dimension is None:
            raise AppError(
                "configuration_not_ready",
                "The selected configuration has no READY active index.",
                409,
            )
        if build.vector_dimension != embedding_config.dimension:
            raise AppError(
                "configuration_invalid",
                "The active index dimension does not match the immutable embedding.",
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
            active_index_alias=ActiveIndexAlias(
                IndexDescriptor(build.vector_dimension, "cosine"),
                self.settings.elasticsearch_index_prefix,
                indexing.id,
            ),
            embedding=SentenceTransformerEmbedding(
                embedding_config,
                cache_folder=self.settings.model_cache_root,
            ),
            workspace_ids=workspace_ids,
            experimental=configuration.experimental,
        )


def _retrieval_indexing_profile_id(profile: Profile) -> UUID:
    value = profile.config.get("indexing_profile_id")
    if not isinstance(value, str):
        raise RuntimeError("A retrieval profile has no exact indexing reference.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError("A retrieval profile indexing reference is invalid.") from exc
