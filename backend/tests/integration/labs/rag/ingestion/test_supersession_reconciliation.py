import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from ai_workshop.config import get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError
from ai_workshop.labs.rag.ingestion.models import (
    RagIngestionDispatchRecord,
    RagIngestionJobRecord,
)
from ai_workshop.labs.rag.ingestion.repository import (
    SqlAlchemyRagDispatchRepository,
    SqlAlchemyRagIngestionCommandRepository,
)
from ai_workshop.labs.rag.ingestion.service import RagIngestionService
from ai_workshop.labs.rag.ingestion.stages import ProductionReadinessVerifier
from ai_workshop.labs.rag.ingestion.tasks import SqlAlchemyRagIngestionLifecycle
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.tasks import create_asset_verification_workflow
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.integration


async def _bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content


@dataclass(frozen=True, slots=True)
class _SupersessionFixture:
    owner_id: UUID
    workspace_id: UUID
    document_id: UUID
    old_asset_id: UUID
    new_asset_id: UUID
    verification_job_id: UUID
    profile_id: UUID
    object_keys: tuple[str, str]


async def _seed_supersession_fixture() -> _SupersessionFixture:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    store = LocalObjectStore(settings.object_store_root)
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    old_asset_id = uuid4()
    new_asset_id = uuid4()
    profile_id = uuid4()
    object_keys = (
        f"synthetic/supersession-{old_asset_id}.txt",
        f"synthetic/supersession-{new_asset_id}.txt",
    )
    old_stored = await store.put(object_keys[0], _bytes_source(b"Synthetic old source."))
    new_stored = await store.put(object_keys[1], _bytes_source(b"Synthetic new source."))
    verification_job = Job.create(
        user_id=owner_id,
        workspace_id=workspace_id,
        asset_version_id=new_asset_id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"verify:{new_asset_id}",
    )
    try:
        async with sessions.begin() as session:
            session.add(
                UserRecord(
                    id=owner_id,
                    display_name="Synthetic Supersession Owner",
                    email=f"supersession-{owner_id}@example.test",
                    normalized_email=f"supersession-{owner_id}@example.test",
                    password_hash="synthetic-password-hash",
                    role="owner",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Synthetic Supersession Workspace {workspace_id}",
                    kind="personal",
                    created_by=owner_id,
                    expires_at=None,
                )
            )
            await session.flush()
            session.add_all(
                [
                    DocumentRecord(
                        id=document_id,
                        workspace_id=workspace_id,
                        folder_id=None,
                        name="supersession.txt",
                        active_version_id=None,
                    ),
                    ProfileRecord(
                        id=profile_id,
                        kind="indexing",
                        name=f"synthetic-supersession-{profile_id}",
                        version=1,
                        config={
                            "chunker": {
                                "name": "structure-aware",
                                "version": 2,
                                "target_tokens": 380,
                                "overlap_tokens": 60,
                            }
                        },
                        evaluation_state="draft",
                        is_default=False,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AssetVersionRecord(
                        id=old_asset_id,
                        document_id=document_id,
                        number=1,
                        object_key=old_stored.key,
                        sha256=old_stored.sha256,
                        media_type="text/plain",
                        size=old_stored.size,
                        status="ready",
                    ),
                    AssetVersionRecord(
                        id=new_asset_id,
                        document_id=document_id,
                        number=2,
                        object_key=new_stored.key,
                        sha256=new_stored.sha256,
                        media_type="text/plain",
                        size=new_stored.size,
                        status="stored",
                    ),
                ]
            )
            await session.flush()
            document = await session.get(DocumentRecord, document_id)
            assert document is not None
            document.active_version_id = old_asset_id
            await SqlAlchemyJobRepository(session).add(verification_job)
        return _SupersessionFixture(
            owner_id=owner_id,
            workspace_id=workspace_id,
            document_id=document_id,
            old_asset_id=old_asset_id,
            new_asset_id=new_asset_id,
            verification_job_id=verification_job.id,
            profile_id=profile_id,
            object_keys=object_keys,
        )
    except Exception:
        for key in object_keys:
            await store.delete(key)
        raise
    finally:
        await engine.dispose()


async def _delete_supersession_fixture(fixture: _SupersessionFixture) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.id == fixture.workspace_id)
            )
            await session.execute(
                delete(ProfileRecord).where(ProfileRecord.id == fixture.profile_id)
            )
            await session.execute(delete(UserRecord).where(UserRecord.id == fixture.owner_id))
    finally:
        await engine.dispose()
    store = LocalObjectStore(settings.object_store_root)
    for key in fixture.object_keys:
        await store.delete(key)


