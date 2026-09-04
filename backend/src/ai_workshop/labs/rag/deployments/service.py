from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import Depends
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentValidationError,
    ModelDeploymentVersion,
)
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    DeploymentRepositoryConflict,
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
from ai_workshop.labs.rag.deployments.secrets import (
    EndpointReferenceResolver,
    SecretReferenceError,
    SecretReferenceResolver,
)
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class DeploymentRepository(Protocol):
    async def get_model_definition(self, model_id: UUID) -> ModelDefinition | None: ...

    async def create_identity(
        self, deployment_id: UUID, *, created_by: UUID, created_at: datetime
    ) -> None: ...

    async def identity_exists(
        self, deployment_id: UUID, *, for_update: bool
    ) -> bool: ...

    async def next_version(self, deployment_id: UUID) -> int: ...

    async def ensure_secret_reference(
        self,
        reference_name: str,
        *,
        created_by: UUID,
        created_at: datetime,
    ) -> None: ...

    async def add_version(
        self, deployment: ModelDeploymentVersion
    ) -> ModelDeploymentVersion: ...

    async def list_versions(self) -> list[DeploymentCatalogEntry]: ...


class DeploymentRegistryService:
    def __init__(
        self,
        repository: DeploymentRepository,
        *,
        endpoint_refs: Mapping[str, str],
        secret_refs: Mapping[str, SecretStr],
    ) -> None:
        self._repository = repository
        self._endpoint_resolver = EndpointReferenceResolver(endpoint_refs)
        self._secret_resolver = SecretReferenceResolver(secret_refs)

    async def create_identity(
        self, request: DeploymentVersionCreate, *, actor_id: UUID
    ) -> DeploymentCatalogEntry:
        self._validate_references(request)
        model = await self._require_llm_model(request.model_definition_id)
        now = datetime.now(UTC)
        deployment_id = uuid4()
        deployment = self._build_version(
            request,
            deployment_id=deployment_id,
            version=1,
            actor_id=actor_id,
        )
        try:
            await self._repository.create_identity(
                deployment_id, created_by=actor_id, created_at=now
            )
            await self._register_resolved_secret(request, actor_id=actor_id, now=now)
            await self._repository.add_version(deployment)
        except DeploymentRepositoryConflict as exc:
            raise AppError(
                "deployment_version_exists",
                "This deployment version already exists.",
                409,
            ) from exc
        return DeploymentCatalogEntry(deployment, model.name, model.version)

    async def create_version(
        self,
        deployment_id: UUID,
        request: DeploymentVersionCreate,
        *,
        actor_id: UUID,
    ) -> DeploymentCatalogEntry:
        self._validate_references(request)
        model = await self._require_llm_model(request.model_definition_id)
        if not await self._repository.identity_exists(deployment_id, for_update=True):
            raise AppError("not_found", "The requested resource was not found.", 404)
        version = await self._repository.next_version(deployment_id)
        now = datetime.now(UTC)
        deployment = self._build_version(
            request,
            deployment_id=deployment_id,
            version=version,
            actor_id=actor_id,
        )
        try:
            await self._register_resolved_secret(request, actor_id=actor_id, now=now)
            await self._repository.add_version(deployment)
        except DeploymentRepositoryConflict as exc:
            raise AppError(
                "deployment_version_exists",
                "This deployment version already exists.",
                409,
            ) from exc
        return DeploymentCatalogEntry(deployment, model.name, model.version)

    async def list_versions(self) -> list[DeploymentCatalogEntry]:
        return await self._repository.list_versions()

    def secret_configured(self, entry: DeploymentCatalogEntry) -> bool:
        reference = entry.deployment.secret_ref
        if reference is None:
            return False
        try:
            self._secret_resolver.resolve(reference)
        except SecretReferenceError:
            return False
        return True

    def _validate_references(self, request: DeploymentVersionCreate) -> None:
        try:
            self._endpoint_resolver.resolve(request.endpoint_ref)
        except SecretReferenceError as exc:
            raise AppError(
                "unknown_endpoint_reference",
                "The endpoint reference is not configured.",
                422,
            ) from exc
        if request.secret_ref is not None:
            try:
                self._secret_resolver.resolve(request.secret_ref)
            except SecretReferenceError as exc:
                raise AppError(
                    "unknown_secret_reference",
                    "The secret reference is not configured.",
                    422,
                ) from exc

    async def _require_llm_model(self, model_id: UUID) -> ModelDefinition:
        model = await self._repository.get_model_definition(model_id)
        if model is None or model.kind is not ModelKind.LLM:
            raise AppError(
                "invalid_model_definition",
                "The deployment requires an LLM Model Definition.",
                422,
            )
        return model

    async def _register_resolved_secret(
        self,
        request: DeploymentVersionCreate,
        *,
        actor_id: UUID,
        now: datetime,
    ) -> None:
        if request.secret_ref is None:
            return
        await self._repository.ensure_secret_reference(
            request.secret_ref,
            created_by=actor_id,
            created_at=now,
        )

    @staticmethod
    def _build_version(
        request: DeploymentVersionCreate,
        *,
        deployment_id: UUID,
        version: int,
        actor_id: UUID,
    ) -> ModelDeploymentVersion:
        try:
            return ModelDeploymentVersion.create(
                deployment_id=deployment_id,
                version=version,
                display_name=request.display_name,
                description=request.description,
                model_definition_id=request.model_definition_id,
                provider=request.provider,
                location=request.location,
                allowed_environments=request.allowed_environments,
                provider_model_id=request.provider_model_id,
                endpoint_ref=request.endpoint_ref,
                secret_ref=request.secret_ref,
                capabilities=request.capabilities,
                external_transfer=request.external_transfer,
                transmitted_data_categories=request.transmitted_data_categories,
                data_processing_notice_ref=request.data_processing_notice_ref,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                retry_backoff_seconds=request.retry_backoff_seconds,
                healthcheck_enabled=request.healthcheck_enabled,
                development_only=request.development_only,
                created_by=actor_id,
            )
        except DeploymentValidationError as exc:
            raise AppError("invalid_deployment", str(exc), 422) from exc


def get_deployment_registry_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DeploymentRegistryService:
    return DeploymentRegistryService(
        SqlAlchemyDeploymentRepository(session),
        endpoint_refs=settings.provider_endpoint_refs,
        secret_refs=settings.provider_secret_refs,
    )
