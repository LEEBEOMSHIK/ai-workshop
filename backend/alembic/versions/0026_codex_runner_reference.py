"""Separate development Codex runner references from HTTP endpoints."""

import sqlalchemy as sa

from alembic import op

revision = "0026_codex_runner_reference"
down_revision = "0025_publishing"
branch_labels = None
depends_on = None

TABLE = "rag_model_deployment_versions"
HTTP_PROVIDERS = "'local_openai_compatible', 'openai_responses'"
REFERENCE_CHECK = (
    "(provider = 'development_codex_exec' AND endpoint_ref IS NULL "
    "AND runner_ref IS NOT NULL AND btrim(runner_ref) <> '') OR "
    "(provider <> 'development_codex_exec' AND endpoint_ref IS NOT NULL "
    "AND btrim(endpoint_ref) <> '' AND runner_ref IS NULL)"
)
RUNNER_CHECK = (
    "runner_ref IS NULL OR ("
    "runner_ref ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$' "
    "AND runner_ref !~ '^(sk|sess|key|token|secret)-')"
)
CODEX_CHECK = (
    "provider <> 'development_codex_exec' OR (external_transfer "
    "AND location = 'external' AND development_only "
    "AND allowed_environments::jsonb = '[\"development\"]'::jsonb "
    "AND secret_ref IS NULL AND max_retries = 0 "
    "AND retry_backoff_seconds = 0 AND NOT healthcheck_enabled)"
)


def _provider_constraints(*, codex: bool) -> None:
    op.drop_constraint("ck_rag_deployment_versions_provider", TABLE, type_="check")
    providers = HTTP_PROVIDERS + (", 'development_codex_exec'" if codex else "")
    op.create_check_constraint(
        "ck_rag_deployment_versions_provider", TABLE, f"provider IN ({providers})"
    )
    allowed = '["local_openai_compatible", "openai_responses"'
    allowed += ', "development_codex_exec"]' if codex else "]"
    for scope in ("installation", "workspace"):
        table = f"rag_{scope}_data_policy_versions"
        name = f"ck_rag_{scope}_policy_versions_providers"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"approved_providers::jsonb <@ '{allowed}'::jsonb")


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("runner_ref", sa.String(120), nullable=True))
    op.alter_column(TABLE, "endpoint_ref", existing_type=sa.String(120), nullable=True)
    _provider_constraints(codex=True)
    for suffix, expression in (
        ("execution_reference", REFERENCE_CHECK),
        ("runner_safe_name", RUNNER_CHECK),
        ("codex_contract", CODEX_CHECK),
    ):
        op.create_check_constraint(f"ck_rag_deployment_versions_{suffix}", TABLE, expression)


def downgrade() -> None:
    # Execute the guard in PostgreSQL so offline SQL preserves the same refusal.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM rag_model_deployment_versions
                       WHERE provider = 'development_codex_exec')
                OR EXISTS (SELECT 1 FROM rag_installation_data_policy_versions
                           WHERE approved_providers::jsonb @> '["development_codex_exec"]'::jsonb)
                OR EXISTS (SELECT 1 FROM rag_workspace_data_policy_versions
                           WHERE approved_providers::jsonb @> '["development_codex_exec"]'::jsonb)
            THEN
                RAISE EXCEPTION 'Cannot downgrade while Codex deployments or approvals exist';
            END IF;
        END $$;
    """)
    for suffix in ("codex_contract", "runner_safe_name", "execution_reference"):
        op.drop_constraint(f"ck_rag_deployment_versions_{suffix}", TABLE, type_="check")
    _provider_constraints(codex=False)
    op.alter_column(TABLE, "endpoint_ref", existing_type=sa.String(120), nullable=False)
    op.drop_column(TABLE, "runner_ref")
