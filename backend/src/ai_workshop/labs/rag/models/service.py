from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    JsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    ProfileValidationError,
)
from ai_workshop.labs.rag.models.repository import (
    ModelRegistryRepository,
    SqlAlchemyModelRegistryRepository,
)
from ai_workshop.labs.rag.models.schemas import parse_profile_yaml
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class RagModelRegistryService:
    def __init__(self, repository: ModelRegistryRepository) -> None:
        self.repository = repository

    async def register_model(
        self,
        *,
        kind: ModelKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
    ) -> ModelDefinition:
        if await self.repository.model_version_exists(kind, name.strip(), version):
            raise AppError("model_version_exists", "This model version already exists.", 409)
        try:
            model = ModelDefinition.create(
                kind=kind,
                name=name,
                version=version,
                config=config,
            )
        except ProfileValidationError as exc:
            raise AppError("invalid_model", str(exc), 422) from exc
        return await self.repository.add_model(model)

    async def list_models(self) -> list[ModelDefinition]:
        return await self.repository.list_models()

    async def register_profile(
        self,
        *,
        kind: ProfileKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
        bindings: tuple[ProfileModelBinding, ...],
        deployment_version_id: UUID | None = None,
        evaluation_state: EvaluationState = EvaluationState.DRAFT,
    ) -> Profile:
        if await self.repository.profile_version_exists(kind, name.strip(), version):
            raise AppError("profile_version_exists", "This profile version already exists.", 409)
        model_ids = tuple(binding.model_id for binding in bindings)
        models = await self.repository.find_models(model_ids)
        kinds_by_id = {model.id: model.kind for model in models}
        if len(kinds_by_id) != len(set(model_ids)) or any(
            kinds_by_id.get(binding.model_id) is not binding.role for binding in bindings
        ):
            raise AppError(
                "invalid_model_binding",
                "A profile binding must reference a model of the same kind.",
                422,
            )
        if deployment_version_id is not None:
            deployment = await self.repository.find_deployment_version(
                deployment_version_id
            )
            if deployment is None:
                raise AppError(
                    "invalid_deployment_binding",
                    "A profile Deployment binding is invalid.",
                    422,
                )
            deployment_models = await self.repository.find_models(
                (deployment.model_definition_id,)
            )
            if (
                len(deployment_models) != 1
                or deployment_models[0].kind is not ModelKind.LLM
            ):
                raise AppError(
                    "invalid_deployment_binding",
                    "A Generation Profile Deployment must reference an LLM.",
                    422,
                )
        try:
            profile = Profile.create(
                kind=kind,
                name=name,
                version=version,
                config=config,
                bindings=bindings,
                deployment_version_id=deployment_version_id,
                evaluation_state=evaluation_state,
            )
        except ProfileValidationError as exc:
            raise AppError("invalid_profile", str(exc), 422) from exc
        return await self.repository.add_profile(profile)

    async def list_profiles(self, kind: ProfileKind | None = None) -> list[Profile]:
        return await self.repository.list_profiles(kind)

    async def register_profile_yaml(self, *, kind: ProfileKind, content: str) -> Profile:
        document = parse_profile_yaml(content, expected_kind=kind)
        return await self.register_profile(
            kind=document.kind,
            name=document.name,
            version=document.version,
            config=document.config,
            bindings=tuple(item.to_domain() for item in document.bindings),
            deployment_version_id=document.deployment_version_id,
            evaluation_state=document.evaluation_state,
        )

    async def promote_default(self, profile_id: UUID) -> Profile:
        profile = await self.repository.find_profile(profile_id)
        if profile is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        if profile.legacy:
            raise AppError(
                "legacy_profile_read_only",
                "A legacy Generation Profile is read-only.",
                409,
            )
        try:
            promoted = profile.as_default()
        except ProfileValidationError as exc:
            raise AppError("profile_not_evaluated", str(exc), 409) from exc
        return await self.repository.set_default(promoted)


def get_rag_model_registry_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RagModelRegistryService:
    return RagModelRegistryService(SqlAlchemyModelRegistryRepository(session))
