from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ai_workshop.labs.rag.deployments.domain import ProviderKind


class OutboundMode(StrEnum):
    DENY = "deny"
    APPROVED_PROVIDERS = "approved_providers"


class WorkspaceOutboundMode(StrEnum):
    INHERIT = "inherit"
    DENY = "deny"
    APPROVED_PROVIDERS = "approved_providers"


class PolicyReasonCode(StrEnum):
    PROVIDER_NOT_ALLOWED = "provider_not_allowed"
    WORKSPACE_EXTERNAL_TRANSFER_DENIED = "workspace_external_transfer_denied"


class DataPolicyValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InstallationDataPolicyVersion:
    id: UUID
    policy_id: UUID
    version: int
    mode: OutboundMode
    approved_providers: frozenset[ProviderKind]
    changed_by: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OutboundMode):
            raise DataPolicyValidationError(
                "An Installation policy requires a named outbound mode."
            )
        providers = _validated_providers(self.approved_providers)
        _validate_policy_shape(
            version=self.version,
            approved_mode=self.mode is OutboundMode.APPROVED_PROVIDERS,
            providers=providers,
            policy_name="Installation",
        )
        object.__setattr__(self, "approved_providers", providers)

    @classmethod
    def create(
        cls,
        *,
        policy_id: UUID,
        version: int,
        mode: OutboundMode,
        approved_providers: Collection[ProviderKind],
        changed_by: UUID,
    ) -> "InstallationDataPolicyVersion":
        return cls(
            id=uuid4(),
            policy_id=policy_id,
            version=version,
            mode=mode,
            approved_providers=frozenset(approved_providers),
            changed_by=changed_by,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceDataPolicyVersion:
    id: UUID
    policy_id: UUID
    workspace_id: UUID
    version: int
    mode: WorkspaceOutboundMode
    approved_providers: frozenset[ProviderKind]
    changed_by: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mode, WorkspaceOutboundMode):
            raise DataPolicyValidationError(
                "A Workspace policy requires a named outbound mode."
            )
        providers = _validated_providers(self.approved_providers)
        _validate_policy_shape(
            version=self.version,
            approved_mode=self.mode is WorkspaceOutboundMode.APPROVED_PROVIDERS,
            providers=providers,
            policy_name="Workspace",
        )
        object.__setattr__(self, "approved_providers", providers)

    @classmethod
    def create(
        cls,
        *,
        policy_id: UUID,
        workspace_id: UUID,
        version: int,
        mode: WorkspaceOutboundMode,
        approved_providers: Collection[ProviderKind],
        changed_by: UUID,
    ) -> "WorkspaceDataPolicyVersion":
        return cls(
            id=uuid4(),
            policy_id=policy_id,
            workspace_id=workspace_id,
            version=version,
            mode=mode,
            approved_providers=frozenset(approved_providers),
            changed_by=changed_by,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: PolicyReasonCode | None
    installation_policy_version_id: UUID
    workspace_policy_version_ids: tuple[UUID, ...]
    workspace_policy_snapshots: tuple[tuple[UUID, UUID], ...] = ()

    def __post_init__(self) -> None:
        if self.reason_code is not None and not isinstance(
            self.reason_code, PolicyReasonCode
        ):
            raise DataPolicyValidationError(
                "A policy decision requires an approved reason code."
            )


def resolve_external_transfer_policy(
    *,
    provider: ProviderKind,
    installation: InstallationDataPolicyVersion,
    workspaces: Collection[WorkspaceDataPolicyVersion],
) -> PolicyDecision:
    workspace_policies = tuple(workspaces)
    _validate_workspace_restrictions(installation, workspace_policies)
    version_ids = tuple(policy.id for policy in workspace_policies)
    snapshots = tuple((policy.workspace_id, policy.id) for policy in workspace_policies)

    if provider is ProviderKind.LOCAL_OPENAI_COMPATIBLE:
        return PolicyDecision(True, None, installation.id, version_ids, snapshots)
    if installation.mode is OutboundMode.DENY:
        return PolicyDecision(
            False,
            PolicyReasonCode.PROVIDER_NOT_ALLOWED,
            installation.id,
            version_ids,
            snapshots,
        )
    if provider not in installation.approved_providers:
        return PolicyDecision(
            False,
            PolicyReasonCode.PROVIDER_NOT_ALLOWED,
            installation.id,
            version_ids,
            snapshots,
        )

    for policy in workspace_policies:
        if policy.mode is WorkspaceOutboundMode.DENY:
            return PolicyDecision(
                False,
                PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
                installation.id,
                version_ids,
                snapshots,
            )
        if (
            policy.mode is WorkspaceOutboundMode.APPROVED_PROVIDERS
            and provider not in policy.approved_providers
        ):
            return PolicyDecision(
                False,
                PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
                installation.id,
                version_ids,
                snapshots,
            )

    return PolicyDecision(True, None, installation.id, version_ids, snapshots)


def _validated_providers(
    providers: Collection[ProviderKind],
) -> frozenset[ProviderKind]:
    frozen = frozenset(providers)
    if any(not isinstance(provider, ProviderKind) for provider in frozen):
        raise DataPolicyValidationError("Policies require named Provider kinds.")
    return frozen


def _validate_policy_shape(
    *,
    version: int,
    approved_mode: bool,
    providers: frozenset[ProviderKind],
    policy_name: str,
) -> None:
    if isinstance(version, bool) or version < 1:
        raise DataPolicyValidationError(f"A {policy_name} policy version must be positive.")
    if approved_mode and not providers:
        raise DataPolicyValidationError(
            f"A {policy_name} policy requires at least one approved Provider."
        )
    if not approved_mode and providers:
        raise DataPolicyValidationError(
            f"A {policy_name} policy may only use approved Providers in approved mode."
        )


def _validate_workspace_restrictions(
    installation: InstallationDataPolicyVersion,
    workspaces: tuple[WorkspaceDataPolicyVersion, ...],
) -> None:
    for policy in workspaces:
        if policy.mode is not WorkspaceOutboundMode.APPROVED_PROVIDERS:
            continue
        if (
            installation.mode is OutboundMode.DENY
            or not policy.approved_providers.issubset(installation.approved_providers)
        ):
            raise DataPolicyValidationError(
                "A Workspace policy cannot widen the Installation policy."
            )
