from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.workspaces.models import WorkspaceRecord

RAG_DOCUMENT_SQL_PARTICIPANT = "rag_document_sql"
RAG_PROJECTION_BUNDLE_KIND = "projection_bundle"
RAG_DERIVED_ARTIFACT_RELATION = "derived_artifact"


class RagProvenanceConflictError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def _lock_projection(
    session: AsyncSession,
    projection_id: UUID,
) -> RagProjectionRecord:
    record = await session.scalar(
        select(RagProjectionRecord)
        .where(RagProjectionRecord.id == projection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise LookupError("RAG document projection does not exist.")
    return record


async def _source_identity(
    session: AsyncSession,
    asset_version_id: UUID,
) -> SourceIdentity:
    row = (
        await session.execute(
            select(
                WorkspaceRecord.id,
                DocumentRecord.id,
                AssetVersionRecord.id,
            )
            .join(
                DocumentRecord,
                DocumentRecord.workspace_id == WorkspaceRecord.id,
            )
            .join(
                AssetVersionRecord,
                AssetVersionRecord.document_id == DocumentRecord.id,
            )
            .where(AssetVersionRecord.id == asset_version_id)
        )
    ).one_or_none()
    if row is None:
        raise RagProvenanceConflictError("rag_projection_source_missing")
    return SourceIdentity(row[0], row[1], row[2])


def _relation(
    projection: RagProjectionRecord,
    source: SourceIdentity,
    revision: int,
) -> SourceRelation:
    return SourceRelation(
        source=source,
        resource=ResourceIdentity(
            participant=RAG_DOCUMENT_SQL_PARTICIPANT,
            kind=RAG_PROJECTION_BUNDLE_KIND,
            resource_id=projection.id,
            revision=revision,
        ),
        relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
    )


async def _register_projection(
    session: AsyncSession,
    projection: RagProjectionRecord,
) -> None:
    if projection.content_revision is None:
        return
    source = await _source_identity(session, projection.asset_version_id)
    await ProvenanceRepository(session).register(
        _relation(projection, source, projection.content_revision)
    )


async def _advance_projection_revision(
    session: AsyncSession,
    projection: RagProjectionRecord,
) -> None:
    current_revision = projection.content_revision
    if current_revision is None:
        return
    next_revision = current_revision + 1
    source = await _source_identity(session, projection.asset_version_id)
    await ProvenanceRepository(session).replace_current(
        _relation(projection, source, current_revision),
        _relation(projection, source, next_revision),
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(RagProjectionRecord)
            .where(
                RagProjectionRecord.id == projection.id,
                RagProjectionRecord.content_revision == current_revision,
            )
            .values(content_revision=next_revision)
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        raise RagProvenanceConflictError("rag_projection_revision_conflict")
    await session.refresh(projection, attribute_names=["content_revision"])
