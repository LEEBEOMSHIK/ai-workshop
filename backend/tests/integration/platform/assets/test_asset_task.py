import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import ai_workshop.platform.assets.tasks as asset_tasks_module
from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.tasks import (
    AssetTaskError,
    AssetVerificationLifecycle,
    AssetVerificationWorkflow,
    create_asset_verification_workflow,
    verify_stored_asset,
)
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceRecord

TEST_DATABASE_URL = os.getenv(
    "AI_WORKSHOP_TEST_DATABASE_URL",
    "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop",
)
SYNTHETIC_PUBLIC_BYTES = (
    b"Public synthetic asset used to verify the immutable upload lifecycle.\n"
)


class MemoryLifecycle(AssetVerificationLifecycle):
    def __init__(self, job: Job, version: AssetVersion) -> None:
        self.job = job
        self.version = version

    async def begin(self, job_id) -> AssetVersion:
        assert job_id == self.job.id
        self.job.start(stage="verifying_object")
        return self.version

    async def succeed(self, job_id) -> None:
        assert job_id == self.job.id
        self.job.succeed(stage="ready")

    async def fail(self, job_id, *, error_code: str, error_message: str) -> None:
        assert job_id == self.job.id
        self.job.fail(error_code=error_code, error_message=error_message)


class CompletedLifecycle(AssetVerificationLifecycle):
    def __init__(self, asset_version_id) -> None:
        self.asset_version_id = asset_version_id

    async def begin(self, job_id):
        return None

    async def verified_asset_version_id(self, job_id):
        return self.asset_version_id

    async def succeed(self, job_id) -> None:
        raise AssertionError("A completed job must not run again.")

    async def fail(self, job_id, *, error_code: str, error_message: str) -> None:
        raise AssertionError("A completed job must not run again.")


async def content() -> AsyncIterator[bytes]:
    yield b"verified report"


async def _bytes_source(value: bytes) -> AsyncIterator[bytes]:
    yield value


@dataclass(frozen=True, slots=True)
class VerificationScenario:
    settings: Settings
    actor_id: UUID
    workspace_id: UUID
    document_id: UUID
    version_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class VerificationSnapshot:
    active_version_id: UUID | None
    version_statuses: tuple[VersionStatus, ...]
    job_statuses: tuple[JobStatus, ...]
    job_stages: tuple[str, ...]


def _test_settings(object_store_root: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
        database_url=TEST_DATABASE_URL,
        object_store_root=object_store_root,
    )


async def _seed_verification_scenario(
    object_store_root: Path,
    *,
    version_count: int,
    invalid_checksum_numbers: frozenset[int] = frozenset(),
) -> VerificationScenario:
    settings = _test_settings(object_store_root)
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    version_ids: list[UUID] = []
    job_ids: list[UUID] = []
    store = LocalObjectStore(settings.object_store_root)
    try:
        async with sessions.begin() as session:
            session.add(
                UserRecord(
                    id=actor_id,
                    display_name="Task 14B Synthetic Actor",
                    email=f"task14b-{actor_id}@example.test",
                    normalized_email=f"task14b-{actor_id}@example.test",
                    password_hash="synthetic-password-hash",
                    role=UserRole.OWNER,
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Task 14B Synthetic Workspace {workspace_id}",
                    kind=WorkspaceKind.PERSONAL,
                    created_by=actor_id,
                    expires_at=None,
                )
            )
            await session.flush()
            session.add(
                DocumentRecord(
                    id=document_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    name="public-synthetic.txt",
                    active_version_id=None,
                )
            )
            await session.flush()

            jobs = SqlAlchemyJobRepository(session)
            for number in range(1, version_count + 1):
                version_id = uuid4()
                stored = await store.put(
                    f"task14b/{workspace_id}/{document_id}/v{number}.txt",
                    _bytes_source(SYNTHETIC_PUBLIC_BYTES + str(number).encode()),
                )
                session.add(
                    AssetVersionRecord(
                        id=version_id,
                        document_id=document_id,
                        number=number,
                        object_key=stored.key,
                        sha256=(
                            "0" * 64
                            if number in invalid_checksum_numbers
                            else stored.sha256
                        ),
                        media_type="text/plain",
                        size=stored.size,
                        status=VersionStatus.STORED,
                    )
                )
                await session.flush()
                job = Job.create(
                    user_id=actor_id,
                    workspace_id=workspace_id,
                    asset_version_id=version_id,
                    type=JobType.VERIFY_ASSET,
                    idempotency_key=f"asset-version:{version_id}",
                )
                await jobs.add(job)
                version_ids.append(version_id)
                job_ids.append(job.id)
    finally:
        await engine.dispose()
    return VerificationScenario(
        settings=settings,
        actor_id=actor_id,
        workspace_id=workspace_id,
        document_id=document_id,
        version_ids=tuple(version_ids),
        job_ids=tuple(job_ids),
    )


