from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ingestion.models import RagIngestionDispatchRecord, RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagDispatchRepository
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.jobs.models import JobRecord

NOW = datetime(2026, 10, 8, tzinfo=UTC)


class Session:
    def __init__(self):
        self.id = uuid4()
        self.asset = AssetVersionRecord(id=uuid4(), document_id=uuid4(), status="ready")
        self.document = DocumentRecord(
            id=self.asset.document_id, active_version_id=self.asset.id, lifecycle="active"
        )
        self.ingestion = RagIngestionJobRecord(
            job_id=self.id,
            projection_id=uuid4(),
            asset_version_id=self.asset.id,
            indexing_profile_id=uuid4(),
            document_processing_profile_id=uuid4(),
            requested_by=uuid4(),
        )
        self.job = JobRecord(
            id=self.id,
            asset_version_id=self.asset.id,
            user_id=self.ingestion.requested_by,
            status="succeeded",
            type="rag_ingestion",
            stage="ready",
        )
        self.projection = RagProjectionRecord(
            id=self.ingestion.projection_id,
            asset_version_id=self.asset.id,
            indexing_profile_id=self.ingestion.indexing_profile_id,
            document_processing_profile_id=self.ingestion.document_processing_profile_id,
            status="ready",
        )
        self.dispatch = RagIngestionDispatchRecord(
            job_id=self.id, status="pending", available_at=NOW, attempt_count=2
        )
        self.calls = []
        self.flushes = 0
        self.entered = 0
        self.rows = {
            RagIngestionJobRecord: self.ingestion,
            JobRecord: self.job,
            RagProjectionRecord: self.projection,
            AssetVersionRecord: self.asset,
            DocumentRecord: self.document,
            RagIngestionDispatchRecord: self.dispatch,
        }

    @asynccontextmanager
    async def begin(self):
        self.entered += 1
        yield self

    async def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in sql
        assert statement.compile().params  # no unbounded write lock
        self.calls.append(entity)
        return self.rows[entity]

    async def scalars(self, statement):
        return [self.ingestion]

    async def get(self, entity, key):
        return None

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_exact_completed_pending_is_cancelled_without_broker_ack():
    s = Session()
    assert await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "cancelled"
    assert s.dispatch.cancelled_at == NOW
    assert s.dispatch.last_error == "rag_ingestion_already_completed"
    assert s.dispatch.sent_at is None
    assert s.dispatch.attempt_count == 2
    assert s.calls == [
        RagIngestionJobRecord,
        JobRecord,
        RagProjectionRecord,
        AssetVersionRecord,
        DocumentRecord,
        RagIngestionDispatchRecord,
    ]
    assert not await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.cancelled_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["claimed", "sent", "cancelled"])
async def test_completed_existing_delivery_is_not_rewritten(status):
    s = Session()
    s.dispatch.status = status
    old = (s.dispatch.status, s.dispatch.claim_token, s.dispatch.attempt_count, s.dispatch.sent_at)
    assert not await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert (
        s.dispatch.status,
        s.dispatch.claim_token,
        s.dispatch.attempt_count,
        s.dispatch.sent_at,
    ) == old


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "failed"])
async def test_non_success_is_not_cancelled(status):
    s = Session()
    s.job.status = status
    assert not await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["asset_version_id", "indexing_profile_id", "document_processing_profile_id"]
)
async def test_projection_binding_mismatch_is_denied(field):
    s = Session()
    setattr(s.projection, field, uuid4())
    with pytest.raises(RagIngestionError, match="durable RAG dispatch"):
        await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "pending"


@pytest.mark.asyncio
async def test_succeeded_without_ready_does_not_invent_completion():
    s = Session()
    s.projection.status = "indexing"
    with pytest.raises(RagIngestionError, match="durable RAG dispatch"):
        await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "pending"


@pytest.mark.asyncio
async def test_batch_does_not_send_successful_pending_job():
    s = Session()
    claims = await SqlAlchemyRagDispatchRepository(s).claim_ready(
        now=NOW, stale_before=NOW - timedelta(minutes=2), limit=1
    )
    assert claims == ()
    assert s.dispatch.status == "cancelled"
    assert s.dispatch.attempt_count == 2


@pytest.mark.asyncio
async def test_batch_does_not_reclaim_successful_unknown_delivery():
    s = Session()
    s.dispatch.status = "claimed"
    s.dispatch.claimed_at = NOW - timedelta(minutes=3)
    s.dispatch.claim_token = uuid4()
    old = s.dispatch.claim_token
    claims = await SqlAlchemyRagDispatchRepository(s).claim_ready(
        now=NOW, stale_before=NOW - timedelta(minutes=2), limit=1
    )
    assert claims == ()
    assert s.dispatch.status == "claimed" and s.dispatch.claim_token == old


@pytest.mark.asyncio
async def test_batch_nonterminal_delivery_keeps_existing_behavior():
    s = Session()
    s.job.status = "queued"
    s.projection.status = "pending"
    claims = await SqlAlchemyRagDispatchRepository(s).claim_ready(
        now=NOW, stale_before=NOW - timedelta(minutes=2), limit=1
    )
    assert len(claims) == 1 and claims[0].job_id == s.id
    assert s.dispatch.status == "claimed" and s.dispatch.attempt_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now",
    [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))],
)
async def test_non_utc_input_is_denied_before_lock(now):
    s = Session()
    with pytest.raises(ValueError):
        await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=now)
    assert s.entered == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["claim_token", "claimed_at", "sent_at", "cancelled_at"])
async def test_pending_with_inconsistent_delivery_marker_is_denied(field):
    s = Session()
    setattr(s.dispatch, field, uuid4() if field == "claim_token" else NOW)
    with pytest.raises(RagIngestionError, match="unresolved delivery"):
        await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "pending" and s.dispatch.attempt_count == 2


@pytest.mark.asyncio
async def test_missing_exact_obligation_does_not_create_one():
    s = Session()
    s.rows[RagIngestionDispatchRecord] = None
    assert not await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", [JobRecord, RagProjectionRecord])
async def test_missing_dependency_refuses_transition(entity):
    s = Session()
    s.rows[entity] = None
    with pytest.raises(RagIngestionError, match="durable RAG dispatch"):
        await SqlAlchemyRagDispatchRepository(s).cancel_completed(s.id, now=NOW)
    assert s.dispatch.status == "pending"
