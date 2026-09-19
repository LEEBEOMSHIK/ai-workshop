# ruff: noqa: F811
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.contracts import IndexDocument
from ai_workshop.labs.rag.indexing.resource_models import RagIndexAttemptRecord
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.indexing.tracking_service import prepare_tracked_index
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.stages import ProductionIndexingStage
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from tests.integration.labs.rag.indexing.test_resource_repository import seed_resource
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    _seed_official_ingestion,
    ensure_legacy_document_processing_profile,  # noqa: F401
    migrated_database,  # noqa: F401
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_uuid", [False, True, "commit", "confirmed"])
async def test_prepare_commits_reservation_before_io_and_preserves_uncertain_attempt(
    migrated_database,
    fail_after_uuid: bool | str,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        secret_key="x" * 32,
        rag_index_store_id="rag",
        rag_index_cluster_uuid="test-cluster",
        elasticsearch_index_prefix="test",
    )
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        document = IndexDocument(
            uuid4(),
            resource.projection_id,
            resource.asset_version_id,
            resource.workspace_id,
            None,
            (),
            "ready",
            "synthetic",
            (),
            "synthetic",
            (),
            (0.1, 0.2, 0.3),
            resource.build_id,
            resource.indexing_profile_id,
        )
        events = []

        async def lock_stage(session):
            events.append("lock")
            if fail_after_uuid == "commit" and events.count("lock") == 3:
                raise SQLAlchemyError("synthetic-private-SQL")

        class Adapter:
            async def prepare(self, current, documents, on_identity):
                events.append("io")
                async with sessions() as session:
                    attempts = list(
                        await session.scalars(
                            select(RagIndexAttemptRecord).where(
                                RagIndexAttemptRecord.build_id == resource.build_id,
                                RagIndexAttemptRecord.state == "open",
                            )
                        )
                    )
                    assert len(attempts) == 1 and attempts[0].state == "open"
                await on_identity("physical-one")
                if fail_after_uuid is True:
                    raise IndexTrackingError("rag_index_writer_unconfirmed")
                if fail_after_uuid == "confirmed":
                    from ai_workshop.labs.rag.indexing.tracked_elasticsearch import (
                        IndexPreparationFailed,
                    )

                    raise IndexPreparationFailed(
                        "rag_index_observation_failed",
                        writer_confirmed_ended=True,
                    )
                from ai_workshop.labs.rag.indexing.tracked_elasticsearch import (
                    TrackedIndexObservation,
                )

                return TrackedIndexObservation(True, "physical-one", 1, ())

        @asynccontextmanager
        async def adapters():
            yield Adapter()

        if fail_after_uuid:
            code = "observation_failed" if fail_after_uuid == "confirmed" else "writer_unconfirmed"
            with pytest.raises(IndexTrackingError, match=code):
                await prepare_tracked_index(
                    sessions, settings, resource.build_id, (document,), adapters, lock_stage
                )
        else:
            await prepare_tracked_index(
                sessions, settings, resource.build_id, (document,), adapters, lock_stage
            )
        async with sessions() as session:
            actual = await SqlAlchemyRagIndexRepository(session).get(resource.build_id)
            build = await session.get(RagIndexBuildRecord, resource.build_id)
            attempt = await session.scalar(
                select(RagIndexAttemptRecord).where(
                    RagIndexAttemptRecord.build_id == resource.build_id
                )
            )
            assert actual.index_uuid == "physical-one"
            assert attempt.state == (
                "open" if fail_after_uuid and fail_after_uuid != "confirmed" else "closed"
            )
            assert build.status == ("building" if fail_after_uuid else "prepared")
        assert events.index("lock") < events.index("io")
        if fail_after_uuid == "confirmed":
            fail_after_uuid = False
            await prepare_tracked_index(
                sessions,
                settings,
                resource.build_id,
                (document,),
                adapters,
                lock_stage,
            )
            async with sessions() as session:
                attempts = list(
                    await session.scalars(
                        select(RagIndexAttemptRecord).where(
                            RagIndexAttemptRecord.build_id == resource.build_id,
                        )
                    )
                )
                assert len(attempts) == 2
                assert all(attempt.state == "closed" for attempt in attempts)
        elif fail_after_uuid:
            with pytest.raises(IndexTrackingError, match="attempt_busy"):
                await prepare_tracked_index(
                    sessions, settings, resource.build_id, (document,), adapters, lock_stage
                )
            assert events.count("io") == 1
        else:
            with pytest.raises(IndexTrackingError, match="input_conflict"):
                await prepare_tracked_index(
                    sessions,
                    settings,
                    resource.build_id,
                    (replace(document, text="changed"),),
                    adapters,
                    lock_stage,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_build_requires_binding_and_registers_before_any_external_call(
    migrated_database,
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="registered-stage")
            asset = await session.get(AssetVersionRecord, seed.source.asset_version_id)
            asset.status = "ready"
            document = await session.get(DocumentRecord, seed.source.document_id)
            document.active_version_id = asset.id
            projection = await session.get(RagProjectionRecord, seed.projection_id)
            projection.status = ProjectionStatus.INDEXING
            profile_id = projection.indexing_profile_id
            ingestion = await session.get(RagIngestionJobRecord, seed.job_id)
            ingestion.embedding_count = 1

        async def resolve(*args, **kwargs):
            return SimpleNamespace(config=SimpleNamespace(dimension=3))

        monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)
        unset = Settings(_env_file=None, secret_key="x" * 32)
        stage = ProductionIndexingStage(unset, LocalObjectStore(tmp_path))
        with pytest.raises(IndexTrackingError, match="binding_mismatch"):
            await stage._ensure_build(sessions, seed.projection_id, profile_id)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(RagIndexBuildRecord).where(
                        RagIndexBuildRecord.projection_id == seed.projection_id
                    )
                )
                is None
            )
        configured = unset.model_copy(
            update={
                "rag_index_store_id": "rag",
                "rag_index_cluster_uuid": "test-cluster",
            }
        )
        stage = ProductionIndexingStage(configured, LocalObjectStore(tmp_path))
        build_id = await stage._ensure_build(sessions, seed.projection_id, profile_id)
        async with sessions() as session:
            resource = await SqlAlchemyRagIndexRepository(session).get(build_id)
            build = await session.get(RagIndexBuildRecord, build_id)
            assert resource.asset_version_id == seed.source.asset_version_id
            assert build.index_name == resource.index_name
            assert resource.index_uuid is None and resource.input_fingerprint is None
            assert build.status == "building"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_indexing_readiness_inventory_with_real_isolated_es(
    migrated_database,
    monkeypatch,
    tmp_path,
) -> None:
    from elasticsearch import AsyncElasticsearch

    from ai_workshop.labs.rag.chunking.contracts import ChunkingResult
    from ai_workshop.labs.rag.documents.models import RetrievalChunkRecord
    from ai_workshop.labs.rag.embeddings.contracts import EmbeddingResult, EmbeddingVector
    from ai_workshop.labs.rag.indexing.resource_inventory import RagIndexInventory
    from ai_workshop.labs.rag.indexing.tracked_elasticsearch import TrackedElasticsearchIndex
    from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
    from ai_workshop.labs.rag.ingestion.serialization import (
        serialize_chunking_result,
        serialize_embedding_result,
    )
    from ai_workshop.labs.rag.ingestion.stages import ProductionReadinessVerifier
    from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget
    from tests.integration.labs.rag.indexing.test_tracked_elasticsearch_live import _test_url
    from tests.unit.labs.rag.ingestion.test_embedding_stage import chunks, descriptor

    url = _test_url()
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    prefix = f"test-rag-stage-{uuid4().hex}"
    projection_id = None
    async with AsyncElasticsearch(url, max_retries=0) as client:
        try:
            cluster = (await client.info())["cluster_uuid"]
            settings = Settings(
                _env_file=None,
                secret_key="x" * 32,
                environment="test",
                database_url=migrated_database.database_url,
                elasticsearch_url=url,
                elasticsearch_index_prefix=prefix,
                rag_index_store_id="rag",
                rag_index_cluster_uuid=cluster,
                object_store_root=tmp_path,
            )
            store = LocalObjectStore(tmp_path)
            async with sessions.begin() as session:
                seed = await _seed_official_ingestion(session, label="live-stage")
                projection_id = seed.projection_id
                projection = await session.get(RagProjectionRecord, projection_id)
                profile_id = projection.indexing_profile_id
                projection.status = ProjectionStatus.INDEXING
                asset = await session.get(AssetVersionRecord, seed.source.asset_version_id)
                asset.status = "ready"
                document = await session.get(DocumentRecord, seed.source.document_id)
                document.active_version_id = asset.id
                generation = document.lifecycle_generation
                chunk = replace(
                    chunks("synthetic").chunks[0], id=uuid4(), projection_id=projection_id
                )
                session.add(
                    RetrievalChunkRecord(
                        id=chunk.id,
                        projection_id=projection_id,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        section_path=[],
                    )
                )
                embedding_descriptor = replace(
                    descriptor(), projection_id=projection_id, indexing_profile_id=profile_id
                )
                artifacts = (
                    ("chunk", serialize_chunking_result(ChunkingResult((chunk,), ()))),
                    (
                        "embedding",
                        serialize_embedding_result(
                            EmbeddingResult(
                                embedding_descriptor, (EmbeddingVector(chunk.id, (1.0, 0.0, 0.0)),)
                            )
                        ),
                    ),
                )
                ingestion = await session.get(RagIngestionJobRecord, seed.job_id)
                ingestion.parsed_element_count = ingestion.chunk_count = (
                    ingestion.embedding_count
                ) = 1
                for role, content in artifacts:

                    async def source(data=content):
                        yield data

                    stored = await store.put(f"{role}.json", source())
                    setattr(ingestion, f"{role}_object_key", stored.key)
                    setattr(ingestion, f"{role}_sha256", stored.sha256)

            async def resolve(*args, **kwargs):
                return SimpleNamespace(
                    config=SimpleNamespace(dimension=3), descriptor=embedding_descriptor
                )

            monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)
            await ProductionIndexingStage(settings, store).index(
                projection_id=projection_id,
                indexing_profile_id=profile_id,
            )
            verifier = ProductionReadinessVerifier(settings)
            assert (
                await verifier.verify(projection_id=projection_id, indexing_profile_id=profile_id)
            ).is_complete
            inspector = TrackedElasticsearchIndex(client, IndexBinding("rag", cluster))
            inventory = await RagIndexInventory(engine, inspector).collect(
                seed.source.workspace_id,
                (
                    DocumentTarget(
                        seed.source.document_id, generation, (seed.source.asset_version_id,)
                    ),
                ),
            )
            assert inventory.exhausted and inventory.supported and inventory.legacy_resolved
            assert len(inventory.resources) == 1
        finally:
            if projection_id is not None:
                async with sessions() as session:
                    build = await session.scalar(
                        select(RagIndexBuildRecord).where(
                            RagIndexBuildRecord.projection_id == projection_id,
                        )
                    )
                    if build is not None and build.index_name is not None:
                        assert build.index_name.startswith(prefix + "-")
                        await client.indices.delete(index=build.index_name, ignore_unavailable=True)
                        assert not await client.indices.exists(index=build.index_name)
            await engine.dispose()
