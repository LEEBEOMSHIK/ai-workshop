from collections.abc import Mapping
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    JsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    freeze_json,
    thaw_json,
)
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)


class ModelRegistryRepository(Protocol):
    async def model_version_exists(self, kind: ModelKind, name: str, version: int) -> bool: ...

    async def add_model(self, model: ModelDefinition) -> ModelDefinition: ...

    async def list_models(self) -> list[ModelDefinition]: ...

    async def find_models(self, model_ids: tuple[UUID, ...]) -> list[ModelDefinition]: ...

    async def profile_version_exists(
        self,
        kind: ProfileKind,
        name: str,
        version: int,
    ) -> bool: ...

    async def add_profile(self, profile: Profile) -> Profile: ...

    async def list_profiles(self, kind: ProfileKind | None = None) -> list[Profile]: ...

    async def find_profile(self, profile_id: UUID) -> Profile | None: ...

    async def set_default(self, profile: Profile) -> Profile: ...


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
            ProfileModelBinding(role=ModelKind(binding.role), model_id=binding.model_id)
            for binding in record.bindings
        ),
        evaluation_state=EvaluationState(record.evaluation_state),
        is_default=record.is_default,
    )


class SqlAlchemyModelRegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def model_version_exists(self, kind: ModelKind, name: str, version: int) -> bool:
        result = await self.session.execute(
            select(ModelDefinitionRecord.id).where(
                ModelDefinitionRecord.kind == kind,
                ModelDefinitionRecord.name == name,
                ModelDefinitionRecord.version == version,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_model(self, model: ModelDefinition) -> ModelDefinition:
        record = ModelDefinitionRecord(
            id=model.id,
            kind=model.kind,
            name=model.name,
            version=model.version,
            config=cast(dict[str, object], thaw_json(model.config)),
        )
        self.session.add(record)
        await self.session.flush()
        return _model_to_domain(record)

    async def list_models(self) -> list[ModelDefinition]:
        result = await self.session.execute(
            select(ModelDefinitionRecord).order_by(
                ModelDefinitionRecord.kind,
                ModelDefinitionRecord.name,
                ModelDefinitionRecord.version,
            )
        )
        return [_model_to_domain(record) for record in result.scalars()]

    async def find_models(self, model_ids: tuple[UUID, ...]) -> list[ModelDefinition]:
        if not model_ids:
            return []
        result = await self.session.execute(
            select(ModelDefinitionRecord).where(ModelDefinitionRecord.id.in_(model_ids))
        )
        return [_model_to_domain(record) for record in result.scalars()]

    async def profile_version_exists(
        self, kind: ProfileKind, name: str, version: int
    ) -> bool:
        result = await self.session.execute(
            select(ProfileRecord.id).where(
                ProfileRecord.kind == kind,
                ProfileRecord.name == name,
                ProfileRecord.version == version,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_profile(self, profile: Profile) -> Profile:
        record = ProfileRecord(
            id=profile.id,
            kind=profile.kind,
            name=profile.name,
            version=profile.version,
            config=cast(dict[str, object], thaw_json(profile.config)),
            evaluation_state=profile.evaluation_state,
            is_default=profile.is_default,
        )
        record.bindings = [
            ProfileModelBindingRecord(
                role=binding.role,
                model_id=binding.model_id,
            )
            for binding in profile.bindings
        ]
        self.session.add(record)
        await self.session.flush()
        return _profile_to_domain(record)

    async def list_profiles(self, kind: ProfileKind | None = None) -> list[Profile]:
        statement = select(ProfileRecord)
        if kind is not None:
            statement = statement.where(ProfileRecord.kind == kind)
        result = await self.session.execute(
            statement.order_by(ProfileRecord.kind, ProfileRecord.name, ProfileRecord.version)
        )
        return [_profile_to_domain(record) for record in result.scalars()]

    async def find_profile(self, profile_id: UUID) -> Profile | None:
        result = await self.session.execute(
            select(ProfileRecord).where(ProfileRecord.id == profile_id)
        )
        record = result.scalar_one_or_none()
        return _profile_to_domain(record) if record else None

    async def set_default(self, profile: Profile) -> Profile:
        await self.session.execute(
            update(ProfileRecord)
            .where(ProfileRecord.kind == profile.kind)
            .values(is_default=False)
        )
        record = await self.session.get(ProfileRecord, profile.id)
        if record is None:
            raise LookupError("Profile does not exist.")
        record.is_default = True
        await self.session.flush()
        return _profile_to_domain(record)
