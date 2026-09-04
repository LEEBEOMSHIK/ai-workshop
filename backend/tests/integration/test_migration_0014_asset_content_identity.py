from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0013 = "0013_system_baseline_indexing"
REVISION_0014 = "0014_asset_content_identity"


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


def test_0014_replaces_filename_identity_with_content_lookup_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t15_asset_identity_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0013)

            command.upgrade(config, REVISION_0014)
            owner_id = uuid4()
            workspace_id = uuid4()
            folder_id = uuid4()
            first_document_id = uuid4()
            second_document_id = uuid4()
            with psycopg.connect(_sync_url(isolated_url)) as connection:
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
                    VALUES ('Migration Workspace', 'personal', %s, NULL, %s)
                    """,
                    (owner_id, workspace_id),
                )
                connection.execute(
                    """
                    INSERT INTO folders (workspace_id, parent_id, name, id)
                    VALUES (%s, NULL, 'reports', %s)
                    """,
                    (workspace_id, folder_id),
                )
                connection.execute(
                    """
                    INSERT INTO documents (workspace_id, folder_id, name, active_version_id, id)
                    VALUES (%s, %s, 'same-name.pdf', NULL, %s),
                           (%s, %s, 'same-name.pdf', NULL, %s)
                    """,
                    (
                        workspace_id,
                        folder_id,
                        first_document_id,
                        workspace_id,
                        folder_id,
                        second_document_id,
                    ),
                )
                connection.commit()
                assert connection.execute(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'documents'::regclass
                      AND conname = 'documents_workspace_id_folder_id_name_key'
                    """
                ).fetchall() == []
                assert connection.execute(
                    """
                    SELECT to_regclass('ix_documents_workspace_id'),
                           to_regclass('ix_asset_versions_sha256')
                    """
                ).fetchone() == (
                    "ix_documents_workspace_id",
                    "ix_asset_versions_sha256",
                )
                connection.execute("DELETE FROM documents WHERE id = %s", (second_document_id,))
                connection.commit()

            command.downgrade(config, REVISION_0013)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'documents'::regclass
                      AND conname = 'documents_workspace_id_folder_id_name_key'
                    """
                ).fetchone() == ("documents_workspace_id_folder_id_name_key",)
            command.upgrade(config, REVISION_0014)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
