# ruff: noqa: F811
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.config import Settings
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.indexing.recovery import SqlAlchemyRagAliasParityReconciler
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import TrackedIndexObservation
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.stages import ProductionReadinessVerifier
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from tests.integration.labs.rag.indexing.test_resource_repository import seed_resource
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    ensure_legacy_document_processing_profile,  # noqa: F401
    migrated_database,  # noqa: F401
)


async def prepared_resource(session):
    resource = await seed_resource(session)
    chunk_id = uuid4()
    session.add(
        RetrievalChunkRecord(
            id=chunk_id,
            projection_id=resource.projection_id,
            ordinal=0,
            text="synthetic",
            section_path=[],
        )
    )
    repository = SqlAlchemyRagIndexRepository(session)
    claim = await repository.reserve(
        resource.build_id, "a" * 64, chunk_ids_sha256=index_chunk_ids_fingerprint((chunk_id,))
    )
    claim = await repository.observe_uuid(claim, "test-physical")
    await repository.finish(claim, "prepared")
    build = await session.get(RagIndexBuildRecord, resource.build_id)
    build.status, build.index_name, build.vector_dimension = "prepared", resource.index_name, 3
    build.expected_document_count = build.indexed_document_count = 1
    projection = await session.get(RagProjectionRecord, resource.projection_id)
    projection.status = ProjectionStatus.INDEXING
    version = await session.get(AssetVersionRecord, resource.asset_version_id)
    version.status = "ready"
    document = await session.get(DocumentRecord, resource.document_id)
    document.active_version_id = version.id
    ingestion = await session.get(RagIngestionJobRecord, resource.job_id)
    ingestion.parsed_element_count = ingestion.chunk_count = ingestion.embedding_count = 1
    await session.flush()
    return await repository.get(resource.build_id)


class Alias:
    def __init__(self):
        self.targets = ()
        self.calls = 0

    async def replace_active_targets(self, alias, targets):
        self.targets = tuple(sorted(targets))
        self.calls += 1
        return True

    async def reconcile_active_targets(self, alias, targets):
        return await self.replace_active_targets(alias, targets)

    async def active_targets(self, alias):
        return self.targets


def adapters(alias):
    @asynccontextmanager
    async def aliases():
        yield alias

    class Inspector:
        async def observe(self, resource, expected_chunk_ids):
            return TrackedIndexObservation(
                True,
                resource.index_uuid,
                len(expected_chunk_ids),
                (resource.alias,) if resource.index_name in alias.targets else (),
            )

    @asynccontextmanager
    async def tracked():
        yield Inspector()

    return aliases, tracked


async def cluster_probe():
    return "test-cluster"


def settings(database):
    return Settings(
        _env_file=None,
        secret_key="x" * 32,
        environment="test",
        database_url=database.database_url,
        elasticsearch_index_prefix="test",
        rag_index_store_id="rag",
        rag_index_cluster_uuid="test-cluster",
    )


@pytest.mark.asyncio
async def test_activation_revision_noop_and_ready_alias_revalidation(
    migrated_database,
    monkeypatch,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)

        async def resolve(*args, **kwargs):
            return SimpleNamespace(config=SimpleNamespace(dimension=3))

        monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)
        alias = Alias()
        aliases, tracked = adapters(alias)
        verifier = ProductionReadinessVerifier(
            settings(migrated_database),
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        arguments = dict(
            projection_id=resource.projection_id, indexing_profile_id=resource.indexing_profile_id
        )
        assert (await verifier.verify(**arguments)).is_complete
        async with sessions() as session:
            current = await SqlAlchemyRagIndexRepository(session).get(resource.build_id)
            assert current.revision == resource.revision + 1
        assert (await verifier.verify(**arguments)).is_complete
        async with sessions() as session:
            assert (
                await SqlAlchemyRagIndexRepository(session).get(resource.build_id)
            ).revision == current.revision
        alias.targets = ()
        with pytest.raises(IndexTrackingError, match="identity_conflict"):
            await verifier.verify(**arguments)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parity_checks_removed_active_target_binding_and_updates_revision(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)
            build = await session.get(RagIndexBuildRecord, resource.build_id)
            build.status, build.is_active = "ready", True
            projection = await session.get(RagProjectionRecord, resource.projection_id)
            projection.status = ProjectionStatus.READY
            document = await session.get(DocumentRecord, resource.document_id)
            document.active_version_id = None
        alias = Alias()
        alias.targets = (resource.index_name,)
        aliases, tracked = adapters(alias)
        wrong = settings(migrated_database).model_copy(update={"rag_index_cluster_uuid": "changed"})
        reconciler = SqlAlchemyRagAliasParityReconciler(
            wrong,
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        result = await reconciler.run_once(profile_id=resource.indexing_profile_id)
        assert result.failed == 1
        assert result.failures[0].error_code == "rag_index_binding_mismatch"
        assert alias.calls == 0
        reconciler = SqlAlchemyRagAliasParityReconciler(
            settings(migrated_database),
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        result = await reconciler.run_once(profile_id=resource.indexing_profile_id)
        assert result.failed == 0 and alias.targets == ()
        async with sessions() as session:
            build = await session.get(RagIndexBuildRecord, resource.build_id)
            current = await SqlAlchemyRagIndexRepository(session).get(resource.build_id)
            assert not build.is_active
            assert current.revision == resource.revision + 1
        assert (await reconciler.run_once(profile_id=resource.indexing_profile_id)).failed == 0
        async with sessions() as session:
            assert (
                await SqlAlchemyRagIndexRepository(session).get(resource.build_id)
            ).revision == current.revision
    finally:
        await engine.dispose()