@pytest.mark.asyncio
async def test_ensure_old_source_waits_for_concurrent_new_version_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    new_version_ready = asyncio.Event()
    release_verification_commit = asyncio.Event()
    original_update = SqlAlchemyJobRepository.update

    async def pause_new_version_commit(repository: SqlAlchemyJobRepository, job: Job) -> Job:
        updated = await original_update(repository, job)
        if job.id == fixture.verification_job_id and job.status is JobStatus.SUCCEEDED:
            new_version_ready.set()
            await release_verification_commit.wait()
        return updated

    monkeypatch.setattr(SqlAlchemyJobRepository, "update", pause_new_version_commit)
    verification = asyncio.create_task(
        create_asset_verification_workflow(settings).run(fixture.verification_job_id)
    )
    ensure: asyncio.Task[UUID] | None = None
    try:
        await asyncio.wait_for(new_version_ready.wait(), timeout=5)

        async def ensure_old_source() -> UUID:
            async with sessions.begin() as session:
                return await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(session)
                ).ensure_indexed(
                    EnsureIndexedCommand(
                        fixture.old_asset_id,
                        fixture.profile_id,
                        fixture.owner_id,
                    )
                )

        ensure = asyncio.create_task(ensure_old_source())
        await asyncio.sleep(0.2)
        assert not ensure.done(), (
            "ensure-v1 must wait for the in-flight v2 AssetVersion->Document lock"
        )

        release_verification_commit.set()
        assert await verification == fixture.new_asset_id
        with pytest.raises(RagIngestionError) as exc_info:
            await ensure
        assert exc_info.value.code == "index_source_inactive"
    finally:
        release_verification_commit.set()
        await asyncio.gather(verification, return_exceptions=True)
        if ensure is not None:
            await asyncio.gather(ensure, return_exceptions=True)
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_dispatch_claim_waits_for_concurrent_new_version_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    new_version_ready = asyncio.Event()
    release_verification_commit = asyncio.Event()
    original_update = SqlAlchemyJobRepository.update

    async def pause_new_version_commit(repository: SqlAlchemyJobRepository, job: Job) -> Job:
        updated = await original_update(repository, job)
        if job.id == fixture.verification_job_id and job.status is JobStatus.SUCCEEDED:
            new_version_ready.set()
            await release_verification_commit.wait()
        return updated

    monkeypatch.setattr(SqlAlchemyJobRepository, "update", pause_new_version_commit)
    async with sessions.begin() as session:
        await RagIngestionService(SqlAlchemyRagIngestionCommandRepository(session)).ensure_indexed(
            EnsureIndexedCommand(
                fixture.old_asset_id,
                fixture.profile_id,
                fixture.owner_id,
            )
        )
    verification = asyncio.create_task(
        create_asset_verification_workflow(settings).run(fixture.verification_job_id)
    )
    claim: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(new_version_ready.wait(), timeout=5)
        current = datetime.now(UTC)
        claim = asyncio.create_task(
            SqlAlchemyRagDispatchRepository(sessions).claim_ready(
                now=current,
                stale_before=current - timedelta(minutes=5),
                limit=10,
            )
        )
        await asyncio.sleep(0.2)
        assert not claim.done(), "dispatch claim must wait for the in-flight v2 Document lock"

        release_verification_commit.set()
        assert await verification == fixture.new_asset_id
        assert await claim == ()
    finally:
        release_verification_commit.set()
        await asyncio.gather(verification, return_exceptions=True)
        if claim is not None:
            await asyncio.gather(claim, return_exceptions=True)
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_handoff_failure_ledger_bounds_retry_and_resolves_exact_identity() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord
    from ai_workshop.labs.rag.ingestion.repository import (
        SqlAlchemyRagAssetHandoffFailureRepository,
    )

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    current = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)

    def clock() -> datetime:
        return current

    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    repository = SqlAlchemyRagAssetHandoffFailureRepository(
        sessions,
        clock=clock,
        max_attempts=3,
        base_backoff_seconds=10,
    )
    try:
        await repository.record(
            command,
            error_class="transient",
            error_code="database_transient",
            safe_message="A safe transient handoff failure occurred.",
        )
        async with sessions() as session:
            first = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert first is not None
        assert first.status == "retrying"
        assert first.attempt_count == 1
        assert first.next_retry_at == current + timedelta(seconds=10)
        assert len(first.last_error_message) <= 500

        current += timedelta(seconds=10)
        await repository.record(
            command,
            error_class="transient",
            error_code="database_transient",
            safe_message="A safe transient handoff failure occurred.",
        )
        current += timedelta(seconds=20)
        await repository.record(
            command,
            error_class="transient",
            error_code="database_transient",
            safe_message="A safe transient handoff failure occurred.",
        )
        async with sessions() as session:
            exhausted = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert exhausted is not None
        assert exhausted.status == "quarantined"
        assert exhausted.error_class == "transient"
        assert exhausted.attempt_count == 3
        assert exhausted.next_retry_at is None
        assert exhausted.terminal_at == current

        await repository.resolve(command)
        async with sessions() as session:
            resolved = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert resolved is not None
        assert resolved.status == "resolved"
        assert resolved.error_code is None
        assert resolved.error_class is None
        assert resolved.next_retry_at is None

        await repository.record(
            command,
            error_class="obsolete",
            error_code="index_source_inactive",
            safe_message="The exact source is obsolete.",
        )
        async with sessions() as session:
            obsolete = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert obsolete is not None
        assert obsolete.status == "cancelled"
        assert obsolete.error_class == "obsolete"
        assert obsolete.next_retry_at is None
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_cancelled_handoff_absorbs_late_locked_failure_writers() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord
    from ai_workshop.labs.rag.ingestion.repository import (
        SqlAlchemyRagAssetHandoffFailureRepository,
    )

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    current = datetime(2026, 8, 31, 1, 0, tzinfo=UTC)
    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    repository = SqlAlchemyRagAssetHandoffFailureRepository(
        sessions,
        clock=lambda: current,
    )
    writer_select_started = asyncio.Event()
    stale_writer: asyncio.Task[None] | None = None

    def observe_exact_lock(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if "rag_asset_handoff_failures" in statement and "FOR UPDATE" in statement:
            writer_select_started.set()

    async def terminal_snapshot() -> tuple[Any, ...]:
        async with sessions() as session:
            record = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert record is not None
        return (
            record.status,
            record.requested_by,
            record.error_class,
            record.error_code,
            record.attempt_count,
            record.last_attempt_at,
            record.next_retry_at,
            record.terminal_at,
            record.last_error_message,
        )

    try:
        await repository.record(
            command,
            error_class="obsolete",
            error_code="index_source_inactive",
            safe_message="The exact source is obsolete.",
        )
        expected = await terminal_snapshot()
        current += timedelta(seconds=10)

        async with sessions.begin() as blocker:
            locked = await blocker.scalar(
                select(RagAssetHandoffFailureRecord)
                .where(
                    RagAssetHandoffFailureRecord.asset_version_id
                    == fixture.old_asset_id,
                    RagAssetHandoffFailureRecord.indexing_profile_id
                    == fixture.profile_id,
                )
                .with_for_update()
            )
            assert locked is not None and locked.status == "cancelled"
            event.listen(engine.sync_engine, "before_cursor_execute", observe_exact_lock)
            stale_writer = asyncio.create_task(
                repository.record(
                    command,
                    error_class="transient",
                    error_code="database_transient",
                    safe_message="A stale transient failure arrived late.",
                )
            )
            await asyncio.wait_for(writer_select_started.wait(), timeout=5)
            await asyncio.sleep(0)
            assert not stale_writer.done(), "the stale writer must wait for the exact row lock"

        await stale_writer
        snapshots = [await terminal_snapshot()]
        current += timedelta(seconds=10)
        await repository.record(
            command,
            error_class="permanent",
            error_code="internal_error",
            safe_message="Internal RAG Asset handoff failure class: ValueError.",
        )
        snapshots.append(await terminal_snapshot())
        await repository.resolve(command)
        snapshots.append(await terminal_snapshot())

        assert snapshots == [expected, expected, expected]
    finally:
        if event.contains(engine.sync_engine, "before_cursor_execute", observe_exact_lock):
            event.remove(engine.sync_engine, "before_cursor_execute", observe_exact_lock)
        if stale_writer is not None:
            await asyncio.gather(stale_writer, return_exceptions=True)
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_direct_ensure_resolves_quarantine_for_new_and_existing_job_once() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    try:
        async with sessions.begin() as session:
            session.add(
                RagAssetHandoffFailureRecord(
                    asset_version_id=fixture.old_asset_id,
                    indexing_profile_id=fixture.profile_id,
                    requested_by=fixture.owner_id,
                    status="quarantined",
                    error_class="permanent",
                    error_code="internal_error",
                    attempt_count=1,
                    last_attempt_at=datetime.now(UTC),
                    next_retry_at=None,
                    terminal_at=datetime.now(UTC),
                    last_error_message="Internal failure class: ValueError.",
                )
            )

        async with sessions.begin() as session:
            service = RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            )
            created_job_id = await service.ensure_indexed(command)
            existing_job_id = await service.ensure_indexed(command)

        assert existing_job_id == created_job_id
        async with sessions() as session:
            failure = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
            job_count = await session.scalar(
                select(func.count())
                .select_from(RagIngestionJobRecord)
                .where(
                    RagIngestionJobRecord.asset_version_id == fixture.old_asset_id,
                    RagIngestionJobRecord.indexing_profile_id == fixture.profile_id,
                )
            )
        assert failure is not None
        assert failure.status == "resolved"
        assert failure.error_class is None
        assert failure.error_code is None
        assert failure.last_error_message is None
        assert failure.next_retry_at is None
        assert failure.terminal_at is not None
        assert job_count == 1
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_existing_job_success_resolves_later_exact_quarantine_without_duplicate() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    try:
        async with sessions.begin() as session:
            original_job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(command)
        async with sessions.begin() as session:
            session.add(
                RagAssetHandoffFailureRecord(
                    asset_version_id=fixture.old_asset_id,
                    indexing_profile_id=fixture.profile_id,
                    requested_by=fixture.owner_id,
                    status="quarantined",
                    error_class="permanent",
                    error_code="internal_error",
                    attempt_count=1,
                    last_attempt_at=datetime.now(UTC),
                    next_retry_at=None,
                    terminal_at=datetime.now(UTC),
                    last_error_message="Internal failure class: TypeError.",
                )
            )

        async with sessions.begin() as session:
            returned_job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(command)

        assert returned_job_id == original_job_id
        async with sessions() as session:
            failure = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
            job_count = await session.scalar(
                select(func.count())
                .select_from(RagIngestionJobRecord)
                .where(
                    RagIngestionJobRecord.asset_version_id == fixture.old_asset_id,
                    RagIngestionJobRecord.indexing_profile_id == fixture.profile_id,
                )
            )
        assert failure is not None and failure.status == "resolved"
        assert job_count == 1
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_direct_ensure_does_not_reverse_an_obsolete_cancelled_ledger() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    try:
        async with sessions.begin() as session:
            session.add(
                RagAssetHandoffFailureRecord(
                    asset_version_id=fixture.old_asset_id,
                    indexing_profile_id=fixture.profile_id,
                    requested_by=fixture.owner_id,
                    status="cancelled",
                    error_class="obsolete",
                    error_code="index_source_inactive",
                    attempt_count=1,
                    last_attempt_at=datetime.now(UTC),
                    next_retry_at=None,
                    terminal_at=datetime.now(UTC),
                    last_error_message="The exact source is obsolete.",
                )
            )

        async with sessions.begin() as session:
            await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(command)

        async with sessions() as session:
            failure = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
        assert failure is not None
        assert failure.status == "cancelled"
        assert failure.error_class == "obsolete"
        assert failure.error_code == "index_source_inactive"
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_failed_new_job_commit_does_not_falsely_resolve_quarantine() -> None:
    from ai_workshop.labs.rag.ingestion.models import RagAssetHandoffFailureRecord

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    command = EnsureIndexedCommand(
        fixture.old_asset_id,
        fixture.profile_id,
        fixture.owner_id,
    )
    commit_attempted = False

    def fail_commit(_connection) -> None:
        nonlocal commit_attempted
        commit_attempted = True
        raise OperationalError(
            "synthetic direct ensure commit failure",
            {},
            OSError("connection lost"),
        )

    try:
        async with sessions.begin() as session:
            session.add(
                RagAssetHandoffFailureRecord(
                    asset_version_id=fixture.old_asset_id,
                    indexing_profile_id=fixture.profile_id,
                    requested_by=fixture.owner_id,
                    status="quarantined",
                    error_class="permanent",
                    error_code="internal_error",
                    attempt_count=1,
                    last_attempt_at=datetime.now(UTC),
                    next_retry_at=None,
                    terminal_at=datetime.now(UTC),
                    last_error_message="Internal failure class: RuntimeError.",
                )
            )
        event.listen(Engine, "commit", fail_commit)

        with pytest.raises(OperationalError):
            async with sessions.begin() as session:
                await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(session)
                ).ensure_indexed(command)

        assert commit_attempted is True
        async with sessions() as session:
            failure = await session.get(
                RagAssetHandoffFailureRecord,
                (fixture.old_asset_id, fixture.profile_id),
            )
            job_count = await session.scalar(
                select(func.count())
                .select_from(RagIngestionJobRecord)
                .where(
                    RagIngestionJobRecord.asset_version_id == fixture.old_asset_id,
                    RagIngestionJobRecord.indexing_profile_id == fixture.profile_id,
                )
            )
        assert failure is not None and failure.status == "quarantined"
        assert failure.error_code == "internal_error"
        assert job_count == 0
    finally:
        if event.contains(Engine, "commit", fail_commit):
            event.remove(Engine, "commit", fail_commit)
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_status", ["pending", "claimed", "sent"])
async def test_reconciler_terminalizes_inactive_nonterminal_ingestion_once(
    dispatch_status: str,
) -> None:
    from ai_workshop.labs.rag.ingestion.recovery import (
        SqlAlchemyInactiveRagIngestionReconciler,
    )

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    job_id: UUID | None = None
    try:
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(
                EnsureIndexedCommand(
                    fixture.old_asset_id,
                    fixture.profile_id,
                    fixture.owner_id,
                )
            )
        await SqlAlchemyRagIngestionLifecycle(settings).begin(job_id)
        async with sessions.begin() as session:
            dispatch = await session.get(RagIngestionDispatchRecord, job_id)
            assert dispatch is not None
            dispatch.status = dispatch_status
            if dispatch_status == "claimed":
                dispatch.claim_token = uuid4()
                dispatch.claimed_at = datetime.now(UTC)
            elif dispatch_status == "sent":
                dispatch.sent_at = datetime.now(UTC)
            await session.flush()

        assert (
            await create_asset_verification_workflow(settings).run(fixture.verification_job_id)
            == fixture.new_asset_id
        )

        first, second = await asyncio.gather(
            SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10),
            SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10),
        )
        assert first.terminalized + second.terminalized == 1
        assert (
            await SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10)
        ).terminalized == 0

        async with sessions() as session:
            job = await session.get(JobRecord, job_id)
            ingestion = await session.get(RagIngestionJobRecord, job_id)
            dispatch = await session.get(RagIngestionDispatchRecord, job_id)
            assert job is not None and ingestion is not None and dispatch is not None
            projection = await session.get(RagProjectionRecord, ingestion.projection_id)
        assert job.status == JobStatus.FAILED
        assert job.stage == "failed"
        assert job.error_code == "index_source_inactive"
        assert projection is not None and projection.status == ProjectionStatus.FAILED
        assert dispatch.status == "cancelled"
        assert dispatch.claim_token is None
        assert dispatch.claimed_at is None
        assert dispatch.sent_at is None
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_reconciler_terminalizes_ready_source_when_active_pointer_is_null() -> None:
    from ai_workshop.labs.rag.ingestion.recovery import (
        SqlAlchemyInactiveRagIngestionReconciler,
    )

    fixture = await _seed_supersession_fixture()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    job_id: UUID | None = None
    try:
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(
                EnsureIndexedCommand(
                    fixture.old_asset_id,
                    fixture.profile_id,
                    fixture.owner_id,
                )
            )
        async with sessions.begin() as session:
            document = await session.get(DocumentRecord, fixture.document_id)
            assert document is not None
            document.active_version_id = None
            await session.flush()

        result = await SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10)
        assert result.terminalized == 1
        async with sessions() as session:
            job = await session.get(JobRecord, job_id)
            dispatch = await session.get(RagIngestionDispatchRecord, job_id)
        assert job is not None and job.status == JobStatus.FAILED
        assert job.error_code == "index_source_inactive"
        assert dispatch is not None and dispatch.status == "cancelled"
    finally:
        await engine.dispose()
        await _delete_supersession_fixture(fixture)


