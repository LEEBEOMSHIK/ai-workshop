from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.search.viewer import ViewerResource
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.repository import workspace_is_active


class SqlAlchemyViewerResourceAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
    ) -> ViewerResource | None:
        membership_join = and_(
            WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
            WorkspaceMembershipRecord.user_id == actor_id,
        )
        row = (
            await self.session.execute(
                select(
                    AssetVersionRecord,
                    DocumentRecord,
                    RagProjectionRecord,
                    RagIngestionJobRecord,
                )
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                .join(WorkspaceMembershipRecord, membership_join)
                .join(
                    RagProjectionRecord,
                    RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                )
                .join(
                    RagIngestionJobRecord,
                    RagIngestionJobRecord.projection_id == RagProjectionRecord.id,
                )
                .where(
                    AssetVersionRecord.id == asset_version_id,
                    RagProjectionRecord.id == projection_id,
                    AssetVersionRecord.status == VersionStatus.READY,
                    DocumentRecord.active_version_id == AssetVersionRecord.id,
                    RagProjectionRecord.status == "ready",
                    RagIngestionJobRecord.parsed_object_key.is_not(None),
                    RagIngestionJobRecord.parsed_sha256.is_not(None),
                    RagIngestionJobRecord.index_alias_verified.is_(True),
                    workspace_is_active(),
                    or_(
                        WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                        WorkspaceRecord.created_by == actor_id,
                    ),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        version, document, projection, ingestion = row
        if ingestion.parsed_object_key is None or ingestion.parsed_sha256 is None:
            return None
        return ViewerResource(
            document_id=document.id,
            asset_version_id=version.id,
            asset_version_number=version.number,
            workspace_id=document.workspace_id,
            folder_id=document.folder_id,
            projection_id=projection.id,
            title=document.name,
            media_type=version.media_type,
            original_object_key=version.object_key,
            original_size=version.size,
            original_sha256=version.sha256,
            parsed_object_key=ingestion.parsed_object_key,
            parsed_sha256=ingestion.parsed_sha256,
        )
