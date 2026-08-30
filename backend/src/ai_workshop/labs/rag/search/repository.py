from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.retrieval.domain import FusedHit, RetrievedChunk
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.repository import workspace_is_active


def _bbox(value: list[float] | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if len(value) != 4:
        raise ValueError("Authoritative evidence bounding boxes require four values.")
    return value[0], value[1], value[2], value[3]


class SqlAlchemySearchSourceResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        usable_hits = tuple(
            hit for hit in hits if isinstance(hit.chunk_id, UUID) and hit.chunk is not None
        )
        if not usable_hits:
            return ()
        chunk_ids = tuple(hit.chunk_id for hit in usable_hits)
        membership_join = and_(
            WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
            WorkspaceMembershipRecord.user_id == actor_id,
        )
        rows = (
            await self.session.execute(
                select(
                    RetrievalChunkRecord,
                    RagProjectionRecord,
                    RagIndexBuildRecord,
                    AssetVersionRecord,
                    DocumentRecord,
                )
                .join(
                    RagProjectionRecord,
                    RagProjectionRecord.id == RetrievalChunkRecord.projection_id,
                )
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                )
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                .join(WorkspaceMembershipRecord, membership_join)
                .join(
                    RagIndexBuildRecord,
                    RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                )
                .where(
                    RetrievalChunkRecord.id.in_(chunk_ids),
                    RagProjectionRecord.indexing_profile_id == indexing_profile_id,
                    RagProjectionRecord.status == "ready",
                    AssetVersionRecord.status == VersionStatus.READY,
                    DocumentRecord.active_version_id == AssetVersionRecord.id,
                    workspace_is_active(),
                    or_(
                        WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                        WorkspaceRecord.created_by == actor_id,
                    ),
                    RagIndexBuildRecord.indexing_profile_id == indexing_profile_id,
                    RagIndexBuildRecord.status == "ready",
                    RagIndexBuildRecord.is_active.is_(True),
                )
            )
        ).all()
        row_by_chunk = {row[0].id: row for row in rows}
        authoritative_chunk_ids = tuple(row_by_chunk)
        evidence_by_chunk: dict[UUID, list[EvidenceUnit]] = {
            chunk_id: [] for chunk_id in authoritative_chunk_ids
        }
        if authoritative_chunk_ids:
            evidence_rows = (
                await self.session.execute(
                    select(EvidenceUnitRecord)
                    .where(EvidenceUnitRecord.retrieval_chunk_id.in_(authoritative_chunk_ids))
                    .order_by(
                        EvidenceUnitRecord.retrieval_chunk_id,
                        EvidenceUnitRecord.ordinal,
                    )
                )
            ).scalars()
            for evidence in evidence_rows:
                evidence_by_chunk[evidence.retrieval_chunk_id].append(
                    EvidenceUnit(
                        id=evidence.id,
                        chunk_id=evidence.retrieval_chunk_id,
                        projection_id=evidence.projection_id,
                        ordinal=evidence.ordinal,
                        text=evidence.text,
                        location=SourceLocation(
                            element_id=evidence.element_id,
                            page=evidence.page,
                            char_start=evidence.char_start,
                            char_end=evidence.char_end,
                            bbox=_bbox(evidence.bbox),
                        ),
                    )
                )

        sources: list[EvidenceSource] = []
        for hit in usable_hits:
            row = row_by_chunk.get(hit.chunk_id)
            if row is None or hit.chunk is None:
                continue
            chunk, projection, build, version, document = row
            if hit.chunk.index_build_id != build.id:
                continue
            sources.append(
                EvidenceSource(
                    document_id=document.id,
                    asset_version_number=version.number,
                    media_type=version.media_type,
                    chunk=RetrievedChunk(
                        chunk_id=chunk.id,
                        projection_id=projection.id,
                        asset_version_id=version.id,
                        workspace_id=document.workspace_id,
                        folder_id=document.folder_id,
                        index_build_id=build.id,
                        title=document.name,
                        section_path=tuple(chunk.section_path),
                        text=chunk.text,
                        evidence_units=tuple(evidence_by_chunk[chunk.id]),
                    ),
                    fused_score=hit.score,
                )
            )
        return tuple(sources)
