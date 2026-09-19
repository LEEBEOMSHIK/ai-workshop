from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.resource_inventory import RagIndexInventory
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import TrackedIndexObservation
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    Seed,
    _isolated_database_at,
    _seed_official_ingestion,
)
from tests.integration.publishing_support import IsolatedPublishingDatabase


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("head") as database:
        yield database


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    assert migrated_database.name.startswith("ai_workshop_publishing_")


class MissingIndex:
    async def observe(
        self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]
    ) -> TrackedIndexObservation:
        return TrackedIndexObservation(False, None, 0, ())


@pytest.mark.asyncio
@pytest.mark.parametrize("has_legacy_build", [False, True])
async def test_no_build_is_normal_but_unregistered_build_is_unresolved(
    migrated_database: IsolatedPublishingDatabase, has_legacy_build: bool
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        async with async_sessionmaker(engine).begin() as session:
            seed = await _seed_official_ingestion(session, label="index-inventory")
            if has_legacy_build:
                projection = await session.get(RagProjectionRecord, seed.projection_id)
                assert projection is not None
                session.add(
                    RagIndexBuildRecord(
                        id=uuid4(),
                        projection_id=projection.id,
                        document_processing_profile_id=projection.document_processing_profile_id,
                        indexing_profile_id=projection.indexing_profile_id,
                        status="building",
                        is_active=False,
                    )
                )
        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))
        result = await RagIndexInventory(engine, MissingIndex()).collect(
            seed.source.workspace_id, (target,)
        )
        assert result.resources == ()
        assert result.legacy_resolved is (not has_legacy_build)
        assert result.supported
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prepared_index_compares_exact_persisted_chunk_ids(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed, build_id = await registered(engine)
        chunk_id = uuid4()
        sessions = async_sessionmaker(engine)
        async with sessions.begin() as session:
            session.add(
                RetrievalChunkRecord(
                    id=chunk_id,
                    projection_id=seed.projection_id,
                    ordinal=0,
                    text="synthetic",
                    section_path=[],
                )
            )
            repository = SqlAlchemyRagIndexRepository(session)
            claim = await repository.reserve(
                build_id, "a" * 64, chunk_ids_sha256=index_chunk_ids_fingerprint((chunk_id,))
            )
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).observe_uuid(claim, "test-uuid")
        async with sessions.begin() as session:
            await session.execute(
                update(RagIndexBuildRecord)
                .where(RagIndexBuildRecord.id == build_id)
                .values(
                    index_name=f"synthetic-{build_id}",
                    status="prepared",
                    expected_document_count=1,
                    indexed_document_count=1,
                    vector_dimension=3,
                )
            )
            await session.execute(
                update(RagIngestionJobRecord)
                .where(RagIngestionJobRecord.job_id == seed.job_id)
                .values(chunk_count=1, embedding_count=1)
            )
            await SqlAlchemyRagIndexRepository(session).finish(claim, "prepared")

        class PresentIndex(MissingIndex):
            async def observe(self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]):
                return TrackedIndexObservation(True, "test-uuid", len(expected_chunk_ids), ())

        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))
        inventory = RagIndexInventory(engine, PresentIndex())
        original = await inventory.collect(seed.source.workspace_id, (target,))
        assert original.exhausted and original.legacy_resolved
        async with sessions.begin() as session:
            await session.execute(
                update(RetrievalChunkRecord)
                .where(RetrievalChunkRecord.id == chunk_id)
                .values(id=uuid4())
            )
        replaced = await inventory.collect(seed.source.workspace_id, (target,))
        assert not replaced.exhausted and not replaced.legacy_resolved
    finally:
        await engine.dispose()


