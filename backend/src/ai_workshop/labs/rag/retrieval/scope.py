from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope
from ai_workshop.platform.assets.models import FolderRecord
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    workspace: Workspace
    is_member: bool


class SearchScopeRepository(Protocol):
    async def find_workspace_access(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[WorkspaceAccess, ...]: ...

    async def find_folder_workspaces(
        self,
        folder_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, UUID], ...]: ...


class SqlAlchemySearchScopeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_workspace_access(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[WorkspaceAccess, ...]:
        if not workspace_ids:
            return ()
        membership_join = and_(
            WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
            WorkspaceMembershipRecord.user_id == actor_id,
        )
        rows = (
            await self.session.execute(
                select(WorkspaceRecord, WorkspaceMembershipRecord.id)
                .outerjoin(WorkspaceMembershipRecord, membership_join)
                .where(WorkspaceRecord.id.in_(workspace_ids))
            )
        ).all()
        by_id = {
            record.id: WorkspaceAccess(
                Workspace(
                    record.id,
                    record.name,
                    WorkspaceKind(record.kind),
                    record.created_by,
                    record.expires_at,
                ),
                membership_id is not None,
            )
            for record, membership_id in rows
        }
        return tuple(by_id[item] for item in workspace_ids if item in by_id)

    async def find_folder_workspaces(
        self,
        folder_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, UUID], ...]:
        if not folder_ids:
            return ()
        rows = (
            await self.session.execute(
                select(FolderRecord.id, FolderRecord.workspace_id).where(
                    FolderRecord.id.in_(folder_ids)
                )
            )
        ).all()
        by_id = {folder_id: workspace_id for folder_id, workspace_id in rows}
        return tuple((item, by_id[item]) for item in folder_ids if item in by_id)


class SearchScopeResolver:
    def __init__(
        self,
        repository: SearchScopeRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now = now or (lambda: datetime.now(UTC))

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        requested_workspaces = tuple(dict.fromkeys(workspace_ids))
        requested_folders = tuple(dict.fromkeys(folder_ids))
        if not requested_workspaces:
            raise AppError(
                "search_scope_empty",
                "At least one authorized workspace is required.",
                422,
            )

        access = await self.repository.find_workspace_access(actor_id, requested_workspaces)
        access_by_id = {item.workspace.id: item for item in access}
        if any(
            workspace_id not in access_by_id
            or not self._is_authorized(access_by_id[workspace_id], actor_id)
            for workspace_id in requested_workspaces
        ):
            self._raise_not_found()

        folder_workspaces = dict(
            await self.repository.find_folder_workspaces(requested_folders)
        )
        authorized_workspaces = frozenset(requested_workspaces)
        if any(
            folder_id not in folder_workspaces
            or folder_workspaces[folder_id] not in authorized_workspaces
            for folder_id in requested_folders
        ):
            self._raise_not_found()

        return ResolvedSearchScope(requested_workspaces, requested_folders)

    def _is_authorized(self, access: WorkspaceAccess, actor_id: UUID) -> bool:
        workspace = access.workspace
        if not access.is_member:
            return False
        if workspace.kind is WorkspaceKind.PERSONAL:
            return workspace.created_by == actor_id
        if workspace.kind is WorkspaceKind.TEMPORARY:
            return workspace.expires_at is not None and workspace.expires_at > self.now()
        return True

    @staticmethod
    def _raise_not_found() -> None:
        raise AppError("not_found", "The requested resource was not found.", 404)
