import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from elasticsearch import AsyncElasticsearch
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.recovery import (
    RagAliasParityError,
    SqlAlchemyRagAliasParityReconciler,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _AliasParityFixture:
    owner_id: UUID
    workspace_id: UUID
    profile_id: UUID
    document_ids: tuple[UUID, UUID]
    asset_ids: tuple[UUID, UUID]
    projection_ids: tuple[UUID, UUID]
    build_ids: tuple[UUID, UUID]
    index_names: tuple[str, str]


async def _seed_alias_parity_fixture(settings: Settings) -> _AliasParityFixture:
    owner_id = uuid4()
    workspace_id = uuid4()
    profile_id = uuid4()
    document_ids = (uuid4(), uuid4())
    asset_ids = (uuid4(), uuid4())
    projection_ids = (uuid4(), uuid4())
    build_ids = (uuid4(), uuid4())
    descriptor = IndexDescriptor(3, "cosine")
    index_names = tuple(
        descriptor.concrete_index_name(
            settings.elasticsearch_index_prefix,
            profile_id,
            build_id,
        )
        for build_id in build_ids
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            session.add(
                UserRecord(
                    id=owner_id,
                    display_name="Synthetic Alias Parity Owner",
                    email=f"alias-parity-{owner_id}@example.test",
                    normalized_email=f"alias-parity-{owner_id}@example.test",
                    password_hash="synthetic-password-hash",
                    role="owner",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Synthetic Alias Parity Workspace {workspace_id}",
                    kind="personal",
                    created_by=owner_id,
                    expires_at=None,
                )
            )
            session.add(
                ProfileRecord(
                    id=profile_id,
                    kind="indexing",
                    name=f"synthetic-alias-parity-{profile_id}",
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
                )
            )
            await session.flush()
            for position in range(2):
                session.add(
                    DocumentRecord(
                        id=document_ids[position],
                        workspace_id=workspace_id,
                        folder_id=None,
                        name=f"alias-parity-{position}.txt",
                        active_version_id=None,
                    )
                )
            await session.flush()
            for position in range(2):
                session.add(
                    AssetVersionRecord(
                        id=asset_ids[position],
                        document_id=document_ids[position],
                        number=1,
                        object_key=f"synthetic/alias-parity-{asset_ids[position]}.txt",
                        sha256=("a" if position == 0 else "b") * 64,
                        media_type="text/plain",
                        size=20 + position,
                        status="ready",
                    )
                )
            await session.flush()
            for position in range(2):
                document = await session.get(DocumentRecord, document_ids[position])
                assert document is not None
                document.active_version_id = asset_ids[position]
                session.add(
                    RagProjectionRecord(
                        id=projection_ids[position],
                        asset_version_id=asset_ids[position],
                        indexing_profile_id=profile_id,
                        status="ready",
                    )
                )
            await session.flush()
            for position in range(2):
                build = RagIndexBuildRecord(
                    id=build_ids[position],
                    projection_id=projection_ids[position],
                    indexing_profile_id=profile_id,
                    index_name=index_names[position],
                    expected_document_count=1,
                    indexed_document_count=1,
                    vector_dimension=3,
                    status="ready",
                    is_active=False,
                )
                session.add(build)
                job = Job.create(
                    user_id=owner_id,
                    workspace_id=workspace_id,
                    asset_version_id=asset_ids[position],
                    type=JobType.RAG_INGESTION,
                    idempotency_key=f"alias-parity:{asset_ids[position]}:{profile_id}",
                )
                job.start(stage="indexing")
                job.succeed(stage="ready")
                await SqlAlchemyJobRepository(session).add(job)
                session.add(
                    RagIngestionJobRecord(
                        job_id=job.id,
                        projection_id=projection_ids[position],
                        asset_version_id=asset_ids[position],
                        indexing_profile_id=profile_id,
                        requested_by=owner_id,
                        parsed_object_key=None,
                        parsed_sha256=None,
                        chunk_object_key=None,
                        chunk_sha256=None,
                        embedding_object_key=None,
                        embedding_sha256=None,
                        index_build_id=build_ids[position],
                        parsed_element_count=1,
                        chunk_count=1,
                        embedding_count=1,
                        indexed_document_count=1,
                        index_alias_verified=True,
                    )
                )
            await session.flush()
    finally:
        await engine.dispose()
    return _AliasParityFixture(
        owner_id,
        workspace_id,
        profile_id,
        document_ids,
        asset_ids,
        projection_ids,
        build_ids,
        index_names,
    )


async def _delete_alias_parity_fixture(
    settings: Settings, fixture: _AliasParityFixture
) -> None:
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
            await session.execute(
                delete(UserRecord).where(UserRecord.id == fixture.owner_id)
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_periodic_alias_parity_recovers_commit_loss_supersession_and_empty_set() -> None:
    base = get_settings()
    settings = base.model_copy(
        update={"elasticsearch_index_prefix": f"rag-alias-parity-{uuid4().hex}"}
    )
    fixture = await _seed_alias_parity_fixture(settings)
    client: AsyncElasticsearch = create_elasticsearch(settings)
    delegate = ElasticsearchSearchIndex(client)
    descriptor = IndexDescriptor(3, "cosine")
    alias = descriptor.active_alias(
        settings.elasticsearch_index_prefix,
        fixture.profile_id,
    )
    commit_failed = False
    listener_armed = False

    def fail_first_commit(_connection) -> None:
        nonlocal commit_failed
        if not commit_failed:
            commit_failed = True
            raise OperationalError(
                "synthetic alias parity commit failure",
                {},
                OSError("connection lost"),
            )

    class ArmCommitFailureAfterAlias:
        async def reconcile_active_targets(
            self, alias: str, index_names: Sequence[str]
        ) -> bool:
            nonlocal listener_armed
            acknowledged = await delegate.reconcile_active_targets(alias, index_names)
            if acknowledged and not listener_armed:
                event.listen(Engine, "commit", fail_first_commit)
                listener_armed = True
            return acknowledged

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            return await delegate.active_targets(alias)

    armed_index = ArmCommitFailureAfterAlias()

    @asynccontextmanager
    async def armed_session() -> AsyncIterator[ArmCommitFailureAfterAlias]:
        yield armed_index

    @asynccontextmanager
    async def normal_session() -> AsyncIterator[ElasticsearchSearchIndex]:
        yield delegate

    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        for position in range(2):
            await delegate.create(
                descriptor.for_index(
                    fixture.index_names[position],
                    indexing_profile_id=fixture.profile_id,
                    index_build_id=fixture.build_ids[position],
                    projection_id=fixture.projection_ids[position],
                )
            )

        failed = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=armed_session,
        ).run_once(profile_id=fixture.profile_id)
        assert (failed.claimed, failed.reconciled, failed.failed) == (1, 0, 1)
        assert failed.failures[0].error_code == "alias_parity_database_transient"
        assert failed.failures[0].retryable is True
        assert await delegate.active_targets(alias) == tuple(sorted(fixture.index_names))
        async with sessions() as session:
            flags_after_rollback = dict(
                (
                    await session.execute(
                        select(RagIndexBuildRecord.id, RagIndexBuildRecord.is_active)
                        .where(RagIndexBuildRecord.id.in_(fixture.build_ids))
                    )
                ).all()
            )
        assert flags_after_rollback == {
            fixture.build_ids[0]: False,
            fixture.build_ids[1]: False,
        }
        assert commit_failed is True
        event.remove(Engine, "commit", fail_first_commit)
        listener_armed = False

        replacement_asset_id = uuid4()
        async with sessions.begin() as session:
            first_document = await session.get(
                DocumentRecord, fixture.document_ids[0]
            )
            assert first_document is not None
            session.add(
                AssetVersionRecord(
                    id=replacement_asset_id,
                    document_id=first_document.id,
                    number=2,
                    object_key=f"synthetic/alias-parity-{replacement_asset_id}.txt",
                    sha256="c" * 64,
                    media_type="text/plain",
                    size=22,
                    status="ready",
                )
            )
            await session.flush()
            first_document.active_version_id = replacement_asset_id

        recovered = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=normal_session,
        ).run_once(profile_id=fixture.profile_id)
        assert (recovered.claimed, recovered.reconciled, recovered.failed) == (1, 1, 0)
        assert await delegate.active_targets(alias) == (fixture.index_names[1],)
        async with sessions() as session:
            flags_after_supersession = dict(
                (
                    await session.execute(
                        select(RagIndexBuildRecord.id, RagIndexBuildRecord.is_active)
                        .where(RagIndexBuildRecord.id.in_(fixture.build_ids))
                    )
                ).all()
            )
        assert flags_after_supersession == {
            fixture.build_ids[0]: False,
            fixture.build_ids[1]: True,
        }

        async with sessions.begin() as session:
            second_document = await session.get(
                DocumentRecord, fixture.document_ids[1]
            )
            assert second_document is not None
            second_document.active_version_id = None

        emptied = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=normal_session,
        ).run_once(profile_id=fixture.profile_id)
        assert (emptied.claimed, emptied.reconciled, emptied.failed) == (1, 1, 0)
        assert await delegate.active_targets(alias) == ()
        async with sessions() as session:
            flags_after_empty = dict(
                (
                    await session.execute(
                        select(RagIndexBuildRecord.id, RagIndexBuildRecord.is_active)
                        .where(RagIndexBuildRecord.id.in_(fixture.build_ids))
                    )
                ).all()
            )
        assert flags_after_empty == {
            fixture.build_ids[0]: False,
            fixture.build_ids[1]: False,
        }
    finally:
        if listener_armed:
            event.remove(Engine, "commit", fail_first_commit)
        try:
            await client.indices.delete(
                index=",".join(fixture.index_names),
                ignore_unavailable=True,
            )
        finally:
            await client.close()
        await engine.dispose()
        await _delete_alias_parity_fixture(settings, fixture)


