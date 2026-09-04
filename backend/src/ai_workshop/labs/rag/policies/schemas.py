from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)


class InstallationDataPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: OutboundMode
    approved_providers: set[ProviderKind] = Field(default_factory=set)


class WorkspaceDataPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: WorkspaceOutboundMode
    approved_providers: set[ProviderKind] = Field(default_factory=set)


class InstallationDataPolicyResponse(BaseModel):
    policy_id: UUID
    version_id: UUID
    version: int
    mode: OutboundMode
    approved_providers: list[ProviderKind]
    changed_by: UUID
    created_at: datetime

    @classmethod
    def from_domain(cls, policy: InstallationDataPolicyVersion) -> Self:
        return cls(
            policy_id=policy.policy_id,
            version_id=policy.id,
            version=policy.version,
            mode=policy.mode,
            approved_providers=sorted(
                policy.approved_providers, key=lambda provider: provider.value
            ),
            changed_by=policy.changed_by,
            created_at=policy.created_at,
        )


class WorkspaceDataPolicyResponse(BaseModel):
    policy_id: UUID
    version_id: UUID
    workspace_id: UUID
    version: int
    mode: WorkspaceOutboundMode
    approved_providers: list[ProviderKind]
    changed_by: UUID
    created_at: datetime

    @classmethod
    def from_domain(cls, policy: WorkspaceDataPolicyVersion) -> Self:
        return cls(
            policy_id=policy.policy_id,
            version_id=policy.id,
            workspace_id=policy.workspace_id,
            version=policy.version,
            mode=policy.mode,
            approved_providers=sorted(
                policy.approved_providers, key=lambda provider: provider.value
            ),
            changed_by=policy.changed_by,
            created_at=policy.created_at,
        )
