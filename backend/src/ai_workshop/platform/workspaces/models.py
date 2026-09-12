from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[WorkspaceKind] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class _MembershipDefaultContext(Protocol):
    def get_current_parameters(self) -> dict[str, object]: ...


def _owner_grant(context: _MembershipDefaultContext) -> bool:
    return context.get_current_parameters().get("role") == MembershipRole.OWNER


class WorkspaceMembershipRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint(
            "can_read OR (NOT can_write AND NOT can_delete)", name="ck_workspace_grants_read"
        ),
        CheckConstraint("permission_revision >= 1", name="ck_workspace_permission_revision"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[MembershipRole] = mapped_column(String(32), nullable=False)
    can_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    can_write: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=_owner_grant, server_default=false()
    )
    can_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=_owner_grant, server_default=false()
    )
    permission_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class WorkspacePermissionAuditRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workspace_permission_audits"
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    target_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    before_permissions: Mapped[dict[str, bool] | None] = mapped_column(JSON)
    after_permissions: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)
    permission_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
