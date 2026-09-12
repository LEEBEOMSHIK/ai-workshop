from collections.abc import Iterator
from contextlib import contextmanager
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


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Config, str]]:
    settings = get_settings()
    database = f"ai_workshop_t23_domains_{uuid4().hex}"
    isolated_url = _database_url(settings.database_url, database)
    administrative = _database_url(settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        yield Config(str(BACKEND_ROOT / "alembic.ini")), isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


def test_domain_migration_is_additive_immutable_and_has_no_seed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch) as (config, isolated_url):
        command.upgrade(config, "0022_mixed_pdf_ocr_profile")
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            before_configurations = connection.execute(
                "SELECT count(*) FROM rag_configurations"
            ).fetchone()
        command.upgrade(config, "0023_rag_domains")
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute("SELECT count(*) FROM rag_domains").fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM rag_domain_connection_versions"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM rag_domain_connection_scope_seals"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM rag_configurations"
            ).fetchone() == before_configurations

        command.downgrade(config, "0022_mixed_pdf_ocr_profile")
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.rag_domains')"
            ).fetchone() == (None,)


def test_domain_database_rejects_slug_mutation_and_foreign_configuration_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch) as (config, isolated_url):
        command.upgrade(config, "0023_rag_domains")
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            owner_id = uuid4()
            domain_id = uuid4()
            connection_id = uuid4()
            configuration_version_id = uuid4()
            workspace_id = uuid4()
            second_workspace_id = uuid4()
            late_workspace_id = uuid4()
            foreign_workspace_id = uuid4()
            email = f"{owner_id}@example.test"
            connection.execute(
                """
                INSERT INTO users (
                    id, display_name, email, normalized_email, password_hash,
                    role, is_active
                ) VALUES (%s, 'Owner', %s, %s, 'hash', 'owner', true)
                """,
                (owner_id, email, email),
            )
            for current_workspace_id, name in (
                (workspace_id, "Allowed"),
                (second_workspace_id, "Also allowed"),
                (late_workspace_id, "Late append"),
                (foreign_workspace_id, "Foreign"),
            ):
                connection.execute(
                    "INSERT INTO workspaces (id, name, kind, created_by) "
                    "VALUES (%s, %s, 'team', %s)",
                    (current_workspace_id, name, owner_id),
                )
            connection.execute(
                """
                SELECT id
                FROM rag_configuration_versions
                WHERE id = '00000000-0000-0000-0000-000000000503'
                """,
            )
            configuration_version_id = connection.execute(
                "SELECT id FROM rag_configuration_versions "
                "WHERE id = '00000000-0000-0000-0000-000000000503'"
            ).fetchone()[0]
            for subscribed_workspace_id in (
                workspace_id,
                second_workspace_id,
                late_workspace_id,
            ):
                connection.execute(
                    """
                    INSERT INTO rag_configuration_workspace_subscriptions (
                        id, configuration_version_id, workspace_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (uuid4(), configuration_version_id, subscribed_workspace_id),
                )
            connection.execute(
                """
                INSERT INTO rag_domains (
                    id, slug, display_name, description, created_by
                ) VALUES (%s, 'fund-management', 'Fund', '', %s)
                """,
                (domain_id, owner_id),
            )
            connection.execute(
                """
                INSERT INTO rag_domain_connection_versions (
                    id, domain_id, version, configuration_version_id, created_by
                ) VALUES (%s, %s, 1, %s, %s)
                """,
                (connection_id, domain_id, configuration_version_id, owner_id),
            )
            connection.execute(
                """
                INSERT INTO rag_domain_connection_workspaces (
                    connection_version_id, configuration_version_id, workspace_id
                ) VALUES (%s, %s, %s)
                """,
                (connection_id, configuration_version_id, workspace_id),
            )
            connection.execute(
                """
                INSERT INTO rag_domain_connection_workspaces (
                    connection_version_id, configuration_version_id, workspace_id
                ) VALUES (%s, %s, %s)
                """,
                (connection_id, configuration_version_id, second_workspace_id),
            )
            with (
                pytest.raises(psycopg.errors.ForeignKeyViolation),
                connection.transaction(),
            ):
                connection.execute(
                    """
                    INSERT INTO rag_domain_connection_workspaces (
                        connection_version_id, configuration_version_id, workspace_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (connection_id, configuration_version_id, foreign_workspace_id),
                )
            connection.commit()

            assert connection.execute(
                "SELECT count(*) FROM rag_domain_connection_workspaces "
                "WHERE connection_version_id = %s",
                (connection_id,),
            ).fetchone() == (2,)
            with (
                pytest.raises(psycopg.errors.RaiseException, match="immutable"),
                connection.transaction(),
            ):
                connection.execute(
                    """
                    INSERT INTO rag_domain_connection_workspaces (
                        connection_version_id, configuration_version_id, workspace_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (connection_id, configuration_version_id, late_workspace_id),
                )

            with (
                pytest.raises(psycopg.errors.RaiseException, match="slug"),
                connection.transaction(),
            ):
                connection.execute(
                    "UPDATE rag_domains SET slug = 'changed' WHERE id = %s",
                    (domain_id,),
                )
            with (
                pytest.raises(psycopg.errors.RaiseException, match="immutable"),
                connection.transaction(),
            ):
                connection.execute(
                    "UPDATE rag_domain_connection_versions SET version = 2 WHERE id = %s",
                    (connection_id,),
                )
