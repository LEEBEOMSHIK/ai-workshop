from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


def _seed_legacy_projection(connection: psycopg.Connection[Any]) -> tuple[UUID, ...]:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    profile_id = uuid4()
    projection_id = uuid4()
    email = f"rag-migration-{owner_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic migration owner',%s,%s,"
        "'synthetic-hash','owner',true,now(),now())",
        (owner_id, email, email),
    )
    connection.execute(
        "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
        "VALUES (%s,'Synthetic migration workspace','personal',%s,now(),now())",
        (workspace_id, owner_id),
    )
    connection.execute(
        "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
        "metadata_revision,lifecycle,lifecycle_generation,created_at,updated_at) "
        "VALUES (%s,%s,NULL,'synthetic.txt',NULL,1,'active',1,now(),now())",
        (document_id, workspace_id),
    )
    connection.execute(
        "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
        "size,status,created_at,updated_at) VALUES "
        "(%s,%s,1,%s,%s,'text/plain',1,'stored',now(),now())",
        (asset_version_id, document_id, f"synthetic/{asset_version_id}", "b" * 64),
    )
    connection.execute(
        "INSERT INTO rag_profiles(id,kind,name,version,config,evaluation_state,is_default,"
        "created_at,updated_at) VALUES "
        "(%s,'indexing',%s,1,'{}','draft',false,now(),now())",
        (profile_id, f"synthetic-indexing-{profile_id}"),
    )
    connection.execute(
        "INSERT INTO rag_document_projections(id,asset_version_id,"
        "document_processing_profile_id,indexing_profile_id,status,created_at,updated_at) "
        "VALUES (%s,%s,'00000000-0000-0000-0000-000000000207',%s,'pending',now(),now())",
        (projection_id, asset_version_id, profile_id),
    )
    return workspace_id, document_id, asset_version_id, projection_id


def test_migration_adds_nullable_positive_bigint_without_backfilling_legacy_rows() -> None:
    with _isolated_database_at("0039_asset_purge_inventory") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            *_, projection_id = _seed_legacy_projection(connection)

        command.upgrade(database.config, "0040_rag_content_revision")

        engine = create_engine(database.database_url)
        try:
            column = next(
                item
                for item in inspect(engine).get_columns("rag_document_projections")
                if item["name"] == "content_revision"
            )
            assert column["nullable"] is True
            assert column["default"] is None
            assert str(column["type"]).upper() == "BIGINT"
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT content_revision FROM rag_document_projections WHERE id=%s",
                (projection_id,),
            ).fetchone() == (None,)
            constraints = {
                name: definition
                for name, definition in connection.execute(
                    "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='rag_document_projections'::regclass"
                ).fetchall()
            }
            assert (
                constraints["ck_rag_document_projections_content_revision_positive"]
                == "CHECK (((content_revision IS NULL) OR (content_revision > 0)))"
            )
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(
                    "UPDATE rag_document_projections SET content_revision=0 WHERE id=%s",
                    (projection_id,),
                )


def test_empty_downgrade_preserves_legacy_projection() -> None:
    with _isolated_database_at("0039_asset_purge_inventory") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            *_, projection_id = _seed_legacy_projection(connection)
        command.upgrade(database.config, "0040_rag_content_revision")
        command.downgrade(database.config, "0039_asset_purge_inventory")

        engine = create_engine(database.database_url)
        try:
            assert "content_revision" not in {
                item["name"] for item in inspect(engine).get_columns("rag_document_projections")
            }
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT id FROM rag_document_projections WHERE id=%s", (projection_id,)
            ).fetchone() == (projection_id,)


@pytest.mark.parametrize("tracked_state", ["revision", "relation"])
def test_downgrade_refuses_tracked_revision_or_participant_relation(
    tracked_state: str,
) -> None:
    with _isolated_database_at("0039_asset_purge_inventory") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            workspace_id, document_id, asset_version_id, projection_id = _seed_legacy_projection(
                connection
            )
        command.upgrade(database.config, "0040_rag_content_revision")
        with psycopg.connect(url) as connection:
            if tracked_state == "revision":
                connection.execute(
                    "UPDATE rag_document_projections SET content_revision=1 WHERE id=%s",
                    (projection_id,),
                )
            else:
                connection.execute(
                    "INSERT INTO asset_source_relations"
                    "(id,workspace_id,document_id,asset_version_id,participant,kind,"
                    "resource_id,resource_revision,relation_kind,created_at) "
                    "VALUES (%s,%s,%s,%s,'rag_document_sql','projection_bundle',%s,1,"
                    "'derived_artifact',now())",
                    (uuid4(), workspace_id, document_id, asset_version_id, projection_id),
                )

        with pytest.raises(RuntimeError, match="rag_content_revision_downgrade_unsafe"):
            command.downgrade(database.config, "0039_asset_purge_inventory")

        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0040_rag_content_revision",
            )