@pytest.mark.asyncio
async def test_final_old_source_activation_waits_for_concurrent_new_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_workshop.labs.rag.ingestion.stages as stages_module

    fixture = await _seed_supersession_fixture()
    settings = get_settings().model_copy(
        update={"elasticsearch_index_prefix": f"task14b-r2-{uuid4().hex}"}
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    new_version_ready = asyncio.Event()
    release_verification_commit = asyncio.Event()
    original_update = SqlAlchemyJobRepository.update

    async def pause_new_version_commit(repository: SqlAlchemyJobRepository, job: Job) -> Job:
        updated = await original_update(repository, job)
        if job.id == fixture.verification_job_id and job.status is JobStatus.SUCCEEDED:
            new_version_ready.set()
            await release_verification_commit.wait()
        return updated

    monkeypatch.setattr(SqlAlchemyJobRepository, "update", pause_new_version_commit)
    async with sessions.begin() as session:
        old_ingestion_job_id = await RagIngestionService(
            SqlAlchemyRagIngestionCommandRepository(session)
        ).ensure_indexed(
            EnsureIndexedCommand(
                fixture.old_asset_id,
                fixture.profile_id,
                fixture.owner_id,
            )
        )
    build_id = uuid4()
    async with sessions.begin() as session:
        ingestion = await session.get(RagIngestionJobRecord, old_ingestion_job_id)
        job = await session.get(JobRecord, old_ingestion_job_id)
        assert ingestion is not None and job is not None
        projection = await session.get(RagProjectionRecord, ingestion.projection_id)
        assert projection is not None
        projection.status = ProjectionStatus.INDEXING
        job.status = JobStatus.RUNNING
        job.stage = ProjectionStatus.INDEXING
        job.attempt = 1
        job.started_at = datetime.now(UTC)
        ingestion.parsed_element_count = 1
        ingestion.chunk_count = 1
        ingestion.embedding_count = 1
        ingestion.index_build_id = build_id
        descriptor = IndexDescriptor(1, "cosine")
        session.add(
            RagIndexBuildRecord(
                id=build_id,
                projection_id=projection.id,
                indexing_profile_id=fixture.profile_id,
                index_name=descriptor.concrete_index_name(
                    settings.elasticsearch_index_prefix,
                    fixture.profile_id,
                    build_id,
                ),
                expected_document_count=1,
                indexed_document_count=1,
                vector_dimension=1,
                status="prepared",
                is_active=False,
            )
        )

    async def resolved_embedding(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(config=SimpleNamespace(dimension=1))

    monkeypatch.setattr(stages_module, "_resolve_embedding", resolved_embedding)

    class RecordingAlias:
        def __init__(self) -> None:
            self.targets: tuple[str, ...] = ()
            self.replace_calls = 0

        async def replace_active_targets(self, alias: str, index_names: tuple[str, ...]) -> bool:
            del alias
            self.replace_calls += 1
            self.targets = tuple(sorted(index_names))
            return True

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            del alias
            return self.targets

    alias = RecordingAlias()

    @asynccontextmanager
    async def alias_session() -> AsyncIterator[Any]:
        yield alias

    verification = asyncio.create_task(
        create_asset_verification_workflow(settings).run(fixture.verification_job_id)
    )
    final_activation: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(new_version_ready.wait(), timeout=5)
        async with sessions() as session:
            ingestion = await session.get(RagIngestionJobRecord, old_ingestion_job_id)
            assert ingestion is not None
            projection_id = ingestion.projection_id
        final_activation = asyncio.create_task(
            ProductionReadinessVerifier(settings, search_index_session=alias_session).verify(
                projection_id=projection_id,
                indexing_profile_id=fixture.profile_id,
            )
        )
        await asyncio.sleep(0.2)
        assert not final_activation.done(), (
            "final v1 alias/READY commit must wait for the v2 source lock"
        )

        release_verification_commit.set()
        assert await verification == fixture.new_asset_id
        with pytest.raises(RagIngestionError) as exc_info:
            await final_activation
        assert exc_info.value.code == "index_source_inactive"
        assert alias.replace_calls == 0
    finally:
        release_verification_commit.set()
        await asyncio.gather(verification, return_exceptions=True)
        if final_activation is not None:
            await asyncio.gather(final_activation, return_exceptions=True)
        await engine.dispose()
        await _delete_supersession_fixture(fixture)
