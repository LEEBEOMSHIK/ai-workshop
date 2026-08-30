from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    ConfigurationValidationError,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)
from ai_workshop.shared.errors import AppError


def _policy(*, configuration_id=None, version: int = 1) -> AnswerPolicyVersion:
    return AnswerPolicyVersion.create(
        configuration_id=configuration_id or uuid4(),
        version=version,
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


def test_default_promotion_requires_passed_and_applicable_versioned_policy() -> None:
    pending = _configuration()
    with pytest.raises(ConfigurationValidationError, match="passed"):
        pending.as_default(evaluation_policy_version_id=uuid4(), access_leaks=0)

    passed = _configuration(evaluation_state=EvaluationState.PASSED)
    with pytest.raises(ConfigurationValidationError, match="Evaluation Policy"):
        passed.as_default(evaluation_policy_version_id=None, access_leaks=0)
    with pytest.raises(ConfigurationValidationError, match="permission leaks"):
        passed.as_default(evaluation_policy_version_id=uuid4(), access_leaks=1)

    promoted = passed.as_default(
        evaluation_policy_version_id=uuid4(),
        access_leaks=0,
    )

    assert promoted.is_default is True


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
    ) -> None:
        self.profiles = {profile.id: profile for profile in profiles}
        self.accessible = accessible_workspace_ids
        self.active_assets = active_asset_version_ids
        self.identities: dict[tuple[UUID, str], UUID] = {}
        self.saved: list[SavedRagConfiguration] = []
        self.events: list[str] = []

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

    async def active_asset_version_ids(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        del workspace_ids
        return self.active_assets

    async def list_visible(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        return [item for item in self.saved if item.owner_id in {None, actor_id}]

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
