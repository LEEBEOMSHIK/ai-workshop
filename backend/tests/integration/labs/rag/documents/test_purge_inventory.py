from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from threading import Event, Thread
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.documents.provenance import (
    RAG_DERIVED_ARTIFACT_RELATION,
    RAG_DOCUMENT_SQL_PARTICIPANT,
    RAG_PROJECTION_BUNDLE_KIND,
)
from ai_workshop.labs.rag.documents.purge_inventory import (
    RagDocumentSqlInventory,
    RagDocumentSqlInventoryError,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("head") as database:
        yield database


@pytest.fixture
async def engine(
    migrated_database: IsolatedPublishingDatabase,
) -> AsyncIterator[AsyncEngine]:
    value = create_async_engine(migrated_database.database_url)
    try:
        yield value
    finally:
        await value.dispose()


@dataclass(frozen=True, slots=True)
class Seed:
    workspace_id: UUID
    document_id: UUID
    generation: int
    version_ids: tuple[UUID, ...]
    profile_id: UUID

    @property
    def target(self) -> DocumentTarget:
        return DocumentTarget(self.document_id, self.generation, self.version_ids)


async def _seed_source(
    session: AsyncSession,
    *,
    label: str,
    version_count: int = 2,
) -> Seed:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    profile_id = uuid4()
    generation = 7
    email = f"rag-inventory-{owner_id}@example.test"
    session.add(
        UserRecord(
            id=owner_id,
            display_name=f"Synthetic inventory owner {label}",
            email=email,
            normalized_email=email,
            password_hash="synthetic-password-hash",
            role="owner",
            is_active=True,
        )
    )
    await session.flush()
    session.add(
        WorkspaceRecord(
            id=workspace_id,
            name=f"Synthetic inventory workspace {label}",
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
                name=f"private-{label}.txt",
                active_version_id=None,
                lifecycle_generation=generation,
            ),
            ProfileRecord(
                id=profile_id,
                kind="indexing",
                name=f"synthetic-inventory-{profile_id}",
                version=1,
                config={"kind": "synthetic"},
                evaluation_state="draft",
                is_default=False,
            ),
        ]
    )
    await session.flush()
    version_ids = tuple(uuid4() for _ in range(version_count))
    session.add_all(
        [
            AssetVersionRecord(
                id=version_id,
                document_id=document_id,
                number=number,
                object_key=f"private/inventory/{version_id}.txt",
                sha256=f"{number:x}" * 64,
                media_type="text/plain",
                size=number,
                status="stored",
            )
            for number, version_id in enumerate(version_ids, start=1)
        ]
    )
    await session.flush()
    return Seed(workspace_id, document_id, generation, version_ids, profile_id)


async def _add_projection(
    session: AsyncSession,
    seed: Seed,
    *,
    version_index: int,
    status: str,
    revision: int | None = 1,
    register: bool = True,
    with_children: bool = False,
) -> UUID:
    projection_id = uuid4()
    session.add(
        RagProjectionRecord(
            id=projection_id,
            asset_version_id=seed.version_ids[version_index],
            document_processing_profile_id=seed.profile_id,
            indexing_profile_id=seed.profile_id,
            status=status,
            content_revision=revision,
        )
    )
    await session.flush()
    if register and revision is not None:
        session.add(
            AssetSourceRelationRecord(
                workspace_id=seed.workspace_id,
                document_id=seed.document_id,
                asset_version_id=seed.version_ids[version_index],
                participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                kind=RAG_PROJECTION_BUNDLE_KIND,
                resource_id=projection_id,
                resource_revision=revision,
                relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
            )
        )
    if with_children:
        element_id = uuid4()
        chunk_id = uuid4()
        session.add(
            StructuralElementRecord(
                id=element_id,
                projection_id=projection_id,
                ordinal=0,
                kind="paragraph",
                text="private element body",
                section_path=["Private"],
                page=1,
                char_start=0,
                char_end=20,
                bbox=None,
                parser_name="synthetic",
                parser_version="1",
                confidence=1.0,
                source_kind="normalized_text",
                source_part="private/path",
                image_sha256="f" * 64,
                table_cell=None,
                evidence_eligible=True,
                warnings=[],
            )
        )
        session.add(
            RetrievalChunkRecord(
                id=chunk_id,
                projection_id=projection_id,
                ordinal=0,
                text="private chunk body",
                section_path=["Private"],
            )
        )
        await session.flush()
        session.add(
            EvidenceUnitRecord(
                id=uuid4(),
                projection_id=projection_id,
                retrieval_chunk_id=chunk_id,
                ordinal=0,
                text="private evidence body",
                element_id=element_id,
                page=1,
                char_start=0,
                char_end=20,
                bbox=None,
                source_kind="normalized_text",
                source_part="private/path",
                image_sha256="e" * 64,
                table_cell=None,
            )
        )
    await session.flush()
    return projection_id


