from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ai_workshop.platform.workspaces.domain import MembershipRole, Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord


class WorkspaceRepository(Protocol):
    async def list_for_user(self, user_id: UUID) -> list[Workspace]: ...
    async def has_personal(self, user_id: UUID) -> bool: ...
    async def add(self, workspace: Workspace, owner_id: UUID) -> Workspace: ...


def _to_domain(record: WorkspaceRecord) -> Workspace:
    return Workspace(record.id, record.name, record.kind, record.created_by, record.expires_at)


def workspace_is_active() -> ColumnElement[bool]:
    now = datetime.now(UTC)
    return or_(
        WorkspaceRecord.kind != WorkspaceKind.TEMPORARY,
        and_(WorkspaceRecord.expires_at.is_not(None), WorkspaceRecord.expires_at > now),
    )


class SqlAlchemyWorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[Workspace]:
        result = await self.session.execute(
            select(WorkspaceRecord)
            .join(WorkspaceMembershipRecord)
            .where(
                WorkspaceMembershipRecord.user_id == user_id,
                workspace_is_active(),
            )
            .order_by(WorkspaceRecord.name)
        )
        return [_to_domain(record) for record in result.scalars()]

    async def has_personal(self, user_id: UUID) -> bool:
        result = await self.session.execute(
            select(WorkspaceRecord.id)
            .join(WorkspaceMembershipRecord)
            .where(
                WorkspaceMembershipRecord.user_id == user_id,
                WorkspaceRecord.kind == WorkspaceKind.PERSONAL,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def add(self, workspace: Workspace, owner_id: UUID) -> Workspace:
        record = WorkspaceRecord(
            id=workspace.id,
            name=workspace.name,
            kind=workspace.kind,
            created_by=workspace.created_by,
            expires_at=workspace.expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            WorkspaceMembershipRecord(
                workspace_id=workspace.id, user_id=owner_id, role=MembershipRole.OWNER
            )
        )
        await self.session.flush()
        return _to_domain(record)
