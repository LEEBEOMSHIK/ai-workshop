from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    ProjectionStatus,
    RagProjection,
    RetrievalChunk,
    SourceLocation,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.documents.provenance import (
    _advance_projection_revision,
    _lock_projection,
    _register_projection,
)
from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
)


def _table_cell_json(location: SourceLocation) -> dict[str, int] | None:
    cell = location.table_cell
    if cell is None:
        return None
    return {
        "row": cell.row,
        "column": cell.column,
        "row_span": cell.row_span,
        "column_span": cell.column_span,
    }


class RagDocumentRepository(Protocol):
    async def add_projection(self, projection: RagProjection) -> RagProjection: ...

    async def find_projection(
        self,
        *,
        asset_version_id: UUID,
        indexing_profile_id: UUID,
        document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    ) -> RagProjection | None: ...

    async def save_parsed_document(
        self,
        projection_id: UUID,
        document: ParsedDocument,
    ) -> None: ...

    async def replace_chunks(
        self,
        projection_id: UUID,
        chunks: tuple[RetrievalChunk, ...],
    ) -> None: ...

    async def mark_status(
        self,
        projection_id: UUID,
        status: ProjectionStatus,
    ) -> RagProjection: ...


def _projection_to_domain(record: RagProjectionRecord) -> RagProjection:
    return RagProjection(
        id=record.id,
        asset_version_id=record.asset_version_id,
        indexing_profile_id=record.indexing_profile_id,
        status=ProjectionStatus(record.status),
        document_processing_profile_id=record.document_processing_profile_id,
    )


class SqlAlchemyRagDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_projection(self, projection: RagProjection) -> RagProjection:
        if projection.status is not ProjectionStatus.PENDING:
            raise ValueError("New RAG document projections must start pending.")
        record = RagProjectionRecord(
            id=projection.id,
            asset_version_id=projection.asset_version_id,
            document_processing_profile_id=(projection.document_processing_profile_id),
            indexing_profile_id=projection.indexing_profile_id,
            status=projection.status,
            content_revision=1,
        )
        self.session.add(record)
        await self.session.flush()
        await _register_projection(self.session, record)
        return projection

    async def find_projection(
        self,
        *,
        asset_version_id: UUID,
        indexing_profile_id: UUID,
        document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    ) -> RagProjection | None:
        result = await self.session.execute(
            select(RagProjectionRecord).where(
                RagProjectionRecord.asset_version_id == asset_version_id,
                RagProjectionRecord.document_processing_profile_id
                == document_processing_profile_id,
                RagProjectionRecord.indexing_profile_id == indexing_profile_id,
            )
        )
        record = result.scalar_one_or_none()
        return _projection_to_domain(record) if record is not None else None

    async def save_parsed_document(
        self,
        projection_id: UUID,
        document: ParsedDocument,
    ) -> None:
        projection = await _lock_projection(self.session, projection_id)
        if projection.asset_version_id != document.asset_version_id:
            raise ValueError("A parsed document must match the projection asset version.")
        chunk_exists = await self.session.scalar(
            select(RetrievalChunkRecord.id)
            .where(RetrievalChunkRecord.projection_id == projection_id)
            .limit(1)
        )
        if chunk_exists is not None:
            raise ValueError("Parsed elements cannot be replaced after chunks exist.")
        await self.session.execute(
            delete(StructuralElementRecord).where(
                StructuralElementRecord.projection_id == projection_id
            )
        )
        self.session.add_all(
            [
                StructuralElementRecord(
                    id=element.id,
                    projection_id=projection_id,
                    ordinal=element.ordinal,
                    kind=element.kind,
                    text=element.text,
                    section_path=list(element.section_path),
                    page=element.location.page,
                    char_start=element.location.char_start,
                    char_end=element.location.char_end,
                    bbox=list(element.location.bbox) if element.location.bbox is not None else None,
                    parser_name=element.parser_name,
                    parser_version=element.parser_version,
                    confidence=element.confidence,
                    source_kind=element.location.source_kind.value,
                    source_part=element.location.source_part,
                    image_sha256=element.location.image_sha256,
                    table_cell=_table_cell_json(element.location),
                    evidence_eligible=element.evidence_eligible,
                    warnings=list(element.warnings),
                )
                for element in document.elements
            ]
        )
        await self.session.flush()
        await _advance_projection_revision(self.session, projection)

    async def replace_chunks(
        self,
        projection_id: UUID,
        chunks: tuple[RetrievalChunk, ...],
    ) -> None:
        projection = await _lock_projection(self.session, projection_id)
        element_ids = {
            evidence.location.element_id
            for chunk in chunks
            for evidence in chunk.evidence_units
        }
        for chunk in chunks:
            if chunk.projection_id != projection_id:
                raise ValueError("A retrieval chunk must belong to the projection being replaced.")
            for evidence in chunk.evidence_units:
                if evidence.chunk_id is not None and evidence.chunk_id != chunk.id:
                    raise ValueError(
                        "An evidence unit must belong to its containing retrieval chunk."
                    )
        if element_ids:
            result = await self.session.execute(
                select(StructuralElementRecord.id).where(
                    StructuralElementRecord.projection_id == projection_id,
                    StructuralElementRecord.id.in_(element_ids),
                )
            )
            if set(result.scalars()) != element_ids:
                raise ValueError(
                    "Evidence units must reference structural elements in the containing "
                    "projection."
                )
        chunk_ids = select(RetrievalChunkRecord.id).where(
            RetrievalChunkRecord.projection_id == projection_id
        )
        await self.session.execute(
            delete(EvidenceUnitRecord).where(EvidenceUnitRecord.retrieval_chunk_id.in_(chunk_ids))
        )
        await self.session.execute(
            delete(RetrievalChunkRecord).where(RetrievalChunkRecord.projection_id == projection_id)
        )
        evidence_records: list[EvidenceUnitRecord] = []
        for chunk in chunks:
            self.session.add(
                RetrievalChunkRecord(
                    id=chunk.id,
                    projection_id=projection_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    section_path=list(chunk.section_path),
                )
            )
            for evidence in chunk.evidence_units:
                evidence_records.append(
                    EvidenceUnitRecord(
                        id=evidence.id,
                        projection_id=projection_id,
                        retrieval_chunk_id=chunk.id,
                        ordinal=evidence.ordinal,
                        text=evidence.text,
                        element_id=evidence.location.element_id,
                        page=evidence.location.page,
                        char_start=evidence.location.char_start,
                        char_end=evidence.location.char_end,
                        bbox=(
                            list(evidence.location.bbox)
                            if evidence.location.bbox is not None
                            else None
                        ),
                        source_kind=evidence.location.source_kind.value,
                        source_part=evidence.location.source_part,
                        image_sha256=evidence.location.image_sha256,
                        table_cell=_table_cell_json(evidence.location),
                    )
                )
        await self.session.flush()
        self.session.add_all(evidence_records)
        await self.session.flush()
        await _advance_projection_revision(self.session, projection)

    async def mark_status(
        self,
        projection_id: UUID,
        status: ProjectionStatus,
    ) -> RagProjection:
        record = await _lock_projection(self.session, projection_id)
        if ProjectionStatus(record.status) is status:
            return _projection_to_domain(record)
        projection = _projection_to_domain(record).transition(status)
        record.status = projection.status
        await self.session.flush()
        await _advance_projection_revision(self.session, record)
        return projection
