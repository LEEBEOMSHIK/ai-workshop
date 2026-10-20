import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint

from ai_workshop.labs.rag.deployments.models import ModelDeploymentVersionRecord


def migration_sql(direction: str) -> str:
    path = Path(__file__).resolve().parents[5] / "alembic/versions/0065_local_transformers.py"
    spec = importlib.util.spec_from_file_location("local_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(module, direction)()
    return output.getvalue()


def test_upgrade_sql_matches_orm_constraints_without_connecting() -> None:
    sql = migration_sql("upgrade")
    assert "ADD COLUMN local_model_ref VARCHAR(120)" in sql
    for constraint in ModelDeploymentVersionRecord.__table__.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name in {
            "ck_rag_deployment_versions_provider",
            "ck_rag_deployment_versions_execution_reference",
            "ck_rag_deployment_versions_local_model_safe_name",
            "ck_rag_deployment_versions_local_transformers_contract",
        }:
            assert str(constraint.sqltext) in sql
    assert "rag_installation_data_policy_versions" in sql
    assert "rag_workspace_data_policy_versions" in sql


def test_downgrade_refuses_data_loss_before_dropping_column() -> None:
    sql = migration_sql("downgrade")
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN local_model_ref")
    assert "WHERE provider = 'local_transformers'" in sql
    assert "WHERE local_model_ref IS NOT NULL" in sql
    assert sql.count('approved_providers::jsonb @>') == 2
