"""Current SQL authorization and the workspace → membership transaction lock order."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError


def workspace_read_allowed(actor_id: UUID) -> ColumnElement[bool]:
    """DB authority, independent of indexed ACLs and of the caller's membership joins."""
    member = aliased(WorkspaceMembershipRecord)
    return and_(
        or_(WorkspaceRecord.kind != WorkspaceKind.PERSONAL, WorkspaceRecord.created_by == actor_id),
        or_(
            WorkspaceRecord.kind != WorkspaceKind.TEMPORARY,
            and_(
                WorkspaceRecord.expires_at.is_not(None),
                WorkspaceRecord.expires_at > datetime.now(UTC),
            ),
        ),
        select(member.id)
        .join(UserRecord, UserRecord.id == member.user_id)
        .where(
            member.workspace_id == WorkspaceRecord.id,
            member.user_id == actor_id,
            UserRecord.is_active.is_(True),
            or_(
                WorkspaceRecord.kind != WorkspaceKind.COMPANY,
                member.role == MembershipRole.OWNER,
                member.can_read.is_(True),
            ),
        )
        .correlate(WorkspaceRecord)
        .exists(),
    )


def workspace_write_allowed(actor_id: UUID) -> ColumnElement[bool]:
    member = aliased(WorkspaceMembershipRecord)
    return and_(
        workspace_read_allowed(actor_id),
        or_(
            WorkspaceRecord.kind != WorkspaceKind.COMPANY,
            select(member.id)
            .where(
                member.workspace_id == WorkspaceRecord.id,
                member.user_id == actor_id,
                or_(member.role == MembershipRole.OWNER, member.can_write.is_(True)),
            )
            .correlate(WorkspaceRecord)
            .exists(),
        ),
    )


def workspace_delete_allowed(actor_id: UUID) -> ColumnElement[bool]:
    member = aliased(WorkspaceMembershipRecord)
    return and_(
        workspace_read_allowed(actor_id),
        select(member.id)
        .where(
            member.workspace_id == WorkspaceRecord.id,
            member.user_id == actor_id,
            or_(
                member.role == MembershipRole.OWNER,
                WorkspaceRecord.kind == WorkspaceKind.PERSONAL,
                and_(
                    WorkspaceRecord.kind == WorkspaceKind.COMPANY,
                    member.can_delete.is_(True),
                ),
            ),
        )
        .correlate(WorkspaceRecord)
        .exists(),
    )


def not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


async def lock_workspace_memberships(
    session: AsyncSession, workspace_id: UUID, actor_ids: tuple[UUID, ...]
) -> None:
    # Acquire workspace first, then membership in stable order. Fresh SQL predicates
    # below prevent an identity-map snapshot from granting a revoked permission.
    await session.scalar(
        select(WorkspaceRecord.id).where(WorkspaceRecord.id == workspace_id).with_for_update()
    )
    await session.scalars(
        select(WorkspaceMembershipRecord.id)
        .where(
            WorkspaceMembershipRecord.workspace_id == workspace_id,
            WorkspaceMembershipRecord.user_id.in_(actor_ids),
        )
        .order_by(WorkspaceMembershipRecord.user_id)
        .with_for_update()
    )


async def require_workspace_write(
    session: AsyncSession, actor_id: UUID, workspace_id: UUID, *, lock: bool = False
) -> None:
    if lock:
        await lock_workspace_memberships(session, workspace_id, (actor_id,))
    found = await session.scalar(
        select(WorkspaceRecord.id).where(
            WorkspaceRecord.id == workspace_id, workspace_write_allowed(actor_id)
        )
    )
    if found is None:
        raise not_found()


async def require_workspace_delete(
    session: AsyncSession, actor_id: UUID, workspace_id: UUID, *, lock: bool = False
) -> None:
    if lock:
        found = await session.scalar(
            select(WorkspaceRecord.id).where(
                WorkspaceRecord.id == workspace_id, workspace_delete_allowed(actor_id)
            )
        )
        if found is None:
            raise not_found()
        await lock_workspace_memberships(session, workspace_id, (actor_id,))
    found = await session.scalar(
        select(WorkspaceRecord.id).where(
            WorkspaceRecord.id == workspace_id, workspace_delete_allowed(actor_id)
        )
    )
    if found is None:
        raise not_found()
