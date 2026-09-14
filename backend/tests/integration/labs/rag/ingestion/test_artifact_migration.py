from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, inspect

from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.shared.models import Base
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile() -> None:
    """Migration cases provision their own UUID database and need no async seed."""


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


def _seed_legacy_ingestion(connection: psycopg.Connection[Any]) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "owner",
            "workspace",
            "document",
            "asset_version",
            "profile",
            "projection",
            "job",
        )
    }
    email = f"artifact-migration-{ids['owner']}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic artifact migration owner',"
        "%s,%s,'synthetic-hash','owner',true,now(),now())",
        (ids["owner"], email, email),
    )
    connection.execute(
        "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
        "VALUES (%s,'Synthetic artifact migration workspace','personal',%s,now(),now())",
        (ids["workspace"], ids["owner"]),
    )
    connection.execute(
        "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
        "metadata_revision,lifecycle,lifecycle_generation,created_at,updated_at) "
        "VALUES (%s,%s,NULL,'synthetic.txt',NULL,1,'active',1,now(),now())",
        (ids["document"], ids["workspace"]),
    )
    connection.execute(
        "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
        "size,status,created_at,updated_at) VALUES "
        "(%s,%s,1,%s,%s,'text/plain',2,'stored',now(),now())",
        (
            ids["asset_version"],
            ids["document"],
            f"synthetic/{ids['asset_version']}",
            "b" * 64,
        ),
    )
    connection.execute(
        "INSERT INTO rag_profiles(id,kind,name,version,config,evaluation_state,is_default,"
        "created_at,updated_at) VALUES "
        "(%s,'indexing',%s,1,'{}','draft',false,now(),now())",
        (ids["profile"], f"synthetic-indexing-{ids['profile']}"),
    )
    connection.execute(
        "INSERT INTO rag_document_projections(id,asset_version_id,"
        "document_processing_profile_id,indexing_profile_id,status,content_revision,"
        "created_at,updated_at) VALUES "
        "(%s,%s,'00000000-0000-0000-0000-000000000207',%s,'pending',NULL,now(),now())",
        (ids["projection"], ids["asset_version"], ids["profile"]),
    )
    connection.execute(
        "INSERT INTO jobs(id,user_id,workspace_id,asset_version_id,type,idempotency_key,"
        "status,stage,attempt,created_at,updated_at) VALUES "
        "(%s,%s,%s,%s,'rag_ingestion',%s,'queued','queued',0,now(),now())",
        (
            ids["job"],
            ids["owner"],
            ids["workspace"],
            ids["asset_version"],
            f"synthetic-{ids['job']}",
        ),
    )
    connection.execute(
        "INSERT INTO rag_ingestion_jobs(job_id,projection_id,asset_version_id,"
        "document_processing_profile_id,indexing_profile_id,requested_by,index_alias_verified,"
        "created_at,updated_at) VALUES "
        "(%s,%s,%s,'00000000-0000-0000-0000-000000000207',%s,%s,false,now(),now())",
        (
            ids["job"],
            ids["projection"],
            ids["asset_version"],
            ids["profile"],
            ids["owner"],
        ),
    )
    return ids


