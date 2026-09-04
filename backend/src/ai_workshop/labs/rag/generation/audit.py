from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.generation.audit_models import (
    GenerationAuditWorkspacePolicySnapshotRecord,
    GenerationExecutionAuditRecord,
)


@dataclass(frozen=True, slots=True)
class WorkspacePolicyAuditSnapshot:
    workspace_id: UUID
    policy_version_id: UUID


@dataclass(frozen=True, slots=True)
class GenerationExecutionAudit:
    id: UUID
    actor_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    deployment_version_id: UUID
    installation_policy_version_id: UUID
    workspace_policies: tuple[WorkspacePolicyAuditSnapshot, ...]
    provider: ProviderKind
    provider_model_id: str
    location: ExecutionLocation
    external_transfer: bool
    policy_allowed: bool
    policy_reason_code: str | None
    prompt_ref: str
    prompt_version: int
    evidence_ids: tuple[UUID, ...]
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    provider_reported_input_tokens: int | None
    provider_reported_output_tokens: int | None
    cost_basis_version: str | None
    estimated_cost_microunits: int | None
    status: str
    safe_error_code: str | None
    correlation_id: UUID
    created_at: datetime


class SqlAlchemyGenerationAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, audit: GenerationExecutionAudit) -> GenerationExecutionAudit:
        self._session.add(
            GenerationExecutionAuditRecord(
                id=audit.id,
                actor_id=audit.actor_id,
                configuration_version_id=audit.configuration_version_id,
                generation_profile_id=audit.generation_profile_id,
                deployment_version_id=audit.deployment_version_id,
                installation_policy_version_id=audit.installation_policy_version_id,
                provider=audit.provider.value,
                provider_model_id=audit.provider_model_id,
                location=audit.location.value,
                external_transfer=audit.external_transfer,
                policy_allowed=audit.policy_allowed,
                policy_reason_code=audit.policy_reason_code,
                prompt_ref=audit.prompt_ref,
                prompt_version=audit.prompt_version,
                evidence_ids=list(audit.evidence_ids),
                input_tokens=audit.input_tokens,
                output_tokens=audit.output_tokens,
                latency_ms=audit.latency_ms,
                provider_reported_input_tokens=audit.provider_reported_input_tokens,
                provider_reported_output_tokens=audit.provider_reported_output_tokens,
                cost_basis_version=audit.cost_basis_version,
                estimated_cost_microunits=audit.estimated_cost_microunits,
                status=audit.status,
                safe_error_code=audit.safe_error_code,
                correlation_id=audit.correlation_id,
                created_at=audit.created_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            GenerationAuditWorkspacePolicySnapshotRecord(
                audit_id=audit.id,
                workspace_id=snapshot.workspace_id,
                workspace_policy_version_id=snapshot.policy_version_id,
            )
            for snapshot in audit.workspace_policies
        )
        await self._session.flush()
        return audit

    async def get(self, audit_id: UUID) -> GenerationExecutionAudit | None:
        record = await self._session.get(GenerationExecutionAuditRecord, audit_id)
        if record is None:
            return None
        rows = (
            await self._session.scalars(
                select(GenerationAuditWorkspacePolicySnapshotRecord)
                .where(
                    GenerationAuditWorkspacePolicySnapshotRecord.audit_id == audit_id
                )
                .order_by(GenerationAuditWorkspacePolicySnapshotRecord.workspace_id)
            )
        ).all()
        return GenerationExecutionAudit(
            id=record.id,
            actor_id=record.actor_id,
            configuration_version_id=record.configuration_version_id,
            generation_profile_id=record.generation_profile_id,
            deployment_version_id=record.deployment_version_id,
            installation_policy_version_id=record.installation_policy_version_id,
            workspace_policies=tuple(
                WorkspacePolicyAuditSnapshot(
                    workspace_id=row.workspace_id,
                    policy_version_id=row.workspace_policy_version_id,
                )
                for row in rows
            ),
            provider=ProviderKind(record.provider),
            provider_model_id=record.provider_model_id,
            location=ExecutionLocation(record.location),
            external_transfer=record.external_transfer,
            policy_allowed=record.policy_allowed,
            policy_reason_code=record.policy_reason_code,
            prompt_ref=record.prompt_ref,
            prompt_version=record.prompt_version,
            evidence_ids=tuple(record.evidence_ids),
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            latency_ms=record.latency_ms,
            provider_reported_input_tokens=record.provider_reported_input_tokens,
            provider_reported_output_tokens=record.provider_reported_output_tokens,
            cost_basis_version=record.cost_basis_version,
            estimated_cost_microunits=record.estimated_cost_microunits,
            status=record.status,
            safe_error_code=record.safe_error_code,
            correlation_id=record.correlation_id,
            created_at=record.created_at,
        )
