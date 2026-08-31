from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord


@dataclass(frozen=True, slots=True)
class LockedIngestionSource:
    asset: AssetVersionRecord
    document: DocumentRecord


async def lock_ingestion_source(
    session: AsyncSession,
    asset_version_id: UUID,
    *,
    require_active: bool = True,
) -> LockedIngestionSource:
    """Lock the exact Asset Version before its Document and then recheck activity."""
    asset = await session.scalar(
        select(AssetVersionRecord)
        .where(AssetVersionRecord.id == asset_version_id)
        .with_for_update()
    )
    if asset is None:
        raise RagIngestionError(
            "ingestion_dependency_missing",
            "The durable RAG ingestion source Asset Version is missing.",
            retryable=False,
        )
    document = await session.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.id == asset.document_id)
        .with_for_update()
    )
    if document is None:
        raise RagIngestionError(
            "ingestion_dependency_missing",
            "The durable RAG ingestion source Document is missing.",
            retryable=False,
        )
    if require_active and (
        VersionStatus(asset.status) is not VersionStatus.READY
        or document.active_version_id != asset.id
    ):
        raise RagIngestionError(
            "index_source_inactive",
            "RAG ingestion requires the Document's exact active READY Asset Version.",
            retryable=False,
        )
    return LockedIngestionSource(asset, document)
