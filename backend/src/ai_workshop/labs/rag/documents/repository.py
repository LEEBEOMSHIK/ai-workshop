from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    ProjectionStatus,
    RagProjection,
    RetrievalChunk,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)


class RagDocumentRepository(Protocol):
    async def add_projection(self, projection: RagProjection) -> RagProjection: ...

    async def find_projection(
        self,
        *,
        asset_version_id: UUID,
        indexing_profile_id: UUID,
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
    )


class SqlAlchemyRagDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_projection(self, projection: RagProjection) -> RagProjection:
        if projection.status is not ProjectionStatus.PENDING:
            raise ValueError("New RAG document projections must start pending.")
        self.session.add(
            RagProjectionRecord(
                id=projection.id,
                asset_version_id=projection.asset_version_id,
                indexing_profile_id=projection.indexing_profile_id,
                status=projection.status,
            )
        )
        await self.session.flush()
        return projection

    async def find_projection(
        self,
        *,
        asset_version_id: UUID,
        indexing_profile_id: UUID,
    ) -> RagProjection | None:
        result = await self.session.execute(
            select(RagProjectionRecord).where(
                RagProjectionRecord.asset_version_id == asset_version_id,
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
        projection = await self.session.get(RagProjectionRecord, projection_id)
        if projection is None:
            raise LookupError("RAG document projection does not exist.")
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
                )
                for element in document.elements
            ]
        )
        await self.session.flush()

    async def replace_chunks(
        self,
        projection_id: UUID,
        chunks: tuple[RetrievalChunk, ...],
    ) -> None:
        element_ids = {
            evidence.location.element_id
            for chunk in chunks
            for evidence in chunk.evidence_units
        }
        for chunk in chunks:
            if chunk.projection_id != projection_id:
                raise ValueError("A retrieval chunk must belong to the projection being replaced.")
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
                if evidence.chunk_id is not None and evidence.chunk_id != chunk.id:
                    raise ValueError(
                        "An evidence unit must belong to its containing retrieval chunk."
                    )
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
                    )
                )
        await self.session.flush()
        self.session.add_all(evidence_records)
        await self.session.flush()

    async def mark_status(
        self,
        projection_id: UUID,
        status: ProjectionStatus,
    ) -> RagProjection:
        record = await self.session.get(RagProjectionRecord, projection_id)
        if record is None:
            raise LookupError("RAG document projection does not exist.")
        projection = _projection_to_domain(record).transition(status)
        record.status = projection.status
        await self.session.flush()
        return projection
