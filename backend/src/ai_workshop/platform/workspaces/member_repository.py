"""Workspace membership authority; all mutations and audits share one transaction."""

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import (
    MembershipRole,
    WorkspaceCapabilities,
    WorkspaceGrants,
    WorkspaceKind,
    WorkspaceMember,
)
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspacePermissionAuditRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.permissions import (
    lock_workspace_memberships,
    not_found,
    workspace_read_allowed,
)
from ai_workshop.shared.errors import AppError


def _member(record: WorkspaceMembershipRecord, user: UserRecord) -> WorkspaceMember:
    owner = record.role == MembershipRole.OWNER
    return WorkspaceMember(
        user.id,
        user.display_name,
        MembershipRole(record.role),
        user.is_active,
        owner or record.can_read,
        owner or record.can_write,
        owner or record.can_delete,
        record.permission_revision,
    )


class SqlAlchemyWorkspaceMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def capabilities(self, actor_id: UUID, workspace_id: UUID) -> WorkspaceCapabilities:
        row = (
            await self.session.execute(
                select(WorkspaceRecord, WorkspaceMembershipRecord)
                .join(
                    WorkspaceMembershipRecord,
                    WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                )
                .where(
                    WorkspaceRecord.id == workspace_id,
                    WorkspaceMembershipRecord.user_id == actor_id,
                    workspace_read_allowed(actor_id),
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise not_found()
        workspace, member = row
        owner = member.role == MembershipRole.OWNER
        personal = workspace.kind == WorkspaceKind.PERSONAL
        legacy_write = workspace.kind in (WorkspaceKind.TEAM, WorkspaceKind.TEMPORARY)
        return WorkspaceCapabilities(
            True,
            owner or personal or legacy_write or member.can_write,
            owner or personal or (workspace.kind == WorkspaceKind.COMPANY and member.can_delete),
            workspace.kind == WorkspaceKind.COMPANY and owner,
        )

    async def _require_owner(self, actor_id: UUID, workspace_id: UUID) -> None:
        capability = await self.capabilities(actor_id, workspace_id)
        if not capability.manage_members:
            raise not_found()

    async def list_members(
        self, actor_id: UUID, workspace_id: UUID, *, after: UUID | None, limit: int
    ) -> tuple[tuple[WorkspaceMember, ...], UUID | None]:
        await self._require_owner(actor_id, workspace_id)
        query = (
            select(WorkspaceMembershipRecord, UserRecord)
            .join(UserRecord, UserRecord.id == WorkspaceMembershipRecord.user_id)
            .where(WorkspaceMembershipRecord.workspace_id == workspace_id)
        )
        if after is not None:
            query = query.where(WorkspaceMembershipRecord.user_id > after)
        rows = (
            await self.session.execute(
                query.order_by(WorkspaceMembershipRecord.user_id).limit(limit + 1)
            )
        ).all()
        items = tuple(_member(member, user) for member, user in rows[:limit])
        return items, items[-1].user_id if len(rows) > limit else None

    async def put_member(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        target_id: UUID,
        *,
        grants: WorkspaceGrants,
        expected_revision: int,
    ) -> WorkspaceMember:
        # Read authorization first to avoid allowing arbitrary callers to hold workspace locks.
        await self._require_owner(actor_id, workspace_id)
        await lock_workspace_memberships(self.session, workspace_id, (actor_id, target_id))
        await self._require_owner(actor_id, workspace_id)
        target = await self.session.scalar(
            select(UserRecord)
            .where(UserRecord.id == target_id, UserRecord.is_active.is_(True))
            .execution_options(populate_existing=True)
        )
        if target is None:
            raise not_found()
        member = await self.session.scalar(
            select(WorkspaceMembershipRecord)
            .where(
                WorkspaceMembershipRecord.workspace_id == workspace_id,
                WorkspaceMembershipRecord.user_id == target_id,
            )
            .execution_options(populate_existing=True)
        )
        if member is not None and member.role == MembershipRole.OWNER:
            raise not_found()
        revision = member.permission_revision if member is not None else 0
        if isinstance(expected_revision, bool) or expected_revision < 0:
            raise AppError("invalid_revision", "The permission revision is invalid.", 422)
        if expected_revision != revision:
            raise AppError(
                "workspace_permission_conflict", "Workspace permissions have changed.", 409
            )
        before = (
            None
            if member is None
            else {
                "read": member.can_read,
                "write": member.can_write,
                "delete": member.can_delete,
            }
        )
        if member is None:
            member = WorkspaceMembershipRecord(
                workspace_id=workspace_id, user_id=target_id, role=MembershipRole.MEMBER
            )
            self.session.add(member)
        member.can_read, member.can_write, member.can_delete = (
            grants.read,
            grants.write,
            grants.delete,
        )
        member.permission_revision = revision + 1
        self.session.add(
            WorkspacePermissionAuditRecord(
                workspace_id=workspace_id,
                actor_id=actor_id,
                target_id=target_id,
                before_permissions=before,
                after_permissions=asdict(grants),
                permission_revision=revision + 1,
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return _member(member, target)
