"""Allow explicit native Anthropic deployments; preserve all existing approvals."""

from alembic import op

revision = "0068_anthropic_messages"
down_revision = "0067_stored_model_comparisons"
branch_labels = None
depends_on = None

TABLE = "rag_model_deployment_versions"
OLD_PROVIDERS = (
    "'local_openai_compatible', 'local_transformers', 'openai_responses', 'development_codex_exec'"
)
ANTHROPIC_CONTRACT = (
    "provider <> 'anthropic_messages' OR (external_transfer "
    "AND location = 'external' AND secret_ref IS NOT NULL AND btrim(secret_ref) <> '' "
    "AND jsonb_array_length(transmitted_data_categories::jsonb) > 0 "
    "AND data_processing_notice_ref IS NOT NULL AND btrim(data_processing_notice_ref) <> '')"
)


def _replace_constraints(*, native: bool) -> None:
    for suffix in ("provider", "execution_reference"):
        op.drop_constraint(f"ck_rag_deployment_versions_{suffix}", TABLE, type_="check")
    providers = OLD_PROVIDERS + (", 'anthropic_messages'" if native else "")
    op.create_check_constraint(
        "ck_rag_deployment_versions_provider",
        TABLE,
        f"provider IN ({providers})",
    )
    http_providers = "'local_openai_compatible', 'openai_responses'"
    if native:
        http_providers += ", 'anthropic_messages'"
    reference = (
        "(provider = 'development_codex_exec' AND endpoint_ref IS NULL "
        "AND runner_ref IS NOT NULL AND btrim(runner_ref) <> '' "
        "AND local_model_ref IS NULL) OR "
        "(provider = 'local_transformers' AND endpoint_ref IS NULL "
        "AND runner_ref IS NULL AND local_model_ref IS NOT NULL) OR "
        f"(provider IN ({http_providers}) "
        "AND endpoint_ref IS NOT NULL AND btrim(endpoint_ref) <> '' "
        "AND runner_ref IS NULL AND local_model_ref IS NULL)"
    )
    op.create_check_constraint("ck_rag_deployment_versions_execution_reference", TABLE, reference)
    allowed = (
        '["local_openai_compatible", "openai_responses", '
        '"development_codex_exec", "local_transformers"'
    )
    allowed += ', "anthropic_messages"]' if native else "]"
    for scope in ("installation", "workspace"):
        table = f"rag_{scope}_data_policy_versions"
        name = f"ck_rag_{scope}_policy_versions_providers"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"approved_providers::jsonb <@ '{allowed}'::jsonb")


def upgrade() -> None:
    _replace_constraints(native=True)
    op.create_check_constraint(
        "ck_rag_deployment_versions_anthropic_contract", TABLE, ANTHROPIC_CONTRACT
    )


def downgrade() -> None:
    # Offline SQL retains this guard. Never delete or silently rewrite deployment/approval data.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM rag_model_deployment_versions
                       WHERE provider = 'anthropic_messages')
                OR EXISTS (SELECT 1 FROM rag_installation_data_policy_versions
                           WHERE approved_providers::jsonb @> '["anthropic_messages"]'::jsonb)
                OR EXISTS (SELECT 1 FROM rag_workspace_data_policy_versions
                           WHERE approved_providers::jsonb @> '["anthropic_messages"]'::jsonb)
            THEN
                RAISE EXCEPTION 'Cannot downgrade while Anthropic deployments or approvals exist';
            END IF;
        END $$;
    """)
    op.drop_constraint("ck_rag_deployment_versions_anthropic_contract", TABLE, type_="check")
    _replace_constraints(native=False)
