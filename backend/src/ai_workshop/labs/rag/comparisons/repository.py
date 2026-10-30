"""Current SQL authority and immutable comparison storage; no runtime file reads."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.comparisons.models import ComparisonReportRecord
from ai_workshop.labs.rag.comparisons.schemas import ComparisonEvidence, ComparisonImport
from ai_workshop.labs.rag.comparisons.service import StoredComparison, unavailable
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed


def stored(row: ComparisonReportRecord) -> StoredComparison:
    return StoredComparison(
        id=row.id,
        owner_id=row.owner_id,
        source_key=row.source_key,
        source_result_sha256=row.source_result_sha256,
        content_sha256=row.content_sha256,
        payload=row.payload,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def matches_evidence(row: EvidenceUnitRecord, evidence: ComparisonEvidence) -> bool:
    return (
        row.id == evidence.evidence_id
        and row.projection_id == evidence.projection_id
        and row.retrieval_chunk_id == evidence.retrieval_chunk_id
        and row.element_id == evidence.element_id
        and row.ordinal == evidence.ordinal
        and row.text == evidence.text
        and row.page == evidence.page
        and row.char_start == evidence.char_start
        and row.char_end == evidence.char_end
        and row.bbox == evidence.bbox
        and row.source_kind == evidence.source_kind
    )


class SqlComparisonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(self, actor_id: UUID, record_id: UUID) -> StoredComparison | None:
        row = await self.session.scalar(
            select(ComparisonReportRecord)
            .where(
                ComparisonReportRecord.id == record_id,
                ComparisonReportRecord.owner_id == actor_id,
            )
            .execution_options(populate_existing=True)
        )
        return stored(row) if row is not None else None

    async def by_key(self, actor_id: UUID, key: str) -> StoredComparison | None:
        row = await self.session.scalar(
            select(ComparisonReportRecord)
            .where(
                ComparisonReportRecord.source_key == key,
                ComparisonReportRecord.owner_id == actor_id,
            )
            .execution_options(populate_existing=True)
        )
        return stored(row) if row is not None else None

    async def list(self, actor_id: UUID) -> list[StoredComparison]:
        rows = (
            await self.session.scalars(
                select(ComparisonReportRecord)
                .where(
                    ComparisonReportRecord.owner_id == actor_id,
                )
                .order_by(
                    ComparisonReportRecord.completed_at.desc(),
                    ComparisonReportRecord.id.desc(),
                )
                .limit(100)
                .execution_options(populate_existing=True)
            )
        ).all()
        return [stored(row) for row in rows]

    async def insert(self, actor_id: UUID, report: ComparisonImport) -> StoredComparison:
        statement = (
            insert(ComparisonReportRecord)
            .values(
                id=uuid4(),
                owner_id=actor_id,
                source_key=report.source_key,
                source_result_sha256=report.source_result_sha256,
                content_sha256=hashlib.sha256(report.canonical_bytes()).hexdigest(),
                payload=report.model_dump(mode="json"),
                completed_at=report.completed_at,
            )
            .on_conflict_do_nothing(constraint="uq_rag_comparison_source")
        )
        await self.session.execute(statement)
        row = await self.by_key(actor_id, report.source_key)
        if row is None:
            raise unavailable()
        return row

    async def accessible(self, actor_id: UUID, report: ComparisonImport) -> bool:
        expected = {
            (e.document_id, e.asset_version_id, e.projection_id, e.index_build_id, e.evidence_id)
            for e in report.evidence
        }
        statement = (
            select(
                EvidenceUnitRecord, DocumentRecord.id, AssetVersionRecord.id, RagIndexBuildRecord.id
            )
            .select_from(DocumentRecord)
            .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
            .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
            .join(
                RagProjectionRecord, RagProjectionRecord.asset_version_id == AssetVersionRecord.id
            )
            .join(RagIndexBuildRecord, RagIndexBuildRecord.projection_id == RagProjectionRecord.id)
            .join(EvidenceUnitRecord, EvidenceUnitRecord.projection_id == RagProjectionRecord.id)
            .where(
                tuple_(
                    DocumentRecord.id,
                    AssetVersionRecord.id,
                    RagProjectionRecord.id,
                    RagIndexBuildRecord.id,
                    EvidenceUnitRecord.id,
                ).in_(expected),
                DocumentRecord.lifecycle == "active",
                workspace_read_allowed(actor_id),
                AssetVersionRecord.status == "ready",
                RagProjectionRecord.status == "ready",
                RagIndexBuildRecord.status == "ready",
                RagIndexBuildRecord.indexing_profile_id == RagProjectionRecord.indexing_profile_id,
                RagIndexBuildRecord.document_processing_profile_id
                == RagProjectionRecord.document_processing_profile_id,
            )
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(statement)).all()
        if len(rows) != len(expected):
            return False
        by_id = {e.evidence_id: e for e in report.evidence}
        return all(
            (document_id, version_id, unit.projection_id, build_id, unit.id) in expected
            and matches_evidence(unit, by_id[unit.id])
            for unit, document_id, version_id, build_id in rows
        )
