import json
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from alembic import command
from tests.integration.publishing_support import isolated_publishing_database

pytestmark = pytest.mark.integration
REVISION = "0026_codex_runner_reference"


def insert_deployment(connection, *, codex=False, **overrides):
    owner, model, identity = uuid4(), uuid4(), uuid4()
    connection.execute(
        "INSERT INTO rag_model_definitions (id, kind, name, version, config) "
        "VALUES (%s, 'llm', %s, 1, '{}'::json)",
        (model, str(model)),
    )
    connection.execute(
        "INSERT INTO rag_model_deployments (id, created_by) VALUES (%s, %s)",
        (identity, owner),
    )
    values = dict(
        id=uuid4(),
        deployment_id=identity,
        version=1,
        display_name="Synthetic deployment",
        description="Synthetic migration fixture",
        model_definition_id=model,
        provider="development_codex_exec" if codex else "local_openai_compatible",
        location="external" if codex else "local",
        allowed_environments='["development"]',
        provider_model_id="synthetic-model",
        endpoint_ref=None if codex else "local-runtime",
        secret_ref=None,
        capabilities='["structured_output"]',
        external_transfer=codex,
        transmitted_data_categories='["question"]' if codex else "[]",
        data_processing_notice_ref="synthetic-notice" if codex else None,
        timeout_seconds=5,
        max_retries=0,
        retry_backoff_seconds=0,
        healthcheck_enabled=not codex,
        development_only=codex,
        created_by=owner,
    )
    if codex:
        values["runner_ref"] = "personal-codex-v1"
    values.update(overrides)
    connection.execute(
        sql.SQL("INSERT INTO rag_model_deployment_versions ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )
    return values["id"]


def test_migration_preserves_http_and_policies_and_roundtrips(monkeypatch):
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0025_publishing")
        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            deployment_id = insert_deployment(connection)
            before = connection.execute(
                "SELECT id, approved_providers::text FROM rag_installation_data_policy_versions"
            ).fetchall()
        command.upgrade(database.config, REVISION)
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT endpoint_ref, runner_ref FROM rag_model_deployment_versions WHERE id=%s",
                (deployment_id,),
            ).fetchone() == ("local-runtime", None)
            assert (
                connection.execute(
                    "SELECT id, approved_providers::text FROM rag_installation_data_policy_versions"
                ).fetchall()
                == before
            )
            with connection.transaction(force_rollback=True):
                insert_deployment(connection, codex=True)
            for override in (
                {"endpoint_ref": "fake-endpoint"},
                {"runner_ref": None},
                {"runner_ref": "C:/codex.exe"},
                {"runner_ref": "codex exec"},
                {"runner_ref": "secret-token"},
                {"max_retries": 1},
                {"retry_backoff_seconds": 0.5},
                {"healthcheck_enabled": True},
                {"development_only": False},
                {"allowed_environments": '["production"]'},
                {"external_transfer": False},
                {"transmitted_data_categories": "[]"},
                {"data_processing_notice_ref": None},
            ):
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    insert_deployment(connection, codex=True, **override)
            for override in (
                {"runner_ref": "personal-codex-v1"},
                {"endpoint_ref": None},
                {"endpoint_ref": "  "},
            ):
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    insert_deployment(connection, **override)
        command.downgrade(database.config, "0025_publishing")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT endpoint_ref FROM rag_model_deployment_versions WHERE id=%s",
                (deployment_id,),
            ).fetchone() == ("local-runtime",)
            assert connection.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rag_model_deployment_versions' AND column_name='endpoint_ref'"
            ).fetchone() == ("NO",)


@pytest.mark.parametrize("retained", ["deployment", "installation", "workspace"])
def test_downgrade_refuses_codex_rows_without_data_loss(monkeypatch, retained):
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, REVISION)
        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            if retained == "deployment":
                insert_deployment(connection, codex=True)
            else:
                policy_id = connection.execute(
                    "SELECT id FROM rag_installation_data_policies"
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO rag_installation_data_policy_versions "
                    "(id, policy_id, version, outbound_mode, approved_providers, changed_by) "
                    "SELECT %s, %s, max(version)+1, 'approved_providers', %s::json, %s "
                    "FROM rag_installation_data_policy_versions",
                    (uuid4(), policy_id, json.dumps(["development_codex_exec"]), uuid4()),
                )
                if retained == "workspace":
                    owner, workspace, workspace_policy = uuid4(), uuid4(), uuid4()
                    email = f"{owner}@example.test"
                    connection.execute(
                        "INSERT INTO users (id, display_name, email, normalized_email, "
                        "password_hash, role, is_active) "
                        "VALUES (%s,'Fixture',%s,%s,'fake','owner',true)",
                        (owner, email, email),
                    )
                    connection.execute(
                        "INSERT INTO workspaces (id,name,kind,created_by) "
                        "VALUES (%s,'Fixture','personal',%s)",
                        (workspace, owner),
                    )
                    connection.execute(
                        "INSERT INTO rag_workspace_data_policies (id,workspace_id) VALUES (%s,%s)",
                        (workspace_policy, workspace),
                    )
                    connection.execute(
                        "INSERT INTO rag_workspace_data_policy_versions "
                        "(id,policy_id,workspace_id,version,outbound_mode,"
                        "approved_providers,changed_by) "
                        "VALUES (%s,%s,%s,1,'approved_providers',%s::json,%s)",
                        (
                            uuid4(),
                            workspace_policy,
                            workspace,
                            json.dumps(["development_codex_exec"]),
                            owner,
                        ),
                    )
            before = connection.execute(
                "SELECT count(*) FROM rag_model_deployment_versions"
            ).fetchone()
        with pytest.raises(Exception, match="Cannot downgrade while Codex"):
            command.downgrade(database.config, "0025_publishing")
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                REVISION,
            )
            assert (
                connection.execute("SELECT count(*) FROM rag_model_deployment_versions").fetchone()
                == before
            )