@pytest.mark.asyncio
async def test_collects_all_versions_and_statuses_in_body_free_read_only_snapshot(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    statements: list[str] = []
    async with sessions.begin() as session:
        seed = await _seed_source(session, label="complete", version_count=3)
        first_projection = await _add_projection(
            session, seed, version_index=0, status="pending", with_children=True
        )
        failed_projection = await _add_projection(
            session, seed, version_index=1, status="failed"
        )

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        result = await RagDocumentSqlInventory(engine).collect(
            seed.workspace_id, (seed.target,)
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_statement)

    assert result.participant == RAG_DOCUMENT_SQL_PARTICIPANT
    assert result.contract_version == 1
    assert {resource.resource_id for resource in result.resources} == {
        first_projection,
        failed_projection,
    }
    assert result.exhausted and result.supported and result.legacy_resolved
    assert [field.name for field in fields(result.resources[0])] == [
        "participant",
        "kind",
        "resource_id",
        "revision",
    ]
    assert any("repeatable read, read only" in statement for statement in statements)
    selected = " ".join(statement for statement in statements if statement.startswith("select"))
    for private_column in ("object_key", "sha256", ".text", "source_part", "section_path"):
        assert private_column not in selected
    assert all(
        not statement.lstrip().startswith(("insert", "update", "delete"))
        for statement in statements
    )


@pytest.mark.asyncio
async def test_valid_source_without_projection_is_an_empty_complete_participant_snapshot(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        seed = await _seed_source(session, label="empty")

    result = await RagDocumentSqlInventory(engine).collect(seed.workspace_id, (seed.target,))

    assert result.resources == ()
    assert result.exhausted and result.supported and result.legacy_resolved
    async with engine.connect() as connection:
        assert await connection.scalar(select(1)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    (
        "missing_document",
        "wrong_workspace",
        "wrong_generation",
        "missing_version",
        "foreign_version",
    ),
)
async def test_invalid_or_incomplete_source_fails_with_safe_typed_error(
    engine: AsyncEngine,
    case: str,
) -> None:
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        seed = await _seed_source(session, label=f"invalid-{case}")
        other = await _seed_source(session, label=f"other-{case}")

    target = seed.target
    workspace_id = seed.workspace_id
    if case == "missing_document":
        target = DocumentTarget(uuid4(), seed.generation, seed.version_ids)
    elif case == "wrong_workspace":
        workspace_id = other.workspace_id
    elif case == "wrong_generation":
        target = DocumentTarget(seed.document_id, seed.generation + 1, seed.version_ids)
    elif case == "missing_version":
        target = DocumentTarget(seed.document_id, seed.generation, seed.version_ids[:-1])
    else:
        target = DocumentTarget(
            seed.document_id,
            seed.generation,
            (seed.version_ids[0], other.version_ids[0]),
        )

    with pytest.raises(RagDocumentSqlInventoryError) as caught:
        await RagDocumentSqlInventory(engine).collect(workspace_id, (target,))

    assert caught.value.code == "rag_document_sql_source_invalid"
    assert str(caught.value) == "rag_document_sql_source_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    (
        "null_revision",
        "missing_relation",
        "gone_resource",
        "wrong_revision",
        "extra_relation",
        "extra_source",
        "wrong_source",
    ),
)
async def test_projection_and_current_relation_inconsistency_fails_closed(
    engine: AsyncEngine,
    case: str,
) -> None:
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        seed = await _seed_source(session, label=f"inconsistent-{case}")
        other = await _seed_source(session, label=f"inconsistent-other-{case}")
        projection_id = await _add_projection(
            session, seed, version_index=0, status="partial_ready"
        )
        relation = await session.scalar(
            select(AssetSourceRelationRecord).where(
                AssetSourceRelationRecord.resource_id == projection_id
            )
        )
        assert relation is not None
        if case == "null_revision":
            await session.execute(
                update(RagProjectionRecord)
                .where(RagProjectionRecord.id == projection_id)
                .values(content_revision=None)
            )
            await session.delete(relation)
        elif case == "missing_relation":
            await session.delete(relation)
        elif case == "gone_resource":
            await session.delete(relation)
            session.add(
                AssetSourceRelationRecord(
                    workspace_id=seed.workspace_id,
                    document_id=seed.document_id,
                    asset_version_id=seed.version_ids[0],
                    participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                    kind=RAG_PROJECTION_BUNDLE_KIND,
                    resource_id=uuid4(),
                    resource_revision=1,
                    relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
                )
            )
        elif case == "wrong_revision":
            await session.execute(
                update(RagProjectionRecord)
                .where(RagProjectionRecord.id == projection_id)
                .values(content_revision=2)
            )
        elif case == "extra_relation":
            session.add(
                AssetSourceRelationRecord(
                    workspace_id=seed.workspace_id,
                    document_id=seed.document_id,
                    asset_version_id=seed.version_ids[0],
                    participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                    kind=RAG_PROJECTION_BUNDLE_KIND,
                    resource_id=projection_id,
                    resource_revision=2,
                    relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
                )
            )
        elif case == "extra_source":
            session.add(
                AssetSourceRelationRecord(
                    workspace_id=other.workspace_id,
                    document_id=other.document_id,
                    asset_version_id=other.version_ids[0],
                    participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                    kind=RAG_PROJECTION_BUNDLE_KIND,
                    resource_id=projection_id,
                    resource_revision=1,
                    relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
                )
            )
        else:
            await session.delete(relation)
            session.add(
                AssetSourceRelationRecord(
                    workspace_id=other.workspace_id,
                    document_id=other.document_id,
                    asset_version_id=other.version_ids[0],
                    participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                    kind=RAG_PROJECTION_BUNDLE_KIND,
                    resource_id=projection_id,
                    resource_revision=1,
                    relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
                )
            )

    result = await RagDocumentSqlInventory(engine).collect(seed.workspace_id, (seed.target,))

    assert result.exhausted and result.supported
    assert not result.legacy_resolved


