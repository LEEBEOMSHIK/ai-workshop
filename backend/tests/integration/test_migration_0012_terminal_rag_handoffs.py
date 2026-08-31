from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.domain import E5_INDEXING_PROFILE_ID
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0011 = "0011_active_rag_builds"
REVISION_0012 = "0012_terminal_rag_handoffs"


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _create_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
        )


def _assert_0012_schema(database_url: str) -> None:
    with psycopg.connect(_sync_url(database_url)) as connection:
        assert connection.execute(
            "SELECT to_regclass('rag_asset_handoff_failures')"
        ).fetchone() == ("rag_asset_handoff_failures",)
        assert connection.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'rag_ingestion_dispatches'
               AND column_name = 'cancelled_at'
            """
        ).fetchone() == ("cancelled_at",)
        constraints = {
            row[0]
            for row in connection.execute(
                """
                SELECT conname FROM pg_constraint
                 WHERE conrelid IN (
                     'rag_ingestion_dispatches'::regclass,
                     'rag_asset_handoff_failures'::regclass
                 )
                """
            ).fetchall()
        }
        assert {
            "ck_rag_ing_dispatch_status",
            "ck_rag_ing_dispatch_state",
            "ck_rag_asset_handoff_status",
            "ck_rag_asset_handoff_error_class",
            "ck_rag_asset_handoff_attempt",
            "ck_rag_asset_handoff_state",
        } <= constraints


def _seed_cancelled_handoff(database_url: str) -> UUID:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    job_id = uuid4()
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Migration Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (f"{owner_id}@example.test", f"{owner_id}@example.test", owner_id),
        )
        connection.execute(
            """
            INSERT INTO workspaces (name, kind, created_by, expires_at, id)
            VALUES (%s, 'personal', %s, NULL, %s)
            """,
            (f"Migration Workspace {workspace_id}", owner_id, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO documents (workspace_id, folder_id, name, active_version_id, id)
            VALUES (%s, NULL, 'migration.txt', NULL, %s)
            """,
            (workspace_id, document_id),
        )
        connection.execute(
            """
            INSERT INTO asset_versions (
                document_id, number, object_key, sha256, media_type,
                size, status, id
            ) VALUES (%s, 1, %s, %s, 'text/plain', 1, 'ready', %s)
            """,
            (
                document_id,
                f"synthetic/{asset_version_id}.txt",
                "a" * 64,
                asset_version_id,
            ),
        )
        connection.execute(
            "UPDATE documents SET active_version_id = %s WHERE id = %s",
            (asset_version_id, document_id),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                user_id, workspace_id, asset_version_id, type, idempotency_key,
                status, stage, attempt, error_code, error_message, id
            ) VALUES (
                %s, %s, %s, 'rag_ingestion', %s,
                'failed', 'failed', 1, 'index_source_inactive',
                'Synthetic inactive source.', %s
            )
            """,
            (owner_id, workspace_id, asset_version_id, f"migration:{job_id}", job_id),
        )
        connection.execute(
            """
            INSERT INTO rag_document_projections (
                asset_version_id, indexing_profile_id, status, id
            ) VALUES (%s, %s, 'failed', %s)
            """,
            (asset_version_id, E5_INDEXING_PROFILE_ID, projection_id),
        )
        connection.execute(
            """
            INSERT INTO rag_ingestion_jobs (
                job_id, projection_id, asset_version_id, indexing_profile_id,
                requested_by, index_alias_verified
            ) VALUES (%s, %s, %s, %s, %s, false)
            """,
            (
                job_id,
                projection_id,
                asset_version_id,
                E5_INDEXING_PROFILE_ID,
                owner_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_ingestion_dispatches (
                job_id, status, available_at, attempt_count, cancelled_at
            ) VALUES (%s, 'cancelled', now(), 1, now())
            """,
            (job_id,),
        )
        connection.execute(
            """
            INSERT INTO rag_asset_handoff_failures (
                asset_version_id, indexing_profile_id, requested_by, status,
                error_class, error_code, attempt_count, last_attempt_at,
                next_retry_at, terminal_at, last_error_message
            ) VALUES (
                %s, %s, %s, 'cancelled', 'obsolete', 'index_source_inactive',
                1, now(), NULL, now(), 'The exact source is obsolete.'
            )
            """,
            (asset_version_id, E5_INDEXING_PROFILE_ID, owner_id),
        )
    return job_id


def test_0012_round_trip_preserves_terminal_non_delivery_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t14b_r2_migration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0011)
            command.upgrade(config, REVISION_0012)
            _assert_0012_schema(isolated_url)
            job_id = _seed_cancelled_handoff(isolated_url)

            command.downgrade(config, REVISION_0011)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT to_regclass('rag_asset_handoff_failures')"
                ).fetchone() == (None,)
                assert connection.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                     WHERE table_name = 'rag_ingestion_dispatches'
                       AND column_name = 'cancelled_at'
                    """
                ).fetchone() is None
                assert connection.execute(
                    "SELECT status, error_code FROM jobs WHERE id = %s", (job_id,)
                ).fetchone() == ("failed", "index_source_inactive")
                assert connection.execute(
                    "SELECT count(*) FROM rag_ingestion_dispatches WHERE job_id = %s",
                    (job_id,),
                ).fetchone() == (0,)

            command.upgrade(config, "head")
            command.current(config, check_heads=True)
            command.check(config)
            _assert_0012_schema(isolated_url)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (REVISION_0012,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
