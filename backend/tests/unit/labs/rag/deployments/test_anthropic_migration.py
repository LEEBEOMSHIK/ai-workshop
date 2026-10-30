"""Render the migration offline; never connect to a database or modify policy rows."""

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint

from ai_workshop.labs.rag.deployments.models import ModelDeploymentVersionRecord
from ai_workshop.labs.rag.policies.models import (
    InstallationDataPolicyVersionRecord,
    WorkspaceDataPolicyVersionRecord,
)


def migration_sql(direction: str) -> str:
    path = Path(__file__).resolve().parents[5] / "alembic/versions/0068_anthropic_messages.py"
    assert path.is_file(), "Native provider needs an additive migration."
    spec = importlib.util.spec_from_file_location("anthropic_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0067_stored_model_comparisons"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(module, direction)()
    return output.getvalue()


def test_upgrade_expands_four_checks_and_native_contract_without_changing_rows():
    sql = migration_sql("upgrade")
    names = {
        "ck_rag_deployment_versions_provider",
        "ck_rag_deployment_versions_execution_reference",
        "ck_rag_deployment_versions_anthropic_contract",
        "ck_rag_installation_policy_versions_providers",
        "ck_rag_workspace_policy_versions_providers",
    }
    checked = set()
    for model in (
        ModelDeploymentVersionRecord,
        InstallationDataPolicyVersionRecord,
        WorkspaceDataPolicyVersionRecord,
    ):
        for constraint in model.__table__.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name in names:
                assert str(constraint.sqltext) in sql
                checked.add(constraint.name)
    assert checked == names
    assert sql.count("DROP CONSTRAINT") == 4
    assert sql.count("ADD CONSTRAINT") == 5
    assert "secret_ref IS NOT NULL" in sql
    assert "location = 'external'" in sql
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "TRUNCATE "):
        assert verb not in sql.upper()


def test_downgrade_refuses_deployment_and_both_policy_references_before_narrowing():
    sql = migration_sql("downgrade")
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP CONSTRAINT")
    assert "WHERE provider = 'anthropic_messages'" in sql
    assert sql.count("approved_providers::jsonb @>") == 2
    assert sql.count("DROP CONSTRAINT") == 5
    for statement in sql.split(";"):
        if "ADD CONSTRAINT" in statement:
            assert "anthropic_messages" not in statement
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "TRUNCATE "):
        assert verb not in sql.upper()
