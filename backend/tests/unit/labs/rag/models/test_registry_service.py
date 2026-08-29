from uuid import UUID

import pytest

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)
from ai_workshop.labs.rag.models.repository import ModelRegistryRepository
from ai_workshop.labs.rag.models.service import RagModelRegistryService
from ai_workshop.shared.errors import AppError


class MemoryRegistryRepository(ModelRegistryRepository):
    def __init__(self) -> None:
        self.models: list[ModelDefinition] = []
        self.profiles: list[Profile] = []

    async def model_version_exists(self, kind: ModelKind, name: str, version: int) -> bool:
        return any(
            model.kind is kind and model.name == name and model.version == version
            for model in self.models
        )

    async def add_model(self, model: ModelDefinition) -> ModelDefinition:
        self.models.append(model)
        return model

    async def list_models(self) -> list[ModelDefinition]:
        return list(self.models)

    async def find_models(self, model_ids: tuple[UUID, ...]) -> list[ModelDefinition]:
        return [model for model in self.models if model.id in model_ids]

    async def profile_version_exists(
        self, kind: ProfileKind, name: str, version: int
    ) -> bool:
        return any(
            profile.kind is kind and profile.name == name and profile.version == version
            for profile in self.profiles
        )

    async def add_profile(self, profile: Profile) -> Profile:
        self.profiles.append(profile)
        return profile

    async def list_profiles(self, kind: ProfileKind | None = None) -> list[Profile]:
        return [profile for profile in self.profiles if kind is None or profile.kind is kind]

    async def find_profile(self, profile_id: UUID) -> Profile | None:
        return next((profile for profile in self.profiles if profile.id == profile_id), None)

    async def set_default(self, profile: Profile) -> Profile:
        self.profiles = [
            current
            if current.kind is not profile.kind
            else Profile(
                current.id,
                current.kind,
                current.name,
                current.version,
                current.config,
                current.bindings,
                current.evaluation_state,
                current.id == profile.id,
            )
            for current in self.profiles
        ]
        return next(current for current in self.profiles if current.id == profile.id)


@pytest.mark.asyncio
async def test_duplicate_model_version_is_rejected() -> None:
    service = RagModelRegistryService(MemoryRegistryRepository())
    await service.register_model(
        kind=ModelKind.EMBEDDING,
        name="embedding-baseline",
        version=1,
        config={"dimension": 768},
    )

    with pytest.raises(AppError) as exc_info:
        await service.register_model(
            kind=ModelKind.EMBEDDING,
            name="embedding-baseline",
            version=1,
            config={"dimension": 1024},
        )

    assert exc_info.value.code == "model_version_exists"


@pytest.mark.asyncio
async def test_duplicate_profile_version_is_rejected_but_a_new_version_is_allowed() -> None:
    service = RagModelRegistryService(MemoryRegistryRepository())
    await service.register_profile(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-baseline",
        version=1,
        config={"bm25": {"top_k": 20}},
        bindings=(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.register_profile(
            kind=ProfileKind.RETRIEVAL,
            name="bm25-baseline",
            version=1,
            config={"bm25": {"top_k": 30}},
            bindings=(),
        )

    second = await service.register_profile(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-baseline",
        version=2,
        config={"bm25": {"top_k": 30}},
        bindings=(),
    )

    assert exc_info.value.code == "profile_version_exists"
    assert second.version == 2


@pytest.mark.asyncio
async def test_profile_binding_must_match_registered_model_kind() -> None:
    repository = MemoryRegistryRepository()
    service = RagModelRegistryService(repository)
    embedding = await service.register_model(
        kind=ModelKind.EMBEDDING,
        name="embedding-baseline",
        version=1,
        config={"dimension": 768},
    )

    with pytest.raises(AppError) as exc_info:
        await service.register_profile(
            kind=ProfileKind.GENERATION,
            name="generation-baseline",
            version=1,
            config={"prompt_ref": "grounded-answer-v1"},
            bindings=(ProfileModelBinding(ModelKind.LLM, embedding.id),),
        )

    assert exc_info.value.code == "invalid_model_binding"


@pytest.mark.asyncio
async def test_only_passed_profile_is_promoted_and_replaces_kind_default() -> None:
    repository = MemoryRegistryRepository()
    service = RagModelRegistryService(repository)
    first = await service.register_profile(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-a",
        version=1,
        config={"bm25": {}},
        bindings=(),
        evaluation_state=EvaluationState.PASSED,
    )
    second = await service.register_profile(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-b",
        version=1,
        config={"bm25": {}},
        bindings=(),
        evaluation_state=EvaluationState.PASSED,
    )

    await service.promote_default(first.id)
    promoted = await service.promote_default(second.id)

    profiles = await service.list_profiles(ProfileKind.RETRIEVAL)
    assert promoted.is_default is True
    assert [profile.id for profile in profiles if profile.is_default] == [second.id]
