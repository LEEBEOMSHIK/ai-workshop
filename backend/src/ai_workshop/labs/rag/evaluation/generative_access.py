"""Current read access to exact historical READY inputs, independent of activation."""

from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.retrieval.domain import SelectedDocumentIdentity
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.shared.errors import AppError


class FrozenEvaluationAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def validate(
        self,
        actor_id: UUID,
        identities: tuple[SelectedDocumentIdentity, ...],
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        configuration: ResolvedSearchConfiguration,
    ) -> None:
        expected = {
            (i.document_id, i.asset_version_id, i.projection_id, i.index_build_id)
            for i in identities
        }
        if not expected:
            return
        statement = (
            select(
                DocumentRecord.id,
                AssetVersionRecord.id,
                RagProjectionRecord.id,
                RagIndexBuildRecord.id,
            )
            .select_from(DocumentRecord)
            .join(
                WorkspaceRecord,
                WorkspaceRecord.id == DocumentRecord.workspace_id,
            )
            .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
            .join(
                RagProjectionRecord,
                RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
            )
            .join(RagIndexBuildRecord, RagIndexBuildRecord.projection_id == RagProjectionRecord.id)
            .where(
                tuple_(
                    DocumentRecord.id,
                    AssetVersionRecord.id,
                    RagProjectionRecord.id,
                    RagIndexBuildRecord.id,
                ).in_(expected),
                DocumentRecord.lifecycle == "active",
                DocumentRecord.workspace_id.in_(workspace_ids),
                workspace_read_allowed(actor_id),
                AssetVersionRecord.status == "ready",
                RagProjectionRecord.status == "ready",
                RagIndexBuildRecord.status == "ready",
                RagProjectionRecord.indexing_profile_id == configuration.indexing_profile_id,
                RagIndexBuildRecord.indexing_profile_id == configuration.indexing_profile_id,
            )
        )
        if folder_ids:
            statement = statement.where(DocumentRecord.folder_id.in_(folder_ids))
        if configuration.document_processing_profile_id is not None:
            statement = statement.where(
                RagProjectionRecord.document_processing_profile_id
                == configuration.document_processing_profile_id,
                RagIndexBuildRecord.document_processing_profile_id
                == configuration.document_processing_profile_id,
            )
        actual = {tuple(row) for row in (await self.session.execute(statement)).all()}
        if actual != expected:
            raise AppError("not_found", "The frozen sources are no longer available.", 404)
