from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@dataclass(frozen=True, slots=True)
class SourceSeed:
    workspace_ids: tuple[UUID, UUID]
    document_ids: tuple[UUID, UUID, UUID]
    version_ids: tuple[UUID, UUID, UUID]


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_sources(connection: psycopg.Connection[Any]) -> SourceSeed:
    user_id = uuid4()
    email = f"provenance-owner-{user_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic provenance owner',%s,%s,"
        "'hash','member',true,now(),now())",
        (user_id, email, email),
    )
    workspace_ids = (uuid4(), uuid4())
    for index, workspace_id in enumerate(workspace_ids):
        connection.execute(
            "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
            "VALUES (%s,%s,'company',%s,now(),now())",
            (workspace_id, f"Synthetic provenance {index}", user_id),
        )
    document_ids = (uuid4(), uuid4(), uuid4())
    version_ids = (uuid4(), uuid4(), uuid4())
    for index, (workspace_id, document_id, version_id) in enumerate(
        zip(
            (workspace_ids[0], workspace_ids[0], workspace_ids[1]),
            document_ids,
            version_ids,
            strict=True,
        )
    ):
        connection.execute(
            "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
            "metadata_revision,created_at,updated_at) "
            "VALUES (%s,%s,NULL,%s,%s,1,now(),now())",
            (document_id, workspace_id, f"synthetic-{index}.txt", version_id),
        )
        connection.execute(
            "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
            "size,status,created_at,updated_at) VALUES "
            "(%s,%s,1,%s,%s,'text/plain',1,'ready',now(),now())",
            (version_id, document_id, f"synthetic/{version_id}", f"{index + 1:064x}"),
        )
    return SourceSeed(workspace_ids, document_ids, version_ids)


def _insert_relation(
    connection: psycopg.Connection[Any],
    *,
    workspace_id: UUID,
    document_id: UUID,
    version_id: UUID,
    participant: str = "rag",
    kind: str = "index_build",
    resource_id: UUID | None = None,
    resource_revision: int = 1,
    relation_kind: str = "derived_artifact",
) -> UUID:
    relation_id = uuid4()
    connection.execute(
        "INSERT INTO asset_source_relations"
        "(id,workspace_id,document_id,asset_version_id,participant,kind,resource_id,"
        "resource_revision,relation_kind,created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
        (
            relation_id,
            workspace_id,
            document_id,
            version_id,
            participant,
            kind,
            resource_id or uuid4(),
            resource_revision,
            relation_kind,
        ),
    )
    return relation_id


