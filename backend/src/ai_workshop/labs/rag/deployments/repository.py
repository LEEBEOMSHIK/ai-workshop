from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
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
from ai_workshop.labs.rag.models.domain import (
    JsonValue,
    ModelDefinition,
    ModelKind,
    freeze_json,
)
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord

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


@dataclass(frozen=True, slots=True)
class DeploymentCatalogEntry:
    deployment: ModelDeploymentVersion
    model_name: str
    model_version: int
    latest_health: DeploymentHealthCheck | None = None


class DeploymentRepositoryConflict(RuntimeError):
    pass


class SqlAlchemyDeploymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_model_definition(self, model_id: UUID) -> ModelDefinition | None:
        record = await self._session.get(ModelDefinitionRecord, model_id)
        if record is None:
            return None
        frozen_config = freeze_json(cast(dict[str, JsonValue], record.config))
        if not isinstance(frozen_config, Mapping):
            raise TypeError("Stored model configuration must be a mapping.")
        return ModelDefinition(
            id=record.id,
            kind=ModelKind(record.kind),
            name=record.name,
            version=record.version,
            config=frozen_config,
        )

    async def create_identity(
        self,
        deployment_id: UUID,
        *,
        created_by: UUID,
        created_at: datetime,
    ) -> None:
        self._session.add(
            ModelDeploymentRecord(
                id=deployment_id,
                created_by=created_by,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DeploymentRepositoryConflict from exc

    async def identity_exists(
        self, deployment_id: UUID, *, for_update: bool
    ) -> bool:
        statement = select(ModelDeploymentRecord.id).where(
            ModelDeploymentRecord.id == deployment_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement) is not None

    async def next_version(self, deployment_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(ModelDeploymentVersionRecord.version)).where(
                ModelDeploymentVersionRecord.deployment_id == deployment_id
            )
        )
        return (latest or 0) + 1

    async def ensure_secret_reference(
        self,
        reference_name: str,
        *,
        created_by: UUID,
        created_at: datetime,
    ) -> None:
        await self._session.execute(
            pg_insert(SecretReferenceRecord)
            .values(
                namespace=PROVIDER_SECRET_NAMESPACE,
                reference_name=reference_name,
                created_by=created_by,
                created_at=created_at,
                updated_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=["namespace", "reference_name"]
            )
        )

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
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DeploymentRepositoryConflict from exc
        return deployment

    async def list_versions(self) -> list[DeploymentCatalogEntry]:
        ranked_health = (
            select(
                DeploymentHealthCheckRecord.id.label("health_id"),
                DeploymentHealthCheckRecord.deployment_version_id.label(
                    "deployment_version_id"
                ),
                func.row_number()
                .over(
                    partition_by=DeploymentHealthCheckRecord.deployment_version_id,
                    order_by=(
                        DeploymentHealthCheckRecord.created_at.desc(),
                        DeploymentHealthCheckRecord.id.desc(),
                    ),
                )
                .label("health_rank"),
            )
            .subquery()
        )
        rows = await self._session.execute(
            select(
                ModelDeploymentVersionRecord,
                ModelDefinitionRecord,
                DeploymentHealthCheckRecord,
            )
            .join(
                ModelDefinitionRecord,
                ModelDefinitionRecord.id
                == ModelDeploymentVersionRecord.model_definition_id,
            )
            .outerjoin(
                ranked_health,
                and_(
                    ranked_health.c.deployment_version_id
                    == ModelDeploymentVersionRecord.id,
                    ranked_health.c.health_rank == 1,
                ),
            )
            .outerjoin(
                DeploymentHealthCheckRecord,
                DeploymentHealthCheckRecord.id == ranked_health.c.health_id,
            )
            .order_by(
                ModelDeploymentVersionRecord.created_at,
                ModelDeploymentVersionRecord.deployment_id,
                ModelDeploymentVersionRecord.version,
            )
        )
        return [
            DeploymentCatalogEntry(
                deployment=_version_domain(deployment),
                model_name=model.name,
                model_version=model.version,
                latest_health=(
                    None if health is None else _health_domain(health)
                ),
            )
            for deployment, model, health in rows
        ]

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
        return _health_domain(record)


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


def _health_domain(record: DeploymentHealthCheckRecord) -> DeploymentHealthCheck:
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
