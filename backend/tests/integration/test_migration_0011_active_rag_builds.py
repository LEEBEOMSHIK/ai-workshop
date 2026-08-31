from datetime import UTC, datetime, timedelta
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
REVISION_0010 = "0010_rag_evaluation"
REVISION_0011 = "0011_active_rag_builds"


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


def _seed_two_active_builds(database_url: str) -> tuple[UUID, UUID]:
    owner_id = uuid4()
    workspace_id = uuid4()
    older_build_id = UUID("00000000-0000-0000-0000-000000001101")
    newer_build_id = UUID("00000000-0000-0000-0000-000000001102")
    start = datetime(2026, 8, 31, tzinfo=UTC)
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
        for ordinal, (build_id, updated_at) in enumerate(
            (
                (older_build_id, start),
                (newer_build_id, start + timedelta(seconds=1)),
            ),
            1,
        ):
            document_id = uuid4()
            asset_version_id = uuid4()
            projection_id = uuid4()
            connection.execute(
                """
                INSERT INTO documents (
                    workspace_id, folder_id, name, active_version_id, id
                ) VALUES (%s, NULL, %s, %s, %s)
                """,
                (
                    workspace_id,
                    f"migration-active-{ordinal}.txt",
                    asset_version_id,
                    document_id,
                ),
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
                    str(ordinal) * 64,
                    asset_version_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_document_projections (
                    asset_version_id, indexing_profile_id, status, id
                ) VALUES (%s, %s, 'ready', %s)
                """,
                (asset_version_id, E5_INDEXING_PROFILE_ID, projection_id),
            )
            connection.execute(
                """
                INSERT INTO rag_index_builds (
                    projection_id, indexing_profile_id, index_name,
                    expected_document_count, indexed_document_count,
                    vector_dimension, status, is_active,
                    id, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, 1, 1, 768, 'ready', true,
                    %s, %s, %s
                )
                """,
                (
                    projection_id,
                    E5_INDEXING_PROFILE_ID,
                    f"ai-workshop-rag-{E5_INDEXING_PROFILE_ID}-{build_id}",
                    build_id,
                    start,
                    updated_at,
                ),
            )
    return older_build_id, newer_build_id


def test_0011_allows_multiple_active_builds_and_downgrades_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t14a_migration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0010)
            command.upgrade(config, REVISION_0011)

            older_build_id, newer_build_id = _seed_two_active_builds(isolated_url)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT to_regclass('uq_rag_index_builds_active_profile')"
                ).fetchone() == (None,)
                assert connection.execute(
                    """
                    SELECT conname FROM pg_constraint
                     WHERE conrelid = 'rag_index_builds'::regclass
                       AND conname IN (
                           'uq_rag_index_builds_projection_id',
                           'uq_rag_index_builds_index_name'
                       )
                     ORDER BY conname
                    """
                ).fetchall() == [
                    ("uq_rag_index_builds_index_name",),
                    ("uq_rag_index_builds_projection_id",),
                ]
                assert connection.execute(
                    """
                    SELECT id FROM rag_index_builds
                     WHERE indexing_profile_id = %s AND is_active
                     ORDER BY id
                    """,
                    (E5_INDEXING_PROFILE_ID,),
                ).fetchall() == [(older_build_id,), (newer_build_id,)]

            command.downgrade(config, REVISION_0010)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT to_regclass('uq_rag_index_builds_active_profile')"
                ).fetchone() == ("uq_rag_index_builds_active_profile",)
                assert connection.execute(
                    """
                    SELECT id FROM rag_index_builds
                     WHERE indexing_profile_id = %s AND is_active
                    """,
                    (E5_INDEXING_PROFILE_ID,),
                ).fetchall() == [(newer_build_id,)]

            command.upgrade(config, "head")
            command.current(config, check_heads=True)
            command.check(config)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (REVISION_0011,)
                assert connection.execute(
                    "SELECT to_regclass('uq_rag_index_builds_active_profile')"
                ).fetchone() == (None,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
