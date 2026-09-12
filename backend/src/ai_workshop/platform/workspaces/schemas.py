from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ai_workshop.platform.workspaces.domain import MembershipRole, Workspace, WorkspaceKind


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


class WorkspaceCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    read: bool
    write: bool
    delete: bool
    manage_members: bool


class WorkspaceMemberPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: StrictBool
    write: StrictBool
    delete: StrictBool
    expected_revision: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_grants(self) -> "WorkspaceMemberPut":
        if not self.read and (self.write or self.delete):
            raise ValueError("Write and delete require read permission.")
        return self


class WorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    display_name: str
    role: MembershipRole
    is_active: bool
    read: bool
    write: bool
    delete: bool
    permission_revision: int


class WorkspaceMemberPage(BaseModel):
    items: list[WorkspaceMemberResponse]
    next_after: UUID | None = None
