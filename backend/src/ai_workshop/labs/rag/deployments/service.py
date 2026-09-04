from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import Depends
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentValidationError,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    DeploymentHealthCheck,
    DeploymentRepositoryConflict,
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
from ai_workshop.labs.rag.deployments.secrets import (
    EndpointReferenceResolver,
    SecretReferenceError,
    SecretReferenceResolver,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.generation.openai_compatible import (
    LocalOpenAICompatibleRuntime,
)
from ai_workshop.labs.rag.generation.runtime_resolver import (
    GenerationRuntimeResolver,
)
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.labs.rag.policies.service import GenerationPolicyResolver
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


class DeploymentHealthRepository(Protocol):
    async def get_version(self, version_id: UUID) -> ModelDeploymentVersion | None: ...

    async def add_health_check(
        self, health_check: DeploymentHealthCheck
    ) -> DeploymentHealthCheck: ...


class DeploymentPolicyResolver(Protocol):
    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision: ...


class RuntimeResolver(Protocol):
    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime: ...


@dataclass(frozen=True, slots=True)
class DeploymentHealthResult:
    status: str
    safe_error_code: str | None
    provider: ProviderKind
    provider_model_id: str
    observed_provider_model_id: str | None
    latency_ms: int


class DeploymentHealthService:
    def __init__(
        self,
        repository: DeploymentHealthRepository,
        policy_resolver: DeploymentPolicyResolver,
        runtime_resolver: RuntimeResolver,
    ) -> None:
        self._repository = repository
        self._policy_resolver = policy_resolver
        self._runtime_resolver = runtime_resolver

    async def check(
        self,
        version_id: UUID,
        *,
        actor_id: UUID,
    ) -> DeploymentHealthResult:
        deployment = await self._repository.get_version(version_id)
        if deployment is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        started = monotonic()
        if (
            not deployment.healthcheck_enabled
            or deployment.provider is ProviderKind.OPENAI_RESPONSES
        ):
            return await self._record_failure(
                deployment,
                actor_id=actor_id,
                code="deployment_not_ready",
                latency_ms=_latency_ms(started),
            )
        try:
            policy = await self._policy_resolver.resolve(
                deployment=deployment,
                workspace_ids=(),
            )
            resolved = self._runtime_resolver.resolve(deployment, policy)
            health = await resolved.adapter.health()
            if (
                health.execution.deployment_version_id != deployment.id
                or health.execution.provider is not deployment.provider
                or health.execution.provider_model_id != deployment.provider_model_id
                or health.ready
                and health.observed_provider_model_id
                != deployment.provider_model_id
            ):
                raise GenerationProviderError(
                    "provider_invalid_response",
                    retryable=False,
                )
            if not health.ready:
                return await self._record_failure(
                    deployment,
                    actor_id=actor_id,
                    code="deployment_not_ready",
                    latency_ms=health.execution.latency_ms,
                )
        except GenerationProviderError as exc:
            return await self._record_failure(
                deployment,
                actor_id=actor_id,
                code=exc.code,
                latency_ms=_latency_ms(started),
            )
        recorded = DeploymentHealthCheck(
            id=uuid4(),
            deployment_version_id=deployment.id,
            status="ready",
            safe_error_code=None,
            observed_provider_model_id=health.observed_provider_model_id,
            latency_ms=health.execution.latency_ms,
            checked_by=actor_id,
            created_at=datetime.now(UTC),
        )
        await self._repository.add_health_check(recorded)
        return DeploymentHealthResult(
            status=recorded.status,
            safe_error_code=None,
            provider=deployment.provider,
            provider_model_id=deployment.provider_model_id,
            observed_provider_model_id=recorded.observed_provider_model_id,
            latency_ms=recorded.latency_ms or 0,
        )

    async def _record_failure(
        self,
        deployment: ModelDeploymentVersion,
        *,
        actor_id: UUID,
        code: str,
        latency_ms: int,
    ) -> DeploymentHealthResult:
        recorded = DeploymentHealthCheck(
            id=uuid4(),
            deployment_version_id=deployment.id,
            status="failed",
            safe_error_code=code,
            observed_provider_model_id=None,
            latency_ms=latency_ms,
            checked_by=actor_id,
            created_at=datetime.now(UTC),
        )
        await self._repository.add_health_check(recorded)
        return DeploymentHealthResult(
            status=recorded.status,
            safe_error_code=code,
            provider=deployment.provider,
            provider_model_id=deployment.provider_model_id,
            observed_provider_model_id=None,
            latency_ms=latency_ms,
        )


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


def get_deployment_health_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DeploymentHealthService:
    repository = SqlAlchemyDeploymentRepository(session)
    runtime_resolver = GenerationRuntimeResolver(
        environment=settings.environment,
        endpoint_refs=settings.provider_endpoint_refs,
        secret_refs=settings.provider_secret_refs,
        factories={
            ProviderKind.LOCAL_OPENAI_COMPATIBLE: (
                lambda deployment, endpoint, secret: LocalOpenAICompatibleRuntime(
                    deployment=deployment,
                    endpoint=endpoint,
                    api_key=secret,
                )
            )
        },
    )
    return DeploymentHealthService(
        repository,
        GenerationPolicyResolver(SqlAlchemyDataPolicyRepository(session)),
        runtime_resolver,
    )


def _latency_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
