from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.configurations.models import (
    ExternalConfigurationApprovalRecord,
    ExternalConfigurationApprovalWorkspaceRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.deployments.models import ModelDeploymentVersionRecord
from ai_workshop.labs.rag.models.models import ProfileDeploymentBindingRecord
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.models import (
    InstallationDataPolicyRecord,
    InstallationDataPolicyVersionRecord,
    WorkspaceDataPolicyRecord,
    WorkspaceDataPolicyVersionRecord,
)
from ai_workshop.platform.workspaces.models import WorkspaceRecord


class DataPolicyRepositoryConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedWorkspacePolicySnapshot:
    workspace_id: UUID
    policy_version_id: UUID


@dataclass(frozen=True, slots=True)
class ExternalConfigurationApproval:
    id: UUID
    configuration_version_id: UUID
    deployment_version_id: UUID
    installation_policy_version_id: UUID
    approved_by: UUID
    disclosure_version: str
    workspace_policies: tuple[ApprovedWorkspacePolicySnapshot, ...]
    created_at: datetime


class SqlAlchemyDataPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def installation_policy_id(self, *, for_update: bool = False) -> UUID:
        statement = select(InstallationDataPolicyRecord.id).where(
            InstallationDataPolicyRecord.singleton_key.is_(True)
        )
        if for_update:
            statement = statement.with_for_update()
        policy_id = await self._session.scalar(statement)
        if policy_id is None:
            raise RuntimeError("The Installation data policy is not initialized.")
        return policy_id

    async def next_installation_version(self, policy_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(InstallationDataPolicyVersionRecord.version)).where(
                InstallationDataPolicyVersionRecord.policy_id == policy_id
            )
        )
        return (latest or 0) + 1

    async def add_installation_version(
        self, policy: InstallationDataPolicyVersion
    ) -> InstallationDataPolicyVersion:
        self._session.add(
            InstallationDataPolicyVersionRecord(
                id=policy.id,
                policy_id=policy.policy_id,
                version=policy.version,
                outbound_mode=policy.mode.value,
                approved_providers=sorted(
                    provider.value for provider in policy.approved_providers
                ),
                changed_by=policy.changed_by,
                created_at=policy.created_at,
                updated_at=policy.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DataPolicyRepositoryConflict from exc
        return policy

    async def get_installation_version(
        self, version_id: UUID
    ) -> InstallationDataPolicyVersion | None:
        record = await self._session.get(
            InstallationDataPolicyVersionRecord, version_id
        )
        if record is None:
            return None
        return InstallationDataPolicyVersion(
            id=record.id,
            policy_id=record.policy_id,
            version=record.version,
            mode=OutboundMode(record.outbound_mode),
            approved_providers=frozenset(
                ProviderKind(provider) for provider in record.approved_providers
            ),
            changed_by=record.changed_by,
            created_at=record.created_at,
        )

    async def latest_installation_policy(self) -> InstallationDataPolicyVersion:
        version_id = await self._session.scalar(
            select(InstallationDataPolicyVersionRecord.id)
            .order_by(
                InstallationDataPolicyVersionRecord.version.desc(),
                InstallationDataPolicyVersionRecord.id.desc(),
            )
            .limit(1)
        )
        if version_id is None:
            raise RuntimeError("The Installation data policy is not initialized.")
        policy = await self.get_installation_version(version_id)
        if policy is None:
            raise RuntimeError("The Installation data policy is not initialized.")
        return policy

    async def workspace_exists(
        self, workspace_id: UUID, *, for_update: bool = False
    ) -> bool:
        statement = select(WorkspaceRecord.id).where(WorkspaceRecord.id == workspace_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement) is not None

    async def workspace_policy_id(
        self, workspace_id: UUID, *, for_update: bool = False
    ) -> UUID | None:
        statement = select(WorkspaceDataPolicyRecord.id).where(
            WorkspaceDataPolicyRecord.workspace_id == workspace_id
        )
        if for_update:
            statement = statement.with_for_update()
        policy_id = await self._session.scalar(statement)
        if policy_id is None or isinstance(policy_id, UUID):
            return policy_id
        raise TypeError("Workspace data policy identity must be a UUID.")

    async def create_workspace_policy_identity(
        self,
        policy_id: UUID,
        *,
        workspace_id: UUID,
        created_at: datetime,
    ) -> None:
        self._session.add(
            WorkspaceDataPolicyRecord(
                id=policy_id,
                workspace_id=workspace_id,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DataPolicyRepositoryConflict from exc

    async def next_workspace_version(self, policy_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(WorkspaceDataPolicyVersionRecord.version)).where(
                WorkspaceDataPolicyVersionRecord.policy_id == policy_id
            )
        )
        return (latest or 0) + 1

    async def add_workspace_version(
        self, policy: WorkspaceDataPolicyVersion
    ) -> WorkspaceDataPolicyVersion:
        identity = await self._session.get(WorkspaceDataPolicyRecord, policy.policy_id)
        if identity is None:
            self._session.add(
                WorkspaceDataPolicyRecord(
                    id=policy.policy_id,
                    workspace_id=policy.workspace_id,
                    created_at=policy.created_at,
                    updated_at=policy.created_at,
                )
            )
        self._session.add(
            WorkspaceDataPolicyVersionRecord(
                id=policy.id,
                policy_id=policy.policy_id,
                workspace_id=policy.workspace_id,
                version=policy.version,
                outbound_mode=policy.mode.value,
                approved_providers=sorted(
                    provider.value for provider in policy.approved_providers
                ),
                changed_by=policy.changed_by,
                created_at=policy.created_at,
                updated_at=policy.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DataPolicyRepositoryConflict from exc
        return policy

    async def get_workspace_version(
        self, version_id: UUID
    ) -> WorkspaceDataPolicyVersion | None:
        record = await self._session.get(WorkspaceDataPolicyVersionRecord, version_id)
        if record is None:
            return None
        return WorkspaceDataPolicyVersion(
            id=record.id,
            policy_id=record.policy_id,
            workspace_id=record.workspace_id,
            version=record.version,
            mode=WorkspaceOutboundMode(record.outbound_mode),
            approved_providers=frozenset(
                ProviderKind(provider) for provider in record.approved_providers
            ),
            changed_by=record.changed_by,
            created_at=record.created_at,
        )

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]:
        if not workspace_ids:
            return ()
        records = (
            await self._session.scalars(
                select(WorkspaceDataPolicyVersionRecord)
                .where(
                    WorkspaceDataPolicyVersionRecord.workspace_id.in_(workspace_ids)
                )
                .order_by(
                    WorkspaceDataPolicyVersionRecord.workspace_id,
                    WorkspaceDataPolicyVersionRecord.version.desc(),
                )
            )
        ).all()
        latest_by_workspace: dict[UUID, WorkspaceDataPolicyVersionRecord] = {}
        for policy_record in records:
            latest_by_workspace.setdefault(policy_record.workspace_id, policy_record)
        resolved: list[WorkspaceDataPolicyVersion] = []
        for workspace_id in workspace_ids:
            selected_record = latest_by_workspace.get(workspace_id)
            if selected_record is None:
                continue
            policy = await self.get_workspace_version(selected_record.id)
            if policy is not None:
                resolved.append(policy)
        return tuple(resolved)

    async def add_external_approval(
        self, approval: ExternalConfigurationApproval
    ) -> ExternalConfigurationApproval:
        await self._validate_external_approval(approval)
        self._session.add(
            ExternalConfigurationApprovalRecord(
                id=approval.id,
                configuration_version_id=approval.configuration_version_id,
                deployment_version_id=approval.deployment_version_id,
                installation_policy_version_id=approval.installation_policy_version_id,
                approved_by=approval.approved_by,
                disclosure_version=approval.disclosure_version,
                created_at=approval.created_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            ExternalConfigurationApprovalWorkspaceRecord(
                approval_id=approval.id,
                workspace_id=snapshot.workspace_id,
                workspace_policy_version_id=snapshot.policy_version_id,
            )
            for snapshot in approval.workspace_policies
        )
        await self._session.flush()
        return approval

    async def _validate_external_approval(
        self, approval: ExternalConfigurationApproval
    ) -> None:
        await self._session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('ai-workshop:rag:external-approval-contract:v1', 0)"
                ")"
            )
        )
        configuration = await self._session.get(
            RagConfigurationVersionRecord, approval.configuration_version_id
        )
        if configuration is None or configuration.generation_profile_id is None:
            raise ValueError("external approval configuration is not generative")
        bound_deployment_id = await self._session.scalar(
            select(ProfileDeploymentBindingRecord.deployment_version_id).where(
                ProfileDeploymentBindingRecord.profile_id
                == configuration.generation_profile_id
            )
        )
        deployment = await self._session.get(
            ModelDeploymentVersionRecord, approval.deployment_version_id
        )
        if (
            bound_deployment_id != approval.deployment_version_id
            or deployment is None
            or deployment.location != "external"
            or not deployment.external_transfer
        ):
            raise ValueError(
                "external approval deployment does not match the configuration"
            )

        latest_installation_id = await self._session.scalar(
            select(InstallationDataPolicyVersionRecord.id)
            .order_by(
                InstallationDataPolicyVersionRecord.version.desc(),
                InstallationDataPolicyVersionRecord.id.desc(),
            )
            .limit(1)
        )
        if latest_installation_id != approval.installation_policy_version_id:
            raise ValueError("external approval installation policy is not current")

        subscribed_workspace_ids = set(
            (
                await self._session.scalars(
                    select(RagConfigurationWorkspaceSubscriptionRecord.workspace_id).where(
                        RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id
                        == approval.configuration_version_id
                    )
                )
            ).all()
        )
        snapshot_by_workspace = {
            snapshot.workspace_id: snapshot.policy_version_id
            for snapshot in approval.workspace_policies
        }
        if len(snapshot_by_workspace) != len(approval.workspace_policies):
            raise ValueError("external approval workspace snapshot is duplicated")
        if set(snapshot_by_workspace) != subscribed_workspace_ids:
            raise ValueError("external approval workspace snapshot set is not exact")

        latest_workspace_policies = await self.latest_workspace_policies(
            tuple(sorted(subscribed_workspace_ids))
        )
        expected_policy_by_workspace = {
            policy.workspace_id: policy.id for policy in latest_workspace_policies
        }
        if snapshot_by_workspace != expected_policy_by_workspace:
            raise ValueError("external approval workspace policy snapshot is not current")

    async def get_external_approval_for_configuration(
        self, configuration_version_id: UUID
    ) -> ExternalConfigurationApproval | None:
        record = await self._session.scalar(
            select(ExternalConfigurationApprovalRecord).where(
                ExternalConfigurationApprovalRecord.configuration_version_id
                == configuration_version_id
            )
        )
        if record is None:
            return None
        workspace_records = (
            await self._session.scalars(
                select(ExternalConfigurationApprovalWorkspaceRecord)
                .where(
                    ExternalConfigurationApprovalWorkspaceRecord.approval_id
                    == record.id
                )
                .order_by(ExternalConfigurationApprovalWorkspaceRecord.workspace_id)
            )
        ).all()
        return ExternalConfigurationApproval(
            id=record.id,
            configuration_version_id=record.configuration_version_id,
            deployment_version_id=record.deployment_version_id,
            installation_policy_version_id=record.installation_policy_version_id,
            approved_by=record.approved_by,
            disclosure_version=record.disclosure_version,
            workspace_policies=tuple(
                ApprovedWorkspacePolicySnapshot(
                    workspace_id=workspace.workspace_id,
                    policy_version_id=workspace.workspace_policy_version_id,
                )
                for workspace in workspace_records
            ),
            created_at=record.created_at,
        )