@pytest.mark.asyncio
async def test_membership_added_while_source_locks_are_acquired_skips_alias_call() -> None:
    settings = get_settings().model_copy(
        update={"elasticsearch_index_prefix": f"rag-membership-race-{uuid4().hex}"}
    )
    fixture = await _seed_alias_parity_fixture(settings)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    authoritative_query_seen = asyncio.Event()
    calls: list[tuple[str, tuple[str, ...]]] = []

    class RecordingIndex:
        async def reconcile_active_targets(
            self, alias: str, index_names: Sequence[str]
        ) -> bool:
            calls.append((alias, tuple(index_names)))
            return True

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            del alias
            return ()

    @asynccontextmanager
    async def recording_session() -> AsyncIterator[RecordingIndex]:
        yield RecordingIndex()

    def observe_authoritative_query(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if (
            statement.lstrip().startswith("SELECT asset_versions.id")
            and "documents.active_version_id = asset_versions.id" in statement
        ):
            authoritative_query_seen.set()

    try:
        async with sessions.begin() as session:
            second_document = await session.get(
                DocumentRecord, fixture.document_ids[1]
            )
            assert second_document is not None
            second_document.active_version_id = None

        event.listen(Engine, "after_cursor_execute", observe_authoritative_query)
        async with sessions.begin() as blocker:
            locked = await blocker.scalar(
                select(AssetVersionRecord)
                .where(AssetVersionRecord.id == fixture.asset_ids[0])
                .with_for_update()
            )
            assert locked is not None
            second_document = await blocker.get(
                DocumentRecord, fixture.document_ids[1]
            )
            assert second_document is not None
            second_document.active_version_id = fixture.asset_ids[1]
            task = asyncio.create_task(
                SqlAlchemyRagAliasParityReconciler(
                    settings,
                    search_index_session=recording_session,
                ).run_once(profile_id=fixture.profile_id)
            )
            await asyncio.wait_for(authoritative_query_seen.wait(), timeout=5)

        result = await asyncio.wait_for(task, timeout=5)
        assert (result.claimed, result.reconciled, result.failed) == (1, 0, 1)
        assert result.failures[0].error_code == "alias_parity_membership_changed"
        assert result.failures[0].retryable is True
        assert calls == []
    finally:
        event.remove(Engine, "after_cursor_execute", observe_authoritative_query)
        await engine.dispose()
        await _delete_alias_parity_fixture(settings, fixture)


@pytest.mark.asyncio
async def test_failed_profile_does_not_block_later_profile_convergence() -> None:
    settings = get_settings().model_copy(
        update={"elasticsearch_index_prefix": f"rag-profile-fairness-{uuid4().hex}"}
    )
    fixture = await _seed_alias_parity_fixture(settings)
    healthy_profile_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    calls: list[str] = []
    observed: dict[str, tuple[str, ...]] = {}

    class PartiallyFailingIndex:
        async def reconcile_active_targets(
            self, alias: str, index_names: Sequence[str]
        ) -> bool:
            calls.append(alias)
            if str(fixture.profile_id) in alias:
                raise RagAliasParityError(
                    "alias_parity_search_transient",
                    "Synthetic profile-scoped search outage.",
                    retryable=True,
                )
            observed[alias] = tuple(index_names)
            return True

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            return observed.get(alias, ())

    partially_failing = PartiallyFailingIndex()

    @asynccontextmanager
    async def partially_failing_session() -> AsyncIterator[PartiallyFailingIndex]:
        yield partially_failing

    try:
        async with sessions.begin() as session:
            session.add(
                ProfileRecord(
                    id=healthy_profile_id,
                    kind="indexing",
                    name=f"synthetic-healthy-profile-{healthy_profile_id}",
                    version=1,
                    config={},
                    evaluation_state="draft",
                    is_default=False,
                )
            )

        result = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=partially_failing_session,
        ).run_once()

        assert result.claimed >= 2
        assert (result.reconciled, result.failed) == (result.claimed - 1, 1)
        assert result.failures[0].profile_id == fixture.profile_id
        assert result.failures[0].error_code == "alias_parity_search_transient"
        failed_call = next(
            position
            for position, alias in enumerate(calls)
            if str(fixture.profile_id) in alias
        )
        healthy_call = next(
            position
            for position, alias in enumerate(calls)
            if str(healthy_profile_id) in alias
        )
        assert healthy_call > failed_call
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ProfileRecord).where(ProfileRecord.id == healthy_profile_id)
            )
        await engine.dispose()
        await _delete_alias_parity_fixture(settings, fixture)


