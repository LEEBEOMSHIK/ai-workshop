"""Support named local Transformers deployments without HTTP or runner references."""

import sqlalchemy as sa

from alembic import op

revision = "0065_local_transformers"
down_revision = "0064_rag_epoch_key_events"
branch_labels = None
depends_on = None

TABLE = "rag_model_deployment_versions"
OLD_PROVIDERS = "'local_openai_compatible', 'openai_responses', 'development_codex_exec'"
OLD_REFERENCE = (
    "(provider = 'development_codex_exec' AND endpoint_ref IS NULL "
    "AND runner_ref IS NOT NULL AND btrim(runner_ref) <> '') OR "
    "(provider <> 'development_codex_exec' AND endpoint_ref IS NOT NULL "
    "AND btrim(endpoint_ref) <> '' AND runner_ref IS NULL)"
)
NEW_REFERENCE = (
    "(provider = 'development_codex_exec' AND endpoint_ref IS NULL "
    "AND runner_ref IS NOT NULL AND btrim(runner_ref) <> '' "
    "AND local_model_ref IS NULL) OR "
    "(provider = 'local_transformers' AND endpoint_ref IS NULL "
    "AND runner_ref IS NULL AND local_model_ref IS NOT NULL) OR "
    "(provider IN ('local_openai_compatible', 'openai_responses') "
    "AND endpoint_ref IS NOT NULL AND btrim(endpoint_ref) <> '' "
    "AND runner_ref IS NULL AND local_model_ref IS NULL)"
)
LOCAL_NAME = (
    "local_model_ref IS NULL OR ("
    "local_model_ref ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$' "
    "AND local_model_ref !~ '^(sk|sess|key|token|secret)-')"
)
LOCAL_CONTRACT = (
    "provider <> 'local_transformers' OR (NOT external_transfer "
    "AND location IN ('local', 'on_premise') AND secret_ref IS NULL "
    "AND max_retries = 0 AND retry_backoff_seconds = 0 "
    "AND transmitted_data_categories::jsonb = '[]'::jsonb "
    "AND data_processing_notice_ref IS NULL)"
)


def _replace_constraints(*, local: bool) -> None:
    for suffix in ("provider", "execution_reference"):
        op.drop_constraint(f"ck_rag_deployment_versions_{suffix}", TABLE, type_="check")
    providers = (
        "'local_openai_compatible', 'local_transformers', "
        "'openai_responses', 'development_codex_exec'" if local else OLD_PROVIDERS
    )
    op.create_check_constraint(
        "ck_rag_deployment_versions_provider", TABLE, f"provider IN ({providers})"
    )
    op.create_check_constraint(
        "ck_rag_deployment_versions_execution_reference", TABLE,
        NEW_REFERENCE if local else OLD_REFERENCE,
    )
    allowed = '["local_openai_compatible", "openai_responses", "development_codex_exec"'
    allowed += ', "local_transformers"]' if local else "]"
    for scope in ("installation", "workspace"):
        table = f"rag_{scope}_data_policy_versions"
        name = f"ck_rag_{scope}_policy_versions_providers"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"approved_providers::jsonb <@ '{allowed}'::jsonb")


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("local_model_ref", sa.String(120), nullable=True))
    _replace_constraints(local=True)
    op.create_check_constraint(
        "ck_rag_deployment_versions_local_model_safe_name", TABLE, LOCAL_NAME,
    )
    op.create_check_constraint(
        "ck_rag_deployment_versions_local_transformers_contract", TABLE, LOCAL_CONTRACT,
    )


def downgrade() -> None:
    # Preserve the refusal in offline SQL too: never delete deployment or policy data.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM rag_model_deployment_versions
                       WHERE provider = 'local_transformers')
                OR EXISTS (SELECT 1 FROM rag_model_deployment_versions
                           WHERE local_model_ref IS NOT NULL)
                OR EXISTS (SELECT 1 FROM rag_installation_data_policy_versions
                           WHERE approved_providers::jsonb @> '["local_transformers"]'::jsonb)
                OR EXISTS (SELECT 1 FROM rag_workspace_data_policy_versions
                           WHERE approved_providers::jsonb @> '["local_transformers"]'::jsonb)
            THEN
                RAISE EXCEPTION 'Cannot downgrade while local model deployments or approvals exist';
            END IF;
        END $$;
    """)
    for suffix in ("local_transformers_contract", "local_model_safe_name"):
        op.drop_constraint(f"ck_rag_deployment_versions_{suffix}", TABLE, type_="check")
    _replace_constraints(local=False)
    op.drop_column(TABLE, "local_model_ref")
