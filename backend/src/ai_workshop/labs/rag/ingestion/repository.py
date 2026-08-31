from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.documents.domain import ProjectionStatus, RagProjection
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.ingestion.dispatch import DispatchClaim
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.models import (
    RagAssetHandoffFailureRecord,
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
        source = await lock_ingestion_source(self.session, command.asset_version_id)
        asset_version = source.asset
        workspace_id = source.document.workspace_id
        profile = await self.session.get(ProfileRecord, command.indexing_profile_id)
        if profile is None or profile.kind != "indexing":
            raise RagIngestionError(
                "indexing_profile_missing",
                "The indexing profile does not exist.",
                retryable=False,
            )

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


class SqlAlchemyRagAssetHandoffSource:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]:
        asset_version_ids = await self.session.scalars(
            select(AssetVersionRecord.id)
            .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
            .where(
                AssetVersionRecord.status == "ready",
                DocumentRecord.active_version_id == AssetVersionRecord.id,
            )
            .order_by(AssetVersionRecord.created_at, AssetVersionRecord.id)
        )
        commands: list[EnsureIndexedCommand] = []
        configurations = SqlAlchemyRagConfigurationRepository(self.session)
        for asset_version_id in asset_version_ids:
            for indexing_profile_id, requested_by in await configurations.subscriptions_for_asset(
                asset_version_id
            ):
                exists = await self.session.scalar(
                    select(RagIngestionJobRecord.job_id).where(
                        RagIngestionJobRecord.asset_version_id == asset_version_id,
                        RagIngestionJobRecord.indexing_profile_id == indexing_profile_id,
                    )
                )
                failure = await self.session.get(
                    RagAssetHandoffFailureRecord,
                    (asset_version_id, indexing_profile_id),
                )
                if exists is None:
                    should_handoff = (
                        failure is None
                        or failure.status == "resolved"
                        or (
                            failure.status == "retrying"
                            and failure.next_retry_at is not None
                            and failure.next_retry_at <= datetime.now(UTC)
                        )
                    )
                else:
                    should_handoff = (
                        failure is not None
                        and failure.status == "retrying"
                        and failure.next_retry_at is not None
                        and failure.next_retry_at <= datetime.now(UTC)
                    )
                if should_handoff:
                    commands.append(
                        EnsureIndexedCommand(
                            asset_version_id,
                            indexing_profile_id,
                            requested_by,
                        )
                    )
                    if len(commands) >= limit:
                        return tuple(commands)
        return tuple(commands)


class SqlAlchemyRagAssetHandoffFailureRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_attempts: int = 5,
        base_backoff_seconds: int = 5,
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds

    async def record(
        self,
        command: EnsureIndexedCommand,
        *,
        error_class: str,
        error_code: str,
        safe_message: str,
    ) -> None:
        if error_class not in {"transient", "permanent", "obsolete"}:
            raise ValueError("Unknown RAG Asset handoff error class.")
        now = self.clock()
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(RagAssetHandoffFailureRecord)
                .where(
                    RagAssetHandoffFailureRecord.asset_version_id == command.asset_version_id,
                    RagAssetHandoffFailureRecord.indexing_profile_id == command.indexing_profile_id,
                )
                .with_for_update()
            )
            if record is None:
                record = RagAssetHandoffFailureRecord(
                    asset_version_id=command.asset_version_id,
                    indexing_profile_id=command.indexing_profile_id,
                    requested_by=command.requested_by,
                    status="retrying",
                    error_class="transient",
                    error_code=error_code[:100],
                    attempt_count=0,
                    last_attempt_at=None,
                    next_retry_at=now,
                    terminal_at=None,
                    last_error_message=safe_message[:500],
                )
                session.add(record)
            elif record.status == "resolved":
                record.attempt_count = 0
            record.requested_by = command.requested_by
            record.attempt_count += 1
            record.last_attempt_at = now
            record.error_class = error_class
            record.error_code = error_code[:100]
            record.last_error_message = safe_message[:500]
            if error_class == "obsolete":
                record.status = "cancelled"
                record.next_retry_at = None
                record.terminal_at = now
            elif error_class == "permanent" or record.attempt_count >= self.max_attempts:
                record.status = "quarantined"
                record.next_retry_at = None
                record.terminal_at = now
            else:
                delay = self.base_backoff_seconds * (2 ** (record.attempt_count - 1))
                record.status = "retrying"
                record.next_retry_at = now + timedelta(seconds=delay)
                record.terminal_at = None
            await session.flush()

    async def resolve(self, command: EnsureIndexedCommand) -> None:
        now = self.clock()
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(RagAssetHandoffFailureRecord)
                .where(
                    RagAssetHandoffFailureRecord.asset_version_id == command.asset_version_id,
                    RagAssetHandoffFailureRecord.indexing_profile_id == command.indexing_profile_id,
                )
                .with_for_update()
            )
            if record is None or record.status == "resolved":
                return
            record.status = "resolved"
            record.error_class = None
            record.error_code = None
            record.last_error_message = None
            record.next_retry_at = None
            record.terminal_at = now
            await session.flush()


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
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord)
                    .join(
                        RagIngestionDispatchRecord,
                        RagIngestionDispatchRecord.job_id == RagIngestionJobRecord.job_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagIngestionJobRecord.asset_version_id,
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == AssetVersionRecord.document_id,
                    )
                    .where(
                        AssetVersionRecord.status == "ready",
                        DocumentRecord.active_version_id == AssetVersionRecord.id,
                        or_(
                            and_(
                                RagIngestionDispatchRecord.status == "pending",
                                RagIngestionDispatchRecord.available_at <= now,
                            ),
                            and_(
                                RagIngestionDispatchRecord.status == "claimed",
                                RagIngestionDispatchRecord.claimed_at <= stale_before,
                            ),
                        ),
                    )
                    .order_by(
                        RagIngestionDispatchRecord.available_at,
                        RagIngestionDispatchRecord.created_at,
                    )
                    .limit(limit)
                    .with_for_update(of=RagIngestionJobRecord, skip_locked=True)
                )
            )
            claims: list[DispatchClaim] = []
            for ingestion in ingestions:
                try:
                    await lock_ingestion_source(session, ingestion.asset_version_id)
                except RagIngestionError as exc:
                    if exc.code == "index_source_inactive":
                        continue
                    raise
                record = await session.scalar(
                    select(RagIngestionDispatchRecord)
                    .where(RagIngestionDispatchRecord.job_id == ingestion.job_id)
                    .with_for_update()
                )
                if record is None or not (
                    (record.status == "pending" and record.available_at <= now)
                    or (
                        record.status == "claimed"
                        and record.claimed_at is not None
                        and record.claimed_at <= stale_before
                    )
                ):
                    continue
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
