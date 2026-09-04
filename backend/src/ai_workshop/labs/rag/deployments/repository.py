from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.models import (
    DeploymentHealthCheckRecord,
    ModelDeploymentRecord,
    ModelDeploymentVersionRecord,
    SecretReferenceRecord,
)

PROVIDER_SECRET_NAMESPACE = "provider_secret"


@dataclass(frozen=True, slots=True)
class SecretReference:
    reference_name: str
    created_by: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeploymentHealthCheck:
    id: UUID
    deployment_version_id: UUID
    status: str
    safe_error_code: str | None
    observed_provider_model_id: str | None
    latency_ms: int | None
    checked_by: UUID
    created_at: datetime


class SqlAlchemyDeploymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_secret_reference(
        self, reference: SecretReference
    ) -> SecretReference:
        self._session.add(
            SecretReferenceRecord(
                namespace=PROVIDER_SECRET_NAMESPACE,
                reference_name=reference.reference_name,
                created_by=reference.created_by,
                created_at=reference.created_at,
                updated_at=reference.created_at,
            )
        )
        await self._session.flush()
        return reference

    async def add_version(
        self, deployment: ModelDeploymentVersion
    ) -> ModelDeploymentVersion:
        identity = await self._session.get(
            ModelDeploymentRecord, deployment.deployment_id
        )
        if identity is None:
            self._session.add(
                ModelDeploymentRecord(
                    id=deployment.deployment_id,
                    created_by=deployment.created_by,
                    created_at=deployment.created_at,
                    updated_at=deployment.created_at,
                )
            )
        self._session.add(_version_record(deployment))
        await self._session.flush()
        return deployment

    async def get_version(self, version_id: UUID) -> ModelDeploymentVersion | None:
        record = await self._session.get(ModelDeploymentVersionRecord, version_id)
        return None if record is None else _version_domain(record)

    async def add_health_check(
        self, health_check: DeploymentHealthCheck
    ) -> DeploymentHealthCheck:
        self._session.add(
            DeploymentHealthCheckRecord(
                id=health_check.id,
                deployment_version_id=health_check.deployment_version_id,
                status=health_check.status,
                safe_error_code=health_check.safe_error_code,
                observed_provider_model_id=health_check.observed_provider_model_id,
                latency_ms=health_check.latency_ms,
                checked_by=health_check.checked_by,
                created_at=health_check.created_at,
            )
        )
        await self._session.flush()
        return health_check

    async def latest_health_check(
        self, deployment_version_id: UUID
    ) -> DeploymentHealthCheck | None:
        record = await self._session.scalar(
            select(DeploymentHealthCheckRecord)
            .where(
                DeploymentHealthCheckRecord.deployment_version_id
                == deployment_version_id
            )
            .order_by(
                DeploymentHealthCheckRecord.created_at.desc(),
                DeploymentHealthCheckRecord.id.desc(),
            )
            .limit(1)
        )
        if record is None:
            return None
        return DeploymentHealthCheck(
            id=record.id,
            deployment_version_id=record.deployment_version_id,
            status=record.status,
            safe_error_code=record.safe_error_code,
            observed_provider_model_id=record.observed_provider_model_id,
            latency_ms=record.latency_ms,
            checked_by=record.checked_by,
            created_at=record.created_at,
        )


def _version_record(deployment: ModelDeploymentVersion) -> ModelDeploymentVersionRecord:
    return ModelDeploymentVersionRecord(
        id=deployment.id,
        deployment_id=deployment.deployment_id,
        version=deployment.version,
        display_name=deployment.display_name,
        description=deployment.description,
        model_definition_id=deployment.model_definition_id,
        provider=deployment.provider.value,
        location=deployment.location.value,
        allowed_environments=[item.value for item in deployment.allowed_environments],
        provider_model_id=deployment.provider_model_id,
        endpoint_ref=deployment.endpoint_ref,
        secret_ref_namespace=(
            PROVIDER_SECRET_NAMESPACE if deployment.secret_ref is not None else None
        ),
        secret_ref=deployment.secret_ref,
        capabilities=sorted(item.value for item in deployment.capabilities),
        external_transfer=deployment.external_transfer,
        transmitted_data_categories=list(deployment.transmitted_data_categories),
        data_processing_notice_ref=deployment.data_processing_notice_ref,
        timeout_seconds=deployment.timeout_seconds,
        max_retries=deployment.max_retries,
        retry_backoff_seconds=deployment.retry_backoff_seconds,
        healthcheck_enabled=deployment.healthcheck_enabled,
        development_only=deployment.development_only,
        created_by=deployment.created_by,
        created_at=deployment.created_at,
        updated_at=deployment.created_at,
    )


def _version_domain(record: ModelDeploymentVersionRecord) -> ModelDeploymentVersion:
    return ModelDeploymentVersion(
        id=record.id,
        deployment_id=record.deployment_id,
        version=record.version,
        display_name=record.display_name,
        description=record.description,
        model_definition_id=record.model_definition_id,
        provider=ProviderKind(record.provider),
        location=ExecutionLocation(record.location),
        allowed_environments=tuple(
            DeploymentEnvironment(item) for item in record.allowed_environments
        ),
        provider_model_id=record.provider_model_id,
        endpoint_ref=record.endpoint_ref,
        secret_ref=record.secret_ref,
        capabilities=frozenset(
            DeploymentCapability(item) for item in record.capabilities
        ),
        external_transfer=record.external_transfer,
        transmitted_data_categories=tuple(record.transmitted_data_categories),
        data_processing_notice_ref=record.data_processing_notice_ref,
        timeout_seconds=record.timeout_seconds,
        max_retries=record.max_retries,
        retry_backoff_seconds=record.retry_backoff_seconds,
        healthcheck_enabled=record.healthcheck_enabled,
        development_only=record.development_only,
        created_by=record.created_by,
        created_at=record.created_at,
    )