def _assert_rejected(
    connection: psycopg.Connection[Any],
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    with pytest.raises(psycopg.Error), connection.transaction():
        connection.execute(statement, parameters)


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
    with _isolated_database_at("0038_asset_provenance") as database:
        yield database


def test_database_rejects_mismatched_sources_and_invalid_relation_fields(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_sources(connection)
        insert_sql = (
            "INSERT INTO asset_source_relations"
            "(id,workspace_id,document_id,asset_version_id,participant,kind,resource_id,"
            "resource_revision,relation_kind,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())"
        )
        invalid_rows = (
            (
                seed.workspace_ids[1],
                seed.document_ids[0],
                seed.version_ids[0],
                "rag",
                "index_build",
                1,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[1],
                "rag",
                "index_build",
                1,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[0],
                "Rag",
                "index_build",
                1,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[0],
                "rag",
                "éclair",
                1,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[0],
                "rag",
                "a" * 81,
                1,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[0],
                "rag",
                "index_build",
                0,
                "derived_artifact",
            ),
            (
                seed.workspace_ids[0],
                seed.document_ids[0],
                seed.version_ids[0],
                "rag",
                "index_build",
                1,
                "shared",
            ),
        )
        for workspace_id, document_id, version_id, participant, kind, revision, relation in (
            invalid_rows
        ):
            _assert_rejected(
                connection,
                insert_sql,
                (
                    uuid4(),
                    workspace_id,
                    document_id,
                    version_id,
                    participant,
                    kind,
                    uuid4(),
                    revision,
                    relation,
                ),
            )

        relation_id = _insert_relation(
            connection,
            workspace_id=seed.workspace_ids[0],
            document_id=seed.document_ids[0],
            version_id=seed.version_ids[0],
        )
        row = connection.execute(
            "SELECT id,created_at IS NOT NULL FROM asset_source_relations WHERE id=%s",
            (relation_id,),
        ).fetchone()
        assert row == (relation_id, True)


@pytest.mark.asyncio
async def test_repository_is_idempotent_and_lists_every_shared_source(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_sources(connection)

    resource = ResourceIdentity("rag", "index_build", uuid4(), 7)
    first = SourceRelation(
        SourceIdentity(
            seed.workspace_ids[0], seed.document_ids[0], seed.version_ids[0]
        ),
        resource,
        "derived_artifact",
    )
    second = SourceRelation(
        SourceIdentity(
            seed.workspace_ids[0], seed.document_ids[1], seed.version_ids[1]
        ),
        resource,
        "authored_reference",
    )
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            repository = ProvenanceRepository(session)
            await repository.register(second)
            await repository.register(first)
            await repository.register(first)

            assert await repository.list_for_source(first.source) == (first,)
            assert frozenset(
                await repository.list_for_resource(seed.workspace_ids[0], resource)
            ) == frozenset({first, second})
            count = await session.scalar(
                select(func.count())
                .select_from(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.workspace_id == seed.workspace_ids[0],
                    AssetSourceRelationRecord.participant == resource.participant,
                    AssetSourceRelationRecord.kind == resource.kind,
                    AssetSourceRelationRecord.resource_id == resource.resource_id,
                    AssetSourceRelationRecord.resource_revision == resource.revision,
                )
            )
            assert count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_flushes_without_committing(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_sources(connection)
    relation = SourceRelation(
        SourceIdentity(
            seed.workspace_ids[0], seed.document_ids[0], seed.version_ids[0]
        ),
        ResourceIdentity("learning", "revision", uuid4(), 1),
        "source_copy",
    )
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await ProvenanceRepository(session).register(relation)
            assert await session.scalar(
                select(func.count())
                .select_from(AssetSourceRelationRecord)
                .where(AssetSourceRelationRecord.resource_id == relation.resource.resource_id)
            ) == 1
            await session.rollback()
        async with sessions() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(AssetSourceRelationRecord)
                .where(AssetSourceRelationRecord.resource_id == relation.resource.resource_id)
            ) == 0
    finally:
        await engine.dispose()


def test_source_deletion_is_restricted_while_relation_exists(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_sources(connection)
        relation_id = _insert_relation(
            connection,
            workspace_id=seed.workspace_ids[0],
            document_id=seed.document_ids[0],
            version_id=seed.version_ids[0],
        )
        _assert_rejected(
            connection,
            "DELETE FROM asset_versions WHERE id=%s",
            (seed.version_ids[0],),
        )
        _assert_rejected(
            connection,
            "DELETE FROM documents WHERE id=%s",
            (seed.document_ids[0],),
        )
        assert connection.execute(
            "SELECT workspace_id,document_id,asset_version_id "
            "FROM asset_source_relations WHERE id=%s",
            (relation_id,),
        ).fetchone() == (
            seed.workspace_ids[0],
            seed.document_ids[0],
            seed.version_ids[0],
        )


def test_migration_constraints_and_empty_downgrade_preserve_existing_sources() -> None:
    with _isolated_database_at("0037_active_folder_names") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_sources(connection)

        command.upgrade(database.config, "0038_asset_provenance")
        with psycopg.connect(url) as connection:
            constraints = {
                name: definition
                for name, definition in connection.execute(
                    "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='asset_source_relations'::regclass"
                ).fetchall()
            }
            assert constraints.keys() >= {
                "pk_asset_source_relations",
                "fk_asset_source_relations_document",
                "fk_asset_source_relations_asset_version",
                "ck_asset_source_relations_participant",
                "ck_asset_source_relations_kind",
                "ck_asset_source_relations_resource_revision_positive",
                "ck_asset_source_relations_relation_kind",
                "uq_asset_source_relations_source_resource_relation",
            }
            assert "ON DELETE RESTRICT" in constraints[
                "fk_asset_source_relations_document"
            ]
            assert "ON DELETE RESTRICT" in constraints[
                "fk_asset_source_relations_asset_version"
            ]
            index_columns = connection.execute(
                "SELECT array_agg(attribute.attname ORDER BY key.ordinality) "
                "FROM pg_class AS index_record "
                "JOIN pg_index ON pg_index.indexrelid=index_record.oid "
                "JOIN LATERAL unnest(pg_index.indkey) WITH ORDINALITY "
                "AS key(attnum,ordinality) ON true "
                "JOIN pg_attribute AS attribute "
                "ON attribute.attrelid=pg_index.indrelid AND attribute.attnum=key.attnum "
                "WHERE index_record.relname='ix_asset_source_relations_resource' "
                "GROUP BY index_record.oid"
            ).fetchone()
            assert index_columns == (
                [
                    "workspace_id",
                    "participant",
                    "kind",
                    "resource_id",
                    "resource_revision",
                ],
            )

        command.downgrade(database.config, "0037_active_folder_names")
        engine = create_engine(database.database_url)
        try:
            schema = inspect(engine)
            assert not schema.has_table("asset_source_relations")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT id,workspace_id FROM documents WHERE id=%s",
                (seed.document_ids[0],),
            ).fetchone() == (seed.document_ids[0], seed.workspace_ids[0])
            assert connection.execute(
                "SELECT id,document_id FROM asset_versions WHERE id=%s",
                (seed.version_ids[0],),
            ).fetchone() == (seed.version_ids[0], seed.document_ids[0])


def test_nonempty_downgrade_is_rejected_without_losing_relation() -> None:
    with _isolated_database_at("0038_asset_provenance") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_sources(connection)
            relation_id = _insert_relation(
                connection,
                workspace_id=seed.workspace_ids[0],
                document_id=seed.document_ids[0],
                version_id=seed.version_ids[0],
            )

        with pytest.raises(RuntimeError) as error:
            command.downgrade(database.config, "0037_active_folder_names")
        assert str(error.value) == "asset_provenance_downgrade_unsafe"
        engine = create_engine(database.database_url)
        try:
            assert inspect(engine).has_table("asset_source_relations")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0038_asset_provenance",)
            assert connection.execute(
                "SELECT id FROM asset_source_relations WHERE id=%s",
                (relation_id,),
            ).fetchone() == (relation_id,)


def test_model_registry_resolves_provenance_metadata_in_a_fresh_process() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    script = """
from ai_workshop.shared.model_registry import load_models
from ai_workshop.shared.models import Base
load_models()
relation = Base.metadata.tables['asset_source_relations']
for foreign_key in relation.foreign_keys:
    foreign_key.column
assert set(relation.columns.keys()) == {
    'id',
    'workspace_id',
    'document_id',
    'asset_version_id',
    'participant',
    'kind',
    'resource_id',
    'resource_revision',
    'relation_kind',
    'created_at',
}
assert {
    constraint.name for constraint in relation.constraints if constraint.name
} >= {
    'ck_asset_source_relations_participant',
    'ck_asset_source_relations_kind',
    'ck_asset_source_relations_resource_revision_positive',
    'ck_asset_source_relations_relation_kind',
    'fk_asset_source_relations_document',
    'fk_asset_source_relations_asset_version',
    'uq_asset_source_relations_source_resource_relation',
}
assert {
    constraint.name
    for constraint in Base.metadata.tables['documents'].constraints
    if constraint.name
} >= {'uq_documents_workspace_id_id'}
assert {
    constraint.name
    for constraint in Base.metadata.tables['asset_versions'].constraints
    if constraint.name
} >= {'uq_asset_versions_document_id_id'}
assert {
    (index.name, tuple(column.name for column in index.columns))
    for index in relation.indexes
} == {
    (
        'ix_asset_source_relations_resource',
        ('workspace_id', 'participant', 'kind', 'resource_id', 'resource_revision'),
    )
}
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