async def registered(engine: AsyncEngine) -> tuple[Seed, UUID]:
    async with async_sessionmaker(engine).begin() as session:
        seed = await _seed_official_ingestion(session, label="registered-index-inventory")
        projection = await session.get(RagProjectionRecord, seed.projection_id)
        assert projection is not None
        build_id = uuid4()
        session.add(
            RagIndexBuildRecord(
                id=build_id,
                projection_id=projection.id,
                document_processing_profile_id=projection.document_processing_profile_id,
                indexing_profile_id=projection.indexing_profile_id,
                status="building",
                is_active=False,
            )
        )
        await session.flush()
        await session.execute(
            update(RagIngestionJobRecord)
            .where(RagIngestionJobRecord.job_id == seed.job_id)
            .values(index_build_id=build_id)
        )
        await SqlAlchemyRagIndexRepository(session).register(
            build_id,
            IndexBinding("synthetic", "inventory-cluster"),
            IndexDescriptor(3, "cosine"),
            f"synthetic-{build_id}",
            "synthetic-active",
        )
    return seed, build_id


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["reserved", "open", "missing_relation"])
async def test_registered_absence_open_attempt_and_missing_relation(
    migrated_database: IsolatedPublishingDatabase, phase: str
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed, build_id = await registered(engine)
        async with async_sessionmaker(engine).begin() as session:
            if phase == "open":
                await SqlAlchemyRagIndexRepository(session).reserve(
                    build_id, "a" * 64, chunk_ids_sha256=index_chunk_ids_fingerprint(())
                )
            elif phase == "missing_relation":
                await session.execute(
                    delete(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.participant == "rag_index_resources",
                        AssetSourceRelationRecord.resource_id == build_id,
                    )
                )
        result = await RagIndexInventory(engine, MissingIndex()).collect(
            seed.source.workspace_id,
            (DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,)),),
        )
        assert result.resources[0].resource_id == build_id
        assert result.exhausted is (phase != "open")
        assert result.legacy_resolved is (phase != "missing_relation")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_generation_change_during_es_observation_is_rejected(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed, _ = await registered(engine)

        class ChangingInspector(MissingIndex):
            async def observe(self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]):
                async with async_sessionmaker(engine).begin() as session:
                    await session.execute(
                        update(DocumentRecord)
                        .where(DocumentRecord.id == seed.source.document_id)
                        .values(lifecycle_generation=2)
                    )
                return await super().observe(resource, expected_chunk_ids)

        with pytest.raises(IndexTrackingError, match="^rag_index_inventory_changed$"):
            await RagIndexInventory(engine, ChangingInspector()).collect(
                seed.source.workspace_id,
                (DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,)),),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["workspace", "generation", "versions"])
async def test_exact_source_scope_is_required(
    migrated_database: IsolatedPublishingDatabase,
    invalid: str,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed, _ = await registered(engine)
        with pytest.raises(IndexTrackingError, match="^rag_index_inventory_incomplete$"):
            await RagIndexInventory(engine, MissingIndex()).collect(
                uuid4() if invalid == "workspace" else seed.source.workspace_id,
                (
                    DocumentTarget(
                        seed.source.document_id,
                        2 if invalid == "generation" else 1,
                        (uuid4(),) if invalid == "versions" else (seed.source.asset_version_id,),
                    ),
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_all_versions_are_required_even_when_only_one_has_a_build(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed, build_id = await registered(engine)
        second_version = uuid4()
        async with async_sessionmaker(engine).begin() as session:
            session.add(
                AssetVersionRecord(
                    id=second_version,
                    document_id=seed.source.document_id,
                    number=2,
                    object_key=f"synthetic/{second_version}",
                    sha256="b" * 64,
                    media_type="text/plain",
                    size=2,
                    status="stored",
                )
            )
        inventory = RagIndexInventory(engine, MissingIndex())
        with pytest.raises(IndexTrackingError, match="^rag_index_inventory_incomplete$"):
            await inventory.collect(
                seed.source.workspace_id,
                (DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,)),),
            )
        result = await inventory.collect(
            seed.source.workspace_id,
            (
                DocumentTarget(
                    seed.source.document_id, 1, (seed.source.asset_version_id, second_version)
                ),
            ),
        )
        assert result.exhausted and result.legacy_resolved
        assert result.resources[0].resource_id == build_id
    finally:
        await engine.dispose()