def test_migration_adds_exact_tracking_schema_without_backfilling_legacy() -> None:
    with _isolated_database_at("0040_rag_content_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            ids = _seed_legacy_ingestion(connection)
        command.upgrade(database.config, "0041_rag_artifact_provenance")

        engine = create_engine(database.database_url)
        try:
            inspector = inspect(engine)
            assert {
                "rag_artifact_bundles",
                "rag_artifact_slots",
                "rag_artifact_attempts",
            } <= set(inspector.get_table_names())
            assert "uq_jobs_id_workspace_asset_version" in {
                item["name"] for item in inspector.get_unique_constraints("jobs")
            }
            assert "uq_rag_document_projections_id_asset_version" in {
                item["name"]
                for item in inspector.get_unique_constraints("rag_document_projections")
            }
            assert "uq_rag_ingestion_jobs_job_projection_asset_version" in {
                item["name"]
                for item in inspector.get_unique_constraints("rag_ingestion_jobs")
            }
            foreign_keys = {
                fk["name"]: fk for fk in inspector.get_foreign_keys("rag_artifact_bundles")
            }
            assert {
                "fk_rag_artifact_bundles_document",
                "fk_rag_artifact_bundles_asset_version",
                "fk_rag_artifact_bundles_job_source",
                "fk_rag_artifact_bundles_ingestion_source",
                "fk_rag_artifact_bundles_projection_source",
            } == set(foreign_keys)
            assert all(fk["options"].get("ondelete") == "RESTRICT" for fk in foreign_keys.values())
            required_foreign_keys = {
                "rag_artifact_bundles": set(foreign_keys),
                "rag_artifact_slots": {"fk_rag_artifact_slots_bundle"},
                "rag_artifact_attempts": {
                    "fk_rag_artifact_attempts_slot_store_binding"
                },
            }
            for table in (
                RagArtifactBundleRecord.__table__,
                RagArtifactSlotRecord.__table__,
                RagArtifactAttemptRecord.__table__,
            ):
                database_names = {
                    item["name"]
                    for item in (
                        inspector.get_check_constraints(table.name)
                        + inspector.get_unique_constraints(table.name)
                        + inspector.get_foreign_keys(table.name)
                        + inspector.get_indexes(table.name)
                    )
                }
                model_names = {
                    item.name for item in table.constraints | table.indexes if item.name is not None
                }
                assert model_names <= database_names
                assert required_foreign_keys[table.name] <= model_names
                assert all(
                    fk["options"].get("ondelete") == "RESTRICT"
                    for fk in inspector.get_foreign_keys(table.name)
                )
        finally:
            engine.dispose()

        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM rag_artifact_bundles").fetchone() == (
                0,
            )
            assert connection.execute(
                "SELECT content_revision FROM rag_document_projections WHERE id=%s",
                (ids["projection"],),
            ).fetchone() == (None,)
            open_index = connection.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname="
                "'uq_rag_artifact_attempts_open_slot'"
            ).fetchone()
            assert open_index is not None
            assert "UNIQUE" in open_index[0]
            assert "WHERE ((state)::text = 'open'::text)" in open_index[0]
            relation_unique = connection.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname="
                "'uq_asset_source_relations_source_resource_relation'"
            ).fetchone()
            assert relation_unique is not None
            assert "resource_revision" in relation_unique[0]
            assert AssetSourceRelationRecord.__table__.name == "asset_source_relations"
            assert Base.metadata.tables["asset_source_relations"] is (
                AssetSourceRelationRecord.__table__
            )


def test_empty_downgrade_preserves_legacy_ingestion() -> None:
    with _isolated_database_at("0040_rag_content_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            ids = _seed_legacy_ingestion(connection)
        command.upgrade(database.config, "0041_rag_artifact_provenance")
        command.downgrade(database.config, "0040_rag_content_revision")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT job_id FROM rag_ingestion_jobs WHERE job_id=%s", (ids["job"],)
            ).fetchone() == (ids["job"],)


@pytest.mark.parametrize("tracked_state", ["bundle", "relation"])
def test_downgrade_refuses_tracking_rows_or_participant_relation(tracked_state: str) -> None:
    with _isolated_database_at("0040_rag_content_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            ids = _seed_legacy_ingestion(connection)
        command.upgrade(database.config, "0041_rag_artifact_provenance")
        with psycopg.connect(url) as connection:
            bundle_id = uuid4()
            if tracked_state == "bundle":
                connection.execute(
                    "INSERT INTO rag_artifact_bundles"
                    "(id,projection_id,job_id,workspace_id,document_id,asset_version_id,revision,"
                    "created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,1,now(),now())",
                    (
                        bundle_id,
                        ids["projection"],
                        ids["job"],
                        ids["workspace"],
                        ids["document"],
                        ids["asset_version"],
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO asset_source_relations"
                    "(id,workspace_id,document_id,asset_version_id,participant,kind,resource_id,"
                    "resource_revision,relation_kind,created_at) VALUES "
                    "(%s,%s,%s,%s,'rag_ingestion_artifacts','artifact_bundle',%s,1,"
                    "'derived_artifact',now())",
                    (
                        uuid4(),
                        ids["workspace"],
                        ids["document"],
                        ids["asset_version"],
                        bundle_id,
                    ),
                )

        with pytest.raises(RuntimeError, match="rag_artifact_provenance_downgrade_unsafe"):
            command.downgrade(database.config, "0040_rag_content_revision")
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0041_rag_artifact_provenance",
            )