@pytest.mark.asyncio
async def test_keyset_pages_reach_101st_profile_after_first_page_failure() -> None:
    settings = get_settings().model_copy(
        update={"elasticsearch_index_prefix": f"rag-keyset-fairness-{uuid4().hex}"}
    )
    profile_ids = tuple(UUID(int=value) for value in range(1, 101)) + (
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    first_profile_id = profile_ids[0]
    last_profile_id = profile_ids[-1]
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    build_id = uuid4()
    descriptor = IndexDescriptor(3, "cosine")
    index_name = descriptor.concrete_index_name(
        settings.elasticsearch_index_prefix,
        last_profile_id,
        build_id,
    )
    first_alias = descriptor.active_alias(
        settings.elasticsearch_index_prefix,
        first_profile_id,
    )
    last_alias = descriptor.active_alias(
        settings.elasticsearch_index_prefix,
        last_profile_id,
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client: AsyncElasticsearch = create_elasticsearch(settings)
    delegate = ElasticsearchSearchIndex(client)
    calls: list[str] = []

    class FailFirstProfileIndex:
        async def reconcile_active_targets(
            self, alias: str, index_names: Sequence[str]
        ) -> bool:
            calls.append(alias)
            if alias == first_alias:
                raise RagAliasParityError(
                    "alias_parity_search_transient",
                    "Synthetic first-page profile failure.",
                    retryable=True,
                )
            return await delegate.reconcile_active_targets(alias, index_names)

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            return await delegate.active_targets(alias)

    failing_index = FailFirstProfileIndex()

    @asynccontextmanager
    async def failing_session() -> AsyncIterator[FailFirstProfileIndex]:
        yield failing_index

    try:
        async with sessions.begin() as session:
            session.add(
                UserRecord(
                    id=owner_id,
                    display_name="Synthetic Keyset Fairness Owner",
                    email=f"keyset-fairness-{owner_id}@example.test",
                    normalized_email=f"keyset-fairness-{owner_id}@example.test",
                    password_hash="synthetic-password-hash",
                    role="owner",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Synthetic Keyset Fairness Workspace {workspace_id}",
                    kind="personal",
                    created_by=owner_id,
                    expires_at=None,
                )
            )
            session.add_all(
                ProfileRecord(
                    id=profile_id,
                    kind="indexing",
                    name=f"synthetic-keyset-fairness-{profile_id}",
                    version=1,
                    config={},
                    evaluation_state="draft",
                    is_default=False,
                )
                for profile_id in profile_ids
            )
            await session.flush()
            session.add(
                DocumentRecord(
                    id=document_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    name="keyset-fairness.txt",
                    active_version_id=None,
                )
            )
            await session.flush()
            session.add(
                AssetVersionRecord(
                    id=asset_version_id,
                    document_id=document_id,
                    number=1,
                    object_key=f"synthetic/keyset-fairness-{asset_version_id}.txt",
                    sha256="d" * 64,
                    media_type="text/plain",
                    size=24,
                    status="ready",
                )
            )
            await session.flush()
            document = await session.get(DocumentRecord, document_id)
            assert document is not None
            document.active_version_id = asset_version_id
            session.add(
                RagProjectionRecord(
                    id=projection_id,
                    asset_version_id=asset_version_id,
                    indexing_profile_id=last_profile_id,
                    status="ready",
                )
            )
            await session.flush()
            session.add(
                RagIndexBuildRecord(
                    id=build_id,
                    projection_id=projection_id,
                    indexing_profile_id=last_profile_id,
                    index_name=index_name,
                    expected_document_count=1,
                    indexed_document_count=1,
                    vector_dimension=3,
                    status="ready",
                    is_active=False,
                )
            )

        await delegate.create(
            descriptor.for_index(
                index_name,
                indexing_profile_id=last_profile_id,
                index_build_id=build_id,
                projection_id=projection_id,
            )
        )
        result = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=failing_session,
            batch_size=100,
        ).run_once()

        assert first_alias in calls
        assert last_alias in calls
        assert calls.index(last_alias) > calls.index(first_alias)
        assert result.claimed >= 101
        assert result.failed == 1
        assert result.reconciled == result.claimed - 1
        assert result.failures[0].profile_id == first_profile_id
        assert await delegate.active_targets(last_alias) == (index_name,)
        async with sessions() as session:
            last_build = await session.get(RagIndexBuildRecord, build_id)
        assert last_build is not None and last_build.is_active is True

        calls.clear()
        exact = await SqlAlchemyRagAliasParityReconciler(
            settings,
            search_index_session=failing_session,
            batch_size=1,
        ).run_once(profile_id=last_profile_id)
        assert (exact.claimed, exact.reconciled, exact.failed) == (1, 1, 0)
        assert calls == [last_alias]
    finally:
        try:
            await client.indices.delete(index=index_name, ignore_unavailable=True)
        finally:
            await client.close()
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id)
            )
            await session.execute(
                delete(ProfileRecord).where(ProfileRecord.id.in_(profile_ids))
            )
            await session.execute(delete(UserRecord).where(UserRecord.id == owner_id))
        await engine.dispose()
