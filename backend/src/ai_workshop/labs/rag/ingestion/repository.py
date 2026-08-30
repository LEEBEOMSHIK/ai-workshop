from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.documents.domain import ProjectionStatus, RagProjection
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository


class SqlAlchemyRagIngestionCommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure(self, command: EnsureIndexedCommand, *, idempotency_key: str) -> UUID:
        asset_result = await self.session.execute(
            select(AssetVersionRecord, DocumentRecord.workspace_id)
            .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
            .where(AssetVersionRecord.id == command.asset_version_id)
            .with_for_update(of=AssetVersionRecord)
        )
        asset_row = asset_result.one_or_none()
        if asset_row is None:
            raise LookupError("Asset version does not exist.")
        asset_version, workspace_id = asset_row
        profile = await self.session.get(ProfileRecord, command.indexing_profile_id)
        if profile is None or profile.kind != "indexing":
            raise LookupError("Indexing profile does not exist.")

        existing = await self.session.scalar(
            select(RagIngestionJobRecord).where(
                RagIngestionJobRecord.asset_version_id == command.asset_version_id,
                RagIngestionJobRecord.indexing_profile_id == command.indexing_profile_id,
            )
        )
        if existing is not None:
            return existing.job_id

        projection_record = await self.session.scalar(
            select(RagProjectionRecord).where(
                RagProjectionRecord.asset_version_id == command.asset_version_id,
                RagProjectionRecord.indexing_profile_id == command.indexing_profile_id,
            )
        )
        if projection_record is None:
            projection = RagProjection.pending(
                asset_version_id=command.asset_version_id,
                indexing_profile_id=command.indexing_profile_id,
            )
            await SqlAlchemyRagDocumentRepository(self.session).add_projection(projection)
        else:
            projection = RagProjection(
                id=projection_record.id,
                asset_version_id=projection_record.asset_version_id,
                indexing_profile_id=projection_record.indexing_profile_id,
                status=ProjectionStatus(projection_record.status),
            )

        job = Job.create(
            user_id=command.requested_by,
            workspace_id=workspace_id,
            asset_version_id=asset_version.id,
            type=JobType.RAG_INGESTION,
            idempotency_key=idempotency_key,
        )
        await SqlAlchemyJobRepository(self.session).add(job)
        self.session.add(
            RagIngestionJobRecord(
                job_id=job.id,
                projection_id=projection.id,
                asset_version_id=command.asset_version_id,
                indexing_profile_id=command.indexing_profile_id,
                requested_by=command.requested_by,
                parsed_object_key=None,
                parsed_sha256=None,
                chunk_object_key=None,
                chunk_sha256=None,
                embedding_object_key=None,
                embedding_sha256=None,
                index_build_id=None,
                parsed_element_count=None,
                chunk_count=None,
                embedding_count=None,
                indexed_document_count=None,
                index_alias_verified=False,
            )
        )
        await self.session.flush()
        return job.id
