from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.documents.domain import ProjectionStatus, RagProjection
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.ingestion.dispatch import DispatchClaim
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.ingestion.models import (
    RagIngestionDispatchRecord,
    RagIngestionJobRecord,
)
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
            if await self.session.get(RagIngestionDispatchRecord, existing.job_id) is None:
                self.session.add(
                    RagIngestionDispatchRecord(
                        job_id=existing.job_id,
                        status="pending",
                        available_at=datetime.now(UTC),
                        claimed_at=None,
                        claim_token=None,
                        attempt_count=0,
                        last_error=None,
                        sent_at=None,
                    )
                )
                await self.session.flush()
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
        self.session.add(
            RagIngestionDispatchRecord(
                job_id=job.id,
                status="pending",
                available_at=datetime.now(UTC),
                claimed_at=None,
                claim_token=None,
                attempt_count=0,
                last_error=None,
                sent_at=None,
            )
        )
        await self.session.flush()
        return job.id


class DispatchClaimLostError(RuntimeError):
    pass


class SqlAlchemyRagDispatchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim_ready(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> tuple[DispatchClaim, ...]:
        async with self.sessions.begin() as session:
            result = await session.execute(
                select(RagIngestionDispatchRecord)
                .where(
                    or_(
                        and_(
                            RagIngestionDispatchRecord.status == "pending",
                            RagIngestionDispatchRecord.available_at <= now,
                        ),
                        and_(
                            RagIngestionDispatchRecord.status == "claimed",
                            RagIngestionDispatchRecord.claimed_at <= stale_before,
                        ),
                    )
                )
                .order_by(
                    RagIngestionDispatchRecord.available_at,
                    RagIngestionDispatchRecord.created_at,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            records = result.scalars().all()
            claims: list[DispatchClaim] = []
            for record in records:
                token = uuid4()
                record.status = "claimed"
                record.claimed_at = now
                record.claim_token = token
                record.attempt_count += 1
                record.sent_at = None
                claims.append(DispatchClaim(record.job_id, token, record.attempt_count))
            await session.flush()
        return tuple(claims)

    async def mark_sent(self, claim: DispatchClaim, *, now: datetime) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RagIngestionDispatchRecord)
                .where(
                    RagIngestionDispatchRecord.job_id == claim.job_id,
                    RagIngestionDispatchRecord.status == "claimed",
                    RagIngestionDispatchRecord.claim_token == claim.claim_token,
                )
                .values(
                    status="sent",
                    sent_at=now,
                    claimed_at=None,
                    claim_token=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise DispatchClaimLostError("RAG dispatch claim token is no longer valid.")

    async def mark_failed(
        self,
        claim: DispatchClaim,
        *,
        now: datetime,
        retry_at: datetime,
        error: str,
    ) -> None:
        del now
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RagIngestionDispatchRecord)
                .where(
                    RagIngestionDispatchRecord.job_id == claim.job_id,
                    RagIngestionDispatchRecord.status == "claimed",
                    RagIngestionDispatchRecord.claim_token == claim.claim_token,
                )
                .values(
                    status="pending",
                    available_at=retry_at,
                    claimed_at=None,
                    claim_token=None,
                    last_error=error[:700],
                    sent_at=None,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise DispatchClaimLostError("RAG dispatch claim token is no longer valid.")
