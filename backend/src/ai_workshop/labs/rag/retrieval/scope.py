from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.labs.rag.retrieval.domain import (
    ResolvedSearchScope,
    SelectedDocumentIdentity,
)
from ai_workshop.labs.rag.retrieval.selection import (
    normalize_document_ids,
    selected_scope_fingerprint,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import (
    AssetVersionRecord,
    DocumentRecord,
    FolderRecord,
)
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
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

    async def find_document_locations(
        self,
        document_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, UUID, UUID | None], ...]: ...

    async def find_searchable_lifecycle(
        self,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
    ) -> tuple[SelectedDocumentIdentity, ...]: ...


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
                .where(WorkspaceRecord.id.in_(workspace_ids), workspace_read_allowed(actor_id))
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

    async def find_document_locations(
        self,
        document_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, UUID, UUID | None], ...]:
        if not document_ids:
            return ()
        rows = (
            await self.session.execute(
                select(
                    DocumentRecord.id,
                    DocumentRecord.workspace_id,
                    DocumentRecord.folder_id,
                ).where(DocumentRecord.id.in_(document_ids))
            )
        ).all()
        by_id = {
            document_id: (workspace_id, folder_id) for document_id, workspace_id, folder_id in rows
        }
        return tuple((item, *by_id[item]) for item in document_ids if item in by_id)

    async def find_searchable_lifecycle(
        self,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
    ) -> tuple[SelectedDocumentIdentity, ...]:
        if not workspace_ids:
            return ()
        statement = (
            select(
                DocumentRecord.id,
                AssetVersionRecord.id,
                RagProjectionRecord.id,
                RagIndexBuildRecord.id,
            )
            .join(
                DocumentRecord,
                DocumentRecord.id == AssetVersionRecord.document_id,
            )
            .join(
                RagProjectionRecord,
                RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
            )
            .join(
                RagIndexBuildRecord,
                RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
            )
            .where(
                DocumentRecord.workspace_id.in_(workspace_ids),
                DocumentRecord.active_version_id == AssetVersionRecord.id,
                AssetVersionRecord.status == VersionStatus.READY,
                RagProjectionRecord.indexing_profile_id == indexing_profile_id,
                RagProjectionRecord.status == ProjectionStatus.READY,
                RagIndexBuildRecord.indexing_profile_id == indexing_profile_id,
                RagIndexBuildRecord.status == "ready",
                RagIndexBuildRecord.is_active.is_(True),
            )
            .order_by(AssetVersionRecord.id, RagIndexBuildRecord.id)
        )
        if folder_ids:
            statement = statement.where(DocumentRecord.folder_id.in_(folder_ids))
        if document_ids is not None:
            statement = statement.where(DocumentRecord.id.in_(document_ids))
        if document_processing_profile_id is not None:
            statement = statement.where(
                RagProjectionRecord.document_processing_profile_id
                == document_processing_profile_id,
                RagIndexBuildRecord.document_processing_profile_id
                == document_processing_profile_id,
            )
        return tuple(
            SelectedDocumentIdentity(document_id, asset_id, projection_id, build_id)
            for document_id, asset_id, projection_id, build_id in (
                await self.session.execute(statement)
            ).all()
        )


class SearchScopeResolver:
    def __init__(
        self,
        repository: SearchScopeRepository,
        *,
        now: Callable[[], datetime] | None = None,
        selected_documents_max_count: int = 100,
    ) -> None:
        self.repository = repository
        self.now = now or (lambda: datetime.now(UTC))
        self.selected_documents_max_count = selected_documents_max_count

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
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

        folder_workspaces = dict(await self.repository.find_folder_workspaces(requested_folders))
        authorized_workspaces = frozenset(requested_workspaces)
        if any(
            folder_id not in folder_workspaces
            or folder_workspaces[folder_id] not in authorized_workspaces
            for folder_id in requested_folders
        ):
            self._raise_not_found()

        selected_document_ids = normalize_document_ids(
            document_ids,
            max_count=self.selected_documents_max_count,
        )
        if selected_document_ids is not None:
            locations = {
                document_id: (workspace_id, folder_id)
                for document_id, workspace_id, folder_id in (
                    await self.repository.find_document_locations(selected_document_ids)
                )
            }
            if any(
                document_id not in locations
                or locations[document_id][0] not in authorized_workspaces
                or (requested_folders and locations[document_id][1] not in requested_folders)
                for document_id in selected_document_ids
            ):
                self._raise_not_found()
            if document_processing_profile_id is None:
                raise AppError(
                    "document_processing_profile_missing",
                    "The selected configuration has no document processing profile.",
                    409,
                )

        lifecycle = await self.repository.find_searchable_lifecycle(
            requested_workspaces,
            requested_folders,
            indexing_profile_id,
            selected_document_ids,
            document_processing_profile_id,
        )
        identities = tuple(sorted(lifecycle, key=lambda item: str(item.document_id)))
        if selected_document_ids is not None and (
            tuple(item.document_id for item in identities) != selected_document_ids
        ):
            raise AppError(
                "selected_documents_not_ready",
                "One or more selected documents are not ready for search.",
                409,
            )
        return ResolvedSearchScope(
            requested_workspaces,
            requested_folders,
            asset_version_ids=tuple(
                dict.fromkeys(identity.asset_version_id for identity in identities)
            ),
            index_build_ids=tuple(
                dict.fromkeys(identity.index_build_id for identity in identities)
            ),
            document_ids=selected_document_ids,
            selected_documents=(identities if selected_document_ids is not None else ()),
            scope_fingerprint=(
                selected_scope_fingerprint(identities)
                if selected_document_ids is not None
                else None
            ),
        )

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