async def _snapshot(scenario: VerificationScenario) -> VerificationSnapshot:
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            document = await session.get(DocumentRecord, scenario.document_id)
            versions = tuple(
                (
                    await session.scalars(
                        select(AssetVersionRecord)
                        .where(AssetVersionRecord.document_id == scenario.document_id)
                        .order_by(AssetVersionRecord.number)
                    )
                ).all()
            )
            jobs = tuple(
                (
                    await session.scalars(
                        select(JobRecord)
                        .where(JobRecord.id.in_(scenario.job_ids))
                        .order_by(JobRecord.asset_version_id)
                    )
                ).all()
            )
        assert document is not None
        jobs_by_version = {job.asset_version_id: job for job in jobs}
        ordered_jobs = tuple(jobs_by_version[version_id] for version_id in scenario.version_ids)
        return VerificationSnapshot(
            active_version_id=document.active_version_id,
            version_statuses=tuple(VersionStatus(version.status) for version in versions),
            job_statuses=tuple(JobStatus(job.status) for job in ordered_jobs),
            job_stages=tuple(job.stage for job in ordered_jobs),
        )
    finally:
        await engine.dispose()


async def _delete_scenario(scenario: VerificationScenario) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.id == scenario.workspace_id)
            )
            await session.execute(delete(UserRecord).where(UserRecord.id == scenario.actor_id))
    finally:
        await engine.dispose()


async def _assert_row_is_locked(settings: Settings, model: type[object], row_id: UUID) -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            with pytest.raises(OperationalError):
                await session.execute(
                    select(model).where(model.id == row_id).with_for_update(nowait=True)  # type: ignore[attr-defined]
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_asset_verification_accepts_the_stored_checksum(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256=stored.sha256,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )

    await verify_stored_asset(store, version)


@pytest.mark.asyncio
async def test_asset_verification_marks_checksum_mismatch_as_permanent(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256="0" * 64,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )

    with pytest.raises(AssetTaskError) as exc_info:
        await verify_stored_asset(store, version)

    assert exc_info.value.code == "checksum_mismatch"
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_asset_verification_marks_missing_object_as_retryable(tmp_path) -> None:
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key="missing/report.pdf",
        sha256="0" * 64,
        media_type="application/pdf",
        size=1,
        status=VersionStatus.STORED,
    )

    with pytest.raises(AssetTaskError) as exc_info:
        await verify_stored_asset(LocalObjectStore(tmp_path), version)

    assert exc_info.value.code == "object_unavailable"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_asset_workflow_persists_successful_terminal_state(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256=stored.sha256,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )
    job = Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"asset-version:{version.id}",
    )

    verified_asset_version_id = await AssetVerificationWorkflow(
        MemoryLifecycle(job, version), store
    ).run(job.id)

    assert verified_asset_version_id == version.id
    assert job.status is JobStatus.SUCCEEDED
    assert job.stage == "ready"


@pytest.mark.asyncio
async def test_asset_workflow_persists_stable_failure_code(tmp_path) -> None:
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key="missing/report.pdf",
        sha256="0" * 64,
        media_type="application/pdf",
        size=1,
        status=VersionStatus.STORED,
    )
    job = Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"asset-version:{version.id}",
    )

    with pytest.raises(AssetTaskError):
        await AssetVerificationWorkflow(
            MemoryLifecycle(job, version), LocalObjectStore(tmp_path)
        ).run(job.id)

    assert job.status is JobStatus.FAILED
    assert job.error_code == "object_unavailable"


@pytest.mark.asyncio
async def test_asset_workflow_does_not_repeat_a_completed_job(tmp_path) -> None:
    asset_version_id = uuid4()

    returned_id = await AssetVerificationWorkflow(
        CompletedLifecycle(asset_version_id), LocalObjectStore(tmp_path)
    ).run(uuid4())

    assert returned_id == asset_version_id