@pytest.mark.asyncio
async def test_unknown_registered_kind_is_returned_but_not_claimed_supported(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine)
    resource_id = uuid4()
    async with sessions.begin() as session:
        seed = await _seed_source(session, label="future-kind")
        session.add(
            AssetSourceRelationRecord(
                workspace_id=seed.workspace_id,
                document_id=seed.document_id,
                asset_version_id=seed.version_ids[0],
                participant=RAG_DOCUMENT_SQL_PARTICIPANT,
                kind="future_projection_bundle",
                resource_id=resource_id,
                resource_revision=1,
                relation_kind=RAG_DERIVED_ARTIFACT_RELATION,
            )
        )

    result = await RagDocumentSqlInventory(engine).collect(seed.workspace_id, (seed.target,))

    assert not result.supported
    assert result.exhausted and result.legacy_resolved
    assert {resource.resource_id for resource in result.resources} == {resource_id}


@pytest.mark.asyncio
async def test_inconsistent_evidence_ownership_is_not_reported_complete(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        seed = await _seed_source(session, label="bad-evidence")
        projection_id = await _add_projection(
            session,
            seed,
            version_index=0,
            status="ready",
            with_children=True,
        )
        other_projection_id = await _add_projection(
            session, seed, version_index=1, status="ready"
        )
        evidence_id = await session.scalar(
            select(EvidenceUnitRecord.id).where(
                EvidenceUnitRecord.projection_id == projection_id
            )
        )
        assert evidence_id is not None
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            update(EvidenceUnitRecord)
            .where(EvidenceUnitRecord.id == evidence_id)
            .values(projection_id=other_projection_id)
        )
        await session.execute(text("SET LOCAL session_replication_role = origin"))

    result = await RagDocumentSqlInventory(engine).collect(seed.workspace_id, (seed.target,))

    assert result.exhausted and result.supported
    assert not result.legacy_resolved


