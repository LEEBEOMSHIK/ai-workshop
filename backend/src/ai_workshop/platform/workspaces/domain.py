from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ai_workshop.platform.identity.domain import User, UserRole


class WorkspaceKind(StrEnum):
    COMPANY = "company"
    TEAM = "team"
    PERSONAL = "personal"
    TEMPORARY = "temporary"


class MembershipRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class WorkspaceGrants:
    read: bool = True
    write: bool = False
    delete: bool = False

    def __post_init__(self) -> None:
        if not self.read and (self.write or self.delete):
            raise ValueError("Write and delete require read permission.")


@dataclass(frozen=True, slots=True)
class WorkspaceCapabilities:
    read: bool
    write: bool
    delete: bool
    manage_members: bool


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    user_id: UUID
    display_name: str
    role: MembershipRole
    is_active: bool
    read: bool
    write: bool
    delete: bool
    permission_revision: int


@dataclass(frozen=True, slots=True)
class Workspace:
    id: UUID
    name: str
    kind: WorkspaceKind
    created_by: UUID
    expires_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        kind: WorkspaceKind,
        creator: User,
        expires_at: datetime | None = None,
    ) -> "Workspace":
        if kind is WorkspaceKind.COMPANY and creator.role is not UserRole.OWNER:
            raise ValueError("Only an owner can create a company workspace.")
        if kind is WorkspaceKind.TEMPORARY:
            if expires_at is None or expires_at <= datetime.now(UTC):
                raise ValueError("A temporary workspace requires a future expiry.")
        elif expires_at is not None:
            raise ValueError("Only a temporary workspace can expire.")
        return cls(uuid4(), name.strip(), kind, creator.id, expires_at)