@pytest.mark.asyncio
async def test_verified_first_version_becomes_ready_and_active(tmp_path) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=1)
    try:
        verified_id = await create_asset_verification_workflow(scenario.settings).run(
            scenario.job_ids[0]
        )

        snapshot = await _snapshot(scenario)

        assert verified_id == scenario.version_ids[0]
        assert snapshot.active_version_id == scenario.version_ids[0]
        assert snapshot.version_statuses == (VersionStatus.READY,)
        assert snapshot.job_statuses == (JobStatus.SUCCEEDED,)
        assert snapshot.job_stages == ("ready",)
    finally:
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_higher_verified_version_replaces_the_active_version(tmp_path) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=2)
    workflow = create_asset_verification_workflow(scenario.settings)
    try:
        await workflow.run(scenario.job_ids[0])
        await workflow.run(scenario.job_ids[1])

        snapshot = await _snapshot(scenario)

        assert snapshot.active_version_id == scenario.version_ids[1]
        assert snapshot.version_statuses == (VersionStatus.READY, VersionStatus.READY)
        assert snapshot.job_stages == ("ready", "ready")
    finally:
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_delayed_older_verification_cannot_replace_a_newer_active_version(
    tmp_path,
) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=2)
    workflow = create_asset_verification_workflow(scenario.settings)
    try:
        await workflow.run(scenario.job_ids[1])
        await workflow.run(scenario.job_ids[0])

        snapshot = await _snapshot(scenario)

        assert snapshot.active_version_id == scenario.version_ids[1]
        assert snapshot.version_statuses == (VersionStatus.READY, VersionStatus.READY)
        assert snapshot.job_statuses == (JobStatus.SUCCEEDED, JobStatus.SUCCEEDED)
    finally:
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_failed_verification_preserves_status_and_active_version(tmp_path) -> None:
    scenario = await _seed_verification_scenario(
        tmp_path,
        version_count=2,
        invalid_checksum_numbers=frozenset({2}),
    )
    workflow = create_asset_verification_workflow(scenario.settings)
    try:
        await workflow.run(scenario.job_ids[0])
        with pytest.raises(AssetTaskError, match="recorded checksum"):
            await workflow.run(scenario.job_ids[1])

        snapshot = await _snapshot(scenario)

        assert snapshot.active_version_id == scenario.version_ids[0]
        assert snapshot.version_statuses == (VersionStatus.READY, VersionStatus.STORED)
        assert snapshot.job_statuses == (JobStatus.SUCCEEDED, JobStatus.FAILED)
    finally:
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_completed_job_redelivery_returns_the_same_version_without_regression(
    tmp_path,
) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=2)
    workflow = create_asset_verification_workflow(scenario.settings)
    try:
        first_result = await workflow.run(scenario.job_ids[0])
        await workflow.run(scenario.job_ids[1])
        redelivered_result = await workflow.run(scenario.job_ids[0])

        snapshot = await _snapshot(scenario)

        assert redelivered_result == first_result == scenario.version_ids[0]
        assert snapshot.active_version_id == scenario.version_ids[1]
        assert snapshot.version_statuses == (VersionStatus.READY, VersionStatus.READY)
        assert snapshot.job_statuses == (JobStatus.SUCCEEDED, JobStatus.SUCCEEDED)
        assert snapshot.job_stages == ("ready", "ready")
    finally:
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_success_transaction_locks_job_version_and_document(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=1)
    paused = asyncio.Event()
    release = asyncio.Event()
    original_flush = AsyncSession.flush

    async def flush_and_pause(
        session: AsyncSession,
        objects: object | None = None,
    ) -> None:
        await original_flush(session, objects)  # type: ignore[arg-type]
        if any(
            isinstance(record, JobRecord) and record.status == JobStatus.SUCCEEDED
            for record in session.identity_map.values()
        ):
            paused.set()
            await release.wait()

    monkeypatch.setattr(AsyncSession, "flush", flush_and_pause)
    verification = asyncio.create_task(
        create_asset_verification_workflow(scenario.settings).run(scenario.job_ids[0])
    )
    try:
        await asyncio.wait_for(paused.wait(), timeout=5)
        await _assert_row_is_locked(scenario.settings, JobRecord, scenario.job_ids[0])
        await _assert_row_is_locked(
            scenario.settings,
            AssetVersionRecord,
            scenario.version_ids[0],
        )
        await _assert_row_is_locked(
            scenario.settings,
            DocumentRecord,
            scenario.document_id,
        )
    finally:
        release.set()
        await verification
        await _delete_scenario(scenario)


@pytest.mark.asyncio
async def test_failed_success_commit_exposes_none_of_the_ready_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _seed_verification_scenario(tmp_path, version_count=1)
    original_session_factory = asset_tasks_module.create_session_factory
    factory_calls = 0

    class RollbackAtCommitBoundary:
        def __init__(self, real_factory) -> None:
            self.real_factory = real_factory

        @asynccontextmanager
        async def begin(self):
            async with self.real_factory() as session, session.begin():
                yield session
                await session.flush()
                raise RuntimeError("synthetic commit failure")

    def session_factory_with_failed_success_commit(engine):
        nonlocal factory_calls
        factory_calls += 1
        real_factory = original_session_factory(engine)
        if factory_calls == 2:
            return RollbackAtCommitBoundary(real_factory)
        return real_factory

    monkeypatch.setattr(
        asset_tasks_module,
        "create_session_factory",
        session_factory_with_failed_success_commit,
    )
    try:
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            await create_asset_verification_workflow(scenario.settings).run(
                scenario.job_ids[0]
            )

        snapshot = await _snapshot(scenario)

        assert snapshot.active_version_id is None
        assert snapshot.version_statuses == (VersionStatus.STORED,)
        assert snapshot.job_statuses == (JobStatus.RUNNING,)
        assert snapshot.job_stages == ("verifying_object",)
    finally:
        await _delete_scenario(scenario)
