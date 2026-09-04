from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
)
from ai_workshop.labs.rag.policies.domain import (
    DataPolicyValidationError,
    InstallationDataPolicyVersion,
    OutboundMode,
    PolicyDecision,
    PolicyReasonCode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
    resolve_external_transfer_policy,
)
from ai_workshop.labs.rag.policies.repository import (
    DataPolicyRepositoryConflict,
    SqlAlchemyDataPolicyRepository,
)
from ai_workshop.labs.rag.policies.schemas import (
    InstallationDataPolicyCreate,
    WorkspaceDataPolicyCreate,
)
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class PolicyReader(Protocol):
    async def latest_installation_policy(self) -> InstallationDataPolicyVersion: ...

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]: ...


class DataPolicyRepository(PolicyReader, Protocol):
    async def installation_policy_id(self, *, for_update: bool = False) -> UUID: ...

    async def next_installation_version(self, policy_id: UUID) -> int: ...

    async def add_installation_version(
        self, policy: InstallationDataPolicyVersion
    ) -> InstallationDataPolicyVersion: ...

    async def workspace_exists(
        self, workspace_id: UUID, *, for_update: bool = False
    ) -> bool: ...

    async def workspace_policy_id(
        self, workspace_id: UUID, *, for_update: bool = False
    ) -> UUID | None: ...

    async def create_workspace_policy_identity(
        self,
        policy_id: UUID,
        *,
        workspace_id: UUID,
        created_at: datetime,
    ) -> None: ...

    async def next_workspace_version(self, policy_id: UUID) -> int: ...

    async def add_workspace_version(
        self, policy: WorkspaceDataPolicyVersion
    ) -> WorkspaceDataPolicyVersion: ...


class GenerationPolicyResolver:
    def __init__(self, repository: PolicyReader) -> None:
        self._repository = repository

    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision:
        requested_workspace_ids = _unique_ids(workspace_ids)
        installation = await self._repository.latest_installation_policy()
        workspace_policies = await self._repository.latest_workspace_policies(
            requested_workspace_ids
        )
        policy_by_workspace = {
            policy.workspace_id: policy for policy in workspace_policies
        }
        exact_policies = tuple(
            policy_by_workspace[workspace_id]
            for workspace_id in requested_workspace_ids
            if workspace_id in policy_by_workspace
        )
        audit_ids = tuple(policy.id for policy in exact_policies)

        if deployment.location in {
            ExecutionLocation.LOCAL,
            ExecutionLocation.ON_PREMISE,
        }:
            return PolicyDecision(True, None, installation.id, audit_ids)

        if len(exact_policies) != len(requested_workspace_ids):
            return PolicyDecision(
                False,
                PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
                installation.id,
                audit_ids,
            )

        installation_decision = resolve_external_transfer_policy(
            provider=deployment.provider,
            installation=installation,
            workspaces=(),
        )
        if not installation_decision.allowed:
            return PolicyDecision(
                False,
                installation_decision.reason_code,
                installation.id,
                audit_ids,
            )
        try:
            return resolve_external_transfer_policy(
                provider=deployment.provider,
                installation=installation,
                workspaces=exact_policies,
            )
        except DataPolicyValidationError:
            return PolicyDecision(
                False,
                PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
                installation.id,
                audit_ids,
            )


class DataPolicyService:
    def __init__(self, repository: DataPolicyRepository) -> None:
        self._repository = repository

    async def current_installation(self) -> InstallationDataPolicyVersion:
        return await self._repository.latest_installation_policy()

    async def append_installation(
        self,
        request: InstallationDataPolicyCreate,
        *,
        actor_id: UUID,
    ) -> InstallationDataPolicyVersion:
        policy_id = await self._repository.installation_policy_id(for_update=True)
        version = await self._repository.next_installation_version(policy_id)
        try:
            policy = InstallationDataPolicyVersion.create(
                policy_id=policy_id,
                version=version,
                mode=request.mode,
                approved_providers=request.approved_providers,
                changed_by=actor_id,
            )
            return await self._repository.add_installation_version(policy)
        except DataPolicyValidationError as exc:
            raise _invalid_policy_error() from exc
        except DataPolicyRepositoryConflict as exc:
            raise _version_conflict_error() from exc

    async def current_workspace(
        self, workspace_id: UUID
    ) -> WorkspaceDataPolicyVersion:
        if not await self._repository.workspace_exists(workspace_id):
            raise _not_found_error()
        policies = await self._repository.latest_workspace_policies((workspace_id,))
        if not policies:
            raise _not_found_error()
        return policies[0]

    async def append_workspace(
        self,
        workspace_id: UUID,
        request: WorkspaceDataPolicyCreate,
        *,
        actor_id: UUID,
    ) -> WorkspaceDataPolicyVersion:
        await self._repository.installation_policy_id(for_update=True)
        installation = await self._repository.latest_installation_policy()
        if not await self._repository.workspace_exists(workspace_id, for_update=True):
            raise _not_found_error()

        policy_id = await self._repository.workspace_policy_id(
            workspace_id, for_update=True
        )
        now = datetime.now(UTC)
        if policy_id is None:
            policy_id = uuid4()
            try:
                await self._repository.create_workspace_policy_identity(
                    policy_id,
                    workspace_id=workspace_id,
                    created_at=now,
                )
            except DataPolicyRepositoryConflict as exc:
                raise _version_conflict_error() from exc
        version = await self._repository.next_workspace_version(policy_id)
        try:
            policy = WorkspaceDataPolicyVersion.create(
                policy_id=policy_id,
                workspace_id=workspace_id,
                version=version,
                mode=request.mode,
                approved_providers=request.approved_providers,
                changed_by=actor_id,
            )
            _ensure_workspace_restriction(installation, policy)
            return await self._repository.add_workspace_version(policy)
        except DataPolicyValidationError as exc:
            raise _invalid_policy_error() from exc
        except DataPolicyRepositoryConflict as exc:
            raise _version_conflict_error() from exc


def _ensure_workspace_restriction(
    installation: InstallationDataPolicyVersion,
    workspace: WorkspaceDataPolicyVersion,
) -> None:
    if workspace.mode is not WorkspaceOutboundMode.APPROVED_PROVIDERS:
        return
    if (
        installation.mode is OutboundMode.DENY
        or not workspace.approved_providers.issubset(
            installation.approved_providers
        )
    ):
        raise DataPolicyValidationError(
            "A Workspace policy cannot widen the Installation policy."
        )


def _unique_ids(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(values))


def _not_found_error() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _invalid_policy_error() -> AppError:
    return AppError("invalid_data_policy", "The data policy is invalid.", 422)


def _version_conflict_error() -> AppError:
    return AppError(
        "data_policy_version_exists",
        "This data policy version already exists.",
        409,
    )


def get_data_policy_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DataPolicyService:
    return DataPolicyService(SqlAlchemyDataPolicyRepository(session))