@pytest.mark.asyncio
async def test_concurrent_commit_does_not_mix_inventory_selects(
    engine: AsyncEngine,
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        seed = await _seed_source(session, label="snapshot")
        projection_id = await _add_projection(
            session, seed, version_index=0, status="ready"
        )

    snapshot_started = Event()
    writer_done = Event()
    writer_error: list[BaseException] = []

    def write_extra_relation() -> None:
        try:
            assert snapshot_started.wait(timeout=5)
            url = migrated_database.database_url.replace(
                "postgresql+psycopg://", "postgresql://", 1
            )
            with psycopg.connect(url, connect_timeout=5) as connection:
                connection.execute(
                    "INSERT INTO asset_source_relations "
                    "(id,workspace_id,document_id,asset_version_id,participant,kind,"
                    "resource_id,resource_revision,relation_kind) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        uuid4(),
                        seed.workspace_id,
                        seed.document_id,
                        seed.version_ids[0],
                        RAG_DOCUMENT_SQL_PARTICIPANT,
                        RAG_PROJECTION_BUNDLE_KIND,
                        projection_id,
                        2,
                        RAG_DERIVED_ARTIFACT_RELATION,
                    ),
                )
        except BaseException as error:
            writer_error.append(error)
        finally:
            writer_done.set()

    writer = Thread(target=write_extra_relation, daemon=True)
    writer.start()
    paused = False

    def pause_after_snapshot(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        nonlocal paused
        normalized = statement.lower()
        if not paused and "from documents" in normalized:
            paused = True
            snapshot_started.set()
            assert writer_done.wait(timeout=5)

    event.listen(engine.sync_engine, "after_cursor_execute", pause_after_snapshot)
    try:
        snapshot_result = await RagDocumentSqlInventory(engine).collect(
            seed.workspace_id, (seed.target,)
        )
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", pause_after_snapshot)
        writer.join(timeout=5)

    assert not writer.is_alive()
    assert writer_error == []
    assert snapshot_result.legacy_resolved
    later_result = await RagDocumentSqlInventory(engine).collect(
        seed.workspace_id, (seed.target,)
    )
    assert not later_result.legacy_resolved


@pytest.mark.asyncio
async def test_database_failure_is_replaced_by_safe_inventory_error(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    # A syntactically valid but unreachable database keeps the assertion independent
    # from private connection details in the raised exception.
    unavailable = create_async_engine(
        migrated_database.database_url.replace(
            f"/{migrated_database.name}", "/missing_inventory_db"
        )
    )
    try:
        with pytest.raises(RagDocumentSqlInventoryError) as caught:
            await RagDocumentSqlInventory(unavailable).collect(uuid4(), ())
        assert caught.value.code == "rag_document_sql_inventory_failed"
        assert str(caught.value) == "rag_document_sql_inventory_failed"
    finally:
        await unavailable.dispose()
