from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    kind: WorkspaceKind
    expires_at: datetime | None = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    kind: WorkspaceKind
    expires_at: datetime | None

    @classmethod
    def from_domain(cls, workspace: Workspace) -> "WorkspaceResponse":
        return cls(
            id=workspace.id,
            name=workspace.name,
            kind=workspace.kind,
            expires_at=workspace.expires_at,
        )
