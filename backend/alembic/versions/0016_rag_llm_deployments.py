"""Persist immutable LLM deployments, data policies, approvals, and audits."""

from collections.abc import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_rag_llm_deployments"
down_revision: str | Sequence[str] | None = "0015_rag_generation_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INSTALLATION_POLICY_ID = UUID("00000000-0000-0000-0000-00000000d001")
INSTALLATION_POLICY_VERSION_ID = UUID("00000000-0000-0000-0000-00000000d002")
MIGRATION_ACTOR_ID = UUID(int=0)


def upgrade() -> None:
    _create_deployment_tables()
    _create_policy_tables()
    _create_approval_tables()
    _create_audit_tables()
    _create_immutable_triggers()
    _replace_configuration_validation(_CONFIGURATION_VALIDATION_V3, "v3")
    _seed_deny_policy()
    _copy_convertible_legacy_profiles()


def downgrade() -> None:
    connection = op.get_bind()
    referenced_count = connection.scalar(
        sa.text(
            """
            SELECT count(*)
            FROM rag_configuration_versions AS version
            JOIN rag_generation_profile_deployments AS binding
              ON binding.profile_id = version.generation_profile_id
            """
        )
    )
    audit_count = connection.scalar(
        sa.text("SELECT count(*) FROM rag_generation_execution_audits")
    )
    approval_count = connection.scalar(
        sa.text("SELECT count(*) FROM rag_external_configuration_approvals")
    )
    user_profile_count = connection.scalar(
        sa.text(
            """
            SELECT count(*)
            FROM rag_generation_profile_deployments AS binding
            LEFT JOIN rag_llm_deployment_migration_profile_copies AS provenance
              ON provenance.profile_id = binding.profile_id
            WHERE provenance.profile_id IS NULL
            """
        )
    )
    if referenced_count or audit_count or approval_count or user_profile_count:
        detail = (
            " user-created deployment-bound profiles exist."
            if user_profile_count
            else ""
        )
        raise RuntimeError(
            "Cannot downgrade while deployment-bound configuration, approval, "
            f"or audit references exist.{detail}"
        )

    _replace_configuration_validation(_CONFIGURATION_VALIDATION_V2, "v2")
    profile_ids = connection.scalars(
        sa.text("SELECT profile_id FROM rag_llm_deployment_migration_profile_copies")
    ).all()
    _drop_immutable_triggers()
    _drop_approval_validation_triggers()
    op.drop_table("rag_generation_audit_workspace_policies")
    op.drop_index(
        "ix_rag_generation_execution_audits_correlation_id",
        table_name="rag_generation_execution_audits",
    )
    op.drop_table("rag_generation_execution_audits")
    op.drop_table("rag_external_configuration_approval_workspaces")
    op.drop_table("rag_external_configuration_approvals")
    op.drop_table("rag_model_deployment_health_checks")
    op.drop_table("rag_workspace_data_policy_versions")
    op.drop_table("rag_workspace_data_policies")
    op.drop_table("rag_installation_data_policy_versions")
    op.drop_table("rag_installation_data_policies")
    op.drop_table("rag_llm_deployment_migration_profile_copies")
    op.drop_table("rag_generation_profile_deployments")
    if profile_ids:
        connection.execute(
            sa.text("DELETE FROM rag_profiles WHERE id = ANY(:profile_ids)").bindparams(
                sa.bindparam(
                    "profile_ids", value=profile_ids, type_=postgresql.ARRAY(sa.Uuid())
                )
            )
        )
    op.drop_table("rag_model_deployment_versions")
    op.drop_table("rag_model_deployments")
    op.drop_table("rag_secret_references")
    op.execute("DROP FUNCTION rag_reject_immutable_llm_metadata_v1()")


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def _create_deployment_tables() -> None:
    op.create_table(
        "rag_secret_references",
        sa.Column("namespace", sa.String(32), nullable=False),
        sa.Column("reference_name", sa.String(120), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "namespace = 'provider_secret'",
            name="ck_rag_secret_references_namespace",
        ),
        sa.CheckConstraint(
            "reference_name ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$' "
            "AND reference_name !~ '^(sk|sess|key|token|secret)-' "
            "AND reference_name !~ '^[0-9a-f]{24,}$'",
            name="ck_rag_secret_references_safe_name",
        ),
        sa.PrimaryKeyConstraint("namespace", "reference_name"),
    )
    op.create_table(
        "rag_model_deployments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rag_model_deployment_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(180), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("model_definition_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("location", sa.String(24), nullable=False),
        sa.Column("allowed_environments", sa.JSON(), nullable=False),
        sa.Column("provider_model_id", sa.String(180), nullable=False),
        sa.Column("endpoint_ref", sa.String(120), nullable=False),
        sa.Column("secret_ref_namespace", sa.String(32), nullable=True),
        sa.Column("secret_ref", sa.String(120), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("external_transfer", sa.Boolean(), nullable=False),
        sa.Column("transmitted_data_categories", sa.JSON(), nullable=False),
        sa.Column("data_processing_notice_ref", sa.String(180), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_seconds", sa.Float(), nullable=False),
        sa.Column("healthcheck_enabled", sa.Boolean(), nullable=False),
        sa.Column("development_only", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("version > 0", name="ck_rag_deployment_versions_positive"),
        sa.CheckConstraint(
            "provider IN ('local_openai_compatible', 'openai_responses')",
            name="ck_rag_deployment_versions_provider",
        ),
        sa.CheckConstraint(
            "location IN ('local', 'on_premise', 'external')",
            name="ck_rag_deployment_versions_location",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0 AND max_retries >= 0 AND retry_backoff_seconds >= 0",
            name="ck_rag_deployment_versions_retry",
        ),
        sa.CheckConstraint(
            "(secret_ref IS NULL AND secret_ref_namespace IS NULL) OR "
            "(secret_ref IS NOT NULL AND secret_ref_namespace IS NOT NULL "
            "AND secret_ref_namespace = 'provider_secret')",
            name="ck_rag_deployment_versions_secret_ref_pair",
        ),
        sa.CheckConstraint(
            "(location = 'external') = external_transfer",
            name="ck_rag_deployment_versions_external_location",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_environments::jsonb) = 'array' "
            "AND jsonb_array_length(allowed_environments::jsonb) > 0 "
            "AND allowed_environments::jsonb <@ "
            "'[\"development\", \"staging\", \"production\"]'::jsonb",
            name="ck_rag_deployment_versions_environments",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capabilities::jsonb) = 'array' "
            "AND jsonb_array_length(capabilities::jsonb) > 0 "
            "AND capabilities::jsonb <@ "
            "'[\"structured_output\", \"contextualization\", \"token_accounting\"]'::jsonb",
            name="ck_rag_deployment_versions_capabilities",
        ),
        sa.CheckConstraint(
            "(external_transfer AND jsonb_array_length(transmitted_data_categories::jsonb) > 0 "
            "AND data_processing_notice_ref IS NOT NULL) "
            "OR (NOT external_transfer AND transmitted_data_categories::jsonb = '[]'::jsonb "
            "AND data_processing_notice_ref IS NULL)",
            name="ck_rag_deployment_versions_transfer_contract",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["rag_model_deployments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_definition_id"],
            ["rag_model_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["secret_ref_namespace", "secret_ref"],
            ["rag_secret_references.namespace", "rag_secret_references.reference_name"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deployment_id", "version"),
    )
    op.create_table(
        "rag_generation_profile_deployments",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["rag_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["deployment_version_id"],
            ["rag_model_deployment_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_table(
        "rag_llm_deployment_migration_profile_copies",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["deployment_version_id"],
            ["rag_model_deployment_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_table(
        "rag_model_deployment_health_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deployment_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("observed_provider_model_id", sa.String(180), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("checked_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_rag_deployment_health_checks_status",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_rag_deployment_health_checks_latency",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_version_id"],
            ["rag_model_deployment_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["checked_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_deployment_health_checks_version_created",
        "rag_model_deployment_health_checks",
        ["deployment_version_id", "created_at"],
    )


def _create_policy_tables() -> None:
    op.create_table(
        "rag_installation_data_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("singleton_key", name="ck_rag_installation_policy_singleton"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton_key"),
    )
    op.create_table(
        "rag_installation_data_policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("outbound_mode", sa.String(32), nullable=False),
        sa.Column("approved_providers", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "version > 0", name="ck_rag_installation_policy_versions_positive"
        ),
        sa.CheckConstraint(
            "outbound_mode IN ('deny', 'approved_providers')",
            name="ck_rag_installation_policy_versions_mode",
        ),
        sa.CheckConstraint(
            "(outbound_mode = 'deny' AND approved_providers::jsonb = '[]'::jsonb) "
            "OR (outbound_mode = 'approved_providers' "
            "AND jsonb_array_length(approved_providers::jsonb) > 0)",
            name="ck_rag_installation_policy_versions_shape",
        ),
        sa.CheckConstraint(
            "approved_providers::jsonb <@ "
            "'[\"local_openai_compatible\", \"openai_responses\"]'::jsonb",
            name="ck_rag_installation_policy_versions_providers",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["rag_installation_data_policies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "version"),
    )
    op.create_table(
        "rag_workspace_data_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_table(
        "rag_workspace_data_policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("outbound_mode", sa.String(32), nullable=False),
        sa.Column("approved_providers", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "version > 0", name="ck_rag_workspace_policy_versions_positive"
        ),
        sa.CheckConstraint(
            "outbound_mode IN ('inherit', 'deny', 'approved_providers')",
            name="ck_rag_workspace_policy_versions_mode",
        ),
        sa.CheckConstraint(
            "(outbound_mode = 'approved_providers' "
            "AND jsonb_array_length(approved_providers::jsonb) > 0) "
            "OR (outbound_mode IN ('inherit', 'deny') "
            "AND approved_providers::jsonb = '[]'::jsonb)",
            name="ck_rag_workspace_policy_versions_shape",
        ),
        sa.CheckConstraint(
            "approved_providers::jsonb <@ "
            "'[\"local_openai_compatible\", \"openai_responses\"]'::jsonb",
            name="ck_rag_workspace_policy_versions_providers",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "workspace_id"],
            ["rag_workspace_data_policies.id", "rag_workspace_data_policies.workspace_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "version"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_index(
        "ix_rag_workspace_policy_versions_workspace_version",
        "rag_workspace_data_policy_versions",
        ["workspace_id", "version"],
    )
    op.execute(_WORKSPACE_POLICY_RESTRICTION_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_rag_workspace_policy_restrict_v1
        BEFORE INSERT ON rag_workspace_data_policy_versions
        FOR EACH ROW EXECUTE FUNCTION rag_restrict_workspace_policy_v1()
        """
    )


def _create_approval_tables() -> None:
    op.create_table(
        "rag_external_configuration_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_version_id", sa.Uuid(), nullable=False),
        sa.Column("installation_policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=False),
        sa.Column("disclosure_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["rag_configuration_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_version_id"],
            ["rag_model_deployment_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["installation_policy_version_id"],
            ["rag_installation_data_policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("configuration_version_id"),
    )
    op.create_table(
        "rag_external_configuration_approval_workspaces",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_policy_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["rag_external_configuration_approvals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_policy_version_id", "workspace_id"],
            [
                "rag_workspace_data_policy_versions.id",
                "rag_workspace_data_policy_versions.workspace_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("approval_id", "workspace_id"),
    )
    op.execute(_APPROVAL_CONTRACT_LOCK_FUNCTION)
    for table in (
        "rag_model_deployment_versions",
        "rag_generation_profile_deployments",
        "rag_installation_data_policy_versions",
        "rag_workspace_data_policy_versions",
        "rag_configuration_workspace_subscriptions",
        "rag_external_configuration_approvals",
        "rag_external_configuration_approval_workspaces",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_approval_contract_lock_v1
            BEFORE INSERT ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION rag_lock_external_approval_contract_v1()
            """
        )
    op.execute(_APPROVAL_VALIDATION_FUNCTION)
    op.execute(_APPROVAL_PARENT_TRIGGER_FUNCTION)
    op.execute(_APPROVAL_WORKSPACE_TRIGGER_FUNCTION)
    op.execute(_APPROVAL_SUBSCRIPTION_TRIGGER_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_rag_external_approvals_validate_v1
        AFTER INSERT ON rag_external_configuration_approvals
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION rag_validate_external_approval_parent_v1()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_rag_external_approval_workspaces_validate_v1
        AFTER INSERT ON rag_external_configuration_approval_workspaces
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION rag_validate_external_approval_workspace_v1()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_rag_external_approval_subscription_validate_v1
        AFTER INSERT ON rag_configuration_workspace_subscriptions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION rag_validate_external_approval_subscription_v1()
        """
    )


def _create_audit_tables() -> None:
    op.create_table(
        "rag_generation_execution_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("generation_profile_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_version_id", sa.Uuid(), nullable=False),
        sa.Column("installation_policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("provider_model_id", sa.String(180), nullable=False),
        sa.Column("location", sa.String(24), nullable=False),
        sa.Column("external_transfer", sa.Boolean(), nullable=False),
        sa.Column("policy_allowed", sa.Boolean(), nullable=False),
        sa.Column("policy_reason_code", sa.String(80), nullable=True),
        sa.Column("prompt_ref", sa.String(180), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("provider_reported_input_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_reported_output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_basis_version", sa.String(80), nullable=True),
        sa.Column("estimated_cost_microunits", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('allowed', 'denied', 'succeeded', 'failed')",
            name="ck_rag_generation_audits_status",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_rag_generation_audits_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_rag_generation_audits_output_tokens",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_rag_generation_audits_latency"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"], ["rag_configuration_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generation_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["deployment_version_id"], ["rag_model_deployment_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["installation_policy_version_id"],
            ["rag_installation_data_policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_generation_execution_audits_correlation_id",
        "rag_generation_execution_audits",
        ["correlation_id"],
    )
    op.create_index(
        "ix_rag_generation_audits_actor_created",
        "rag_generation_execution_audits",
        ["actor_id", "created_at"],
    )
    op.create_index(
        "ix_rag_generation_audits_configuration_created",
        "rag_generation_execution_audits",
        ["configuration_version_id", "created_at"],
    )
    op.create_index(
        "ix_rag_generation_audits_deployment_created",
        "rag_generation_execution_audits",
        ["deployment_version_id", "created_at"],
    )
    op.create_table(
        "rag_generation_audit_workspace_policies",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_policy_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["rag_generation_execution_audits.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_policy_version_id", "workspace_id"],
            [
                "rag_workspace_data_policy_versions.id",
                "rag_workspace_data_policy_versions.workspace_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("audit_id", "workspace_id"),
        sa.UniqueConstraint("audit_id", "workspace_id"),
    )


def _seed_deny_policy() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_installation_data_policies (
                id, singleton_key, created_at, updated_at
            ) VALUES (:id, true, now(), now())
            """
        ),
        {"id": INSTALLATION_POLICY_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_installation_data_policy_versions (
                id, policy_id, version, outbound_mode, approved_providers,
                changed_by, created_at, updated_at
            ) VALUES (
                :id, :policy_id, 1, 'deny', CAST('[]' AS json),
                :changed_by, now(), now()
            )
            """
        ),
        {
            "id": INSTALLATION_POLICY_VERSION_ID,
            "policy_id": INSTALLATION_POLICY_ID,
            "changed_by": MIGRATION_ACTOR_ID,
        },
    )


def _copy_convertible_legacy_profiles() -> None:
    connection = op.get_bind()
    models = connection.execute(
        sa.text(
            """
            SELECT id, name, config
            FROM rag_model_definitions
            WHERE kind = 'llm'
              AND jsonb_typeof(config::jsonb) = 'object'
              AND jsonb_typeof(config::jsonb -> 'provider') = 'string'
              AND config ->> 'provider' = 'openai_compatible'
              AND jsonb_typeof(config::jsonb -> 'data_policy') = 'string'
              AND config ->> 'data_policy' = 'local_only'
              AND jsonb_typeof(config::jsonb -> 'runtime_model') = 'string'
              AND char_length(BTRIM(config ->> 'runtime_model')) BETWEEN 1 AND 180
            ORDER BY id
            """
        )
    ).mappings()
    for model in models:
        deployment_id = uuid4()
        deployment_version_id = uuid4()
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_model_deployments (
                    id, created_by, created_at, updated_at
                ) VALUES (:id, :created_by, now(), now())
                """
            ),
            {"id": deployment_id, "created_by": MIGRATION_ACTOR_ID},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_model_deployment_versions (
                    id, deployment_id, version, display_name, description,
                    model_definition_id, provider, location, allowed_environments,
                    provider_model_id, endpoint_ref, secret_ref_namespace,
                    secret_ref, capabilities,
                    external_transfer, transmitted_data_categories,
                    data_processing_notice_ref, timeout_seconds, max_retries,
                    retry_backoff_seconds, healthcheck_enabled, development_only,
                    created_by, created_at, updated_at
                ) VALUES (
                    :id, :deployment_id, 1, :display_name, :description,
                    :model_id, 'local_openai_compatible', 'local',
                    CAST(:allowed_environments AS json), :provider_model_id,
                    'legacy-local-openai-compatible', NULL, NULL,
                    CAST(:capabilities AS json),
                    false, CAST('[]' AS json), NULL, 30, 0, 0, true, false,
                    :created_by, now(), now()
                )
                """
            ),
            {
                "id": deployment_version_id,
                "deployment_id": deployment_id,
                "display_name": f"Legacy local: {model['name']}"[:180],
                "description": "Migrated local OpenAI-compatible deployment",
                "model_id": model["id"],
                "allowed_environments": '["development", "staging", "production"]',
                "provider_model_id": model["config"]["runtime_model"].strip(),
                "capabilities": '["structured_output", "contextualization"]',
                "created_by": MIGRATION_ACTOR_ID,
            },
        )
        profiles = connection.execute(
            sa.text(
                """
                SELECT profile.id, profile.name, profile.config, profile.evaluation_state
                FROM rag_profiles AS profile
                JOIN rag_profile_model_bindings AS binding
                  ON binding.profile_id = profile.id
                WHERE profile.kind = 'generation'
                  AND binding.role = 'llm'
                  AND binding.model_id = :model_id
                ORDER BY profile.id
                """
            ),
            {"model_id": model["id"]},
        ).mappings()
        for profile in profiles:
            next_version = connection.scalar(
                sa.text(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM rag_profiles
                    WHERE kind = 'generation' AND name = :name
                    """
                ),
                {"name": profile["name"]},
            )
            new_profile_id = uuid4()
            connection.execute(
                sa.text(
                    """
                    INSERT INTO rag_profiles (
                        id, kind, name, version, config, evaluation_state,
                        is_default, created_at, updated_at
                    ) VALUES (
                        :id, 'generation', :name, :version, :config,
                        :evaluation_state, false, now(), now()
                    )
                    """
                ).bindparams(sa.bindparam("config", type_=sa.JSON())),
                {
                    "id": new_profile_id,
                    "name": profile["name"],
                    "version": next_version,
                    "config": profile["config"],
                    "evaluation_state": profile["evaluation_state"],
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO rag_llm_deployment_migration_profile_copies (
                        profile_id, deployment_version_id
                    ) VALUES (:profile_id, :deployment_version_id)
                    """
                ),
                {
                    "profile_id": new_profile_id,
                    "deployment_version_id": deployment_version_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO rag_generation_profile_deployments (
                        profile_id, deployment_version_id
                    ) VALUES (:profile_id, :deployment_version_id)
                    """
                ),
                {
                    "profile_id": new_profile_id,
                    "deployment_version_id": deployment_version_id,
                },
            )


def _replace_configuration_validation(function_sql: str, version: str) -> None:
    other = "v2" if version == "v3" else "v3"
    op.execute(
        f"DROP TRIGGER trg_rag_configuration_versions_validate_{other} "
        "ON rag_configuration_versions"
    )
    op.execute(f"DROP FUNCTION rag_validate_configuration_version_{other}()")
    op.execute(function_sql)
    op.execute(
        f"""
        CREATE TRIGGER trg_rag_configuration_versions_validate_{version}
        BEFORE INSERT OR UPDATE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_validate_configuration_version_{version}()
        """
    )


_IMMUTABLE_TABLES = (
    "rag_secret_references",
    "rag_model_deployment_versions",
    "rag_generation_profile_deployments",
    "rag_llm_deployment_migration_profile_copies",
    "rag_installation_data_policy_versions",
    "rag_workspace_data_policy_versions",
    "rag_external_configuration_approvals",
    "rag_external_configuration_approval_workspaces",
    "rag_model_deployment_health_checks",
    "rag_generation_execution_audits",
    "rag_generation_audit_workspace_policies",
)

def _create_immutable_triggers() -> None:
    op.execute(_DEPLOYMENT_PROFILE_BINDING_VALIDATION_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_rag_generation_profile_deployments_validate_v1
        BEFORE INSERT ON rag_generation_profile_deployments
        FOR EACH ROW EXECUTE FUNCTION rag_validate_deployment_profile_binding_v1()
        """
    )
    op.execute(_MODEL_PROFILE_BINDING_EXCLUSIVITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_rag_profile_model_bindings_deployment_exclusive_v1
        BEFORE INSERT OR UPDATE ON rag_profile_model_bindings
        FOR EACH ROW EXECUTE FUNCTION rag_reject_deployment_profile_model_binding_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_reject_immutable_llm_metadata_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'immutable RAG LLM metadata cannot be updated or deleted';
        END;
        $$
        """
    )
    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable_v1
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION rag_reject_immutable_llm_metadata_v1()
            """
        )


def _drop_immutable_triggers() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_profile_model_bindings_deployment_exclusive_v1 "
        "ON rag_profile_model_bindings"
    )
    op.execute("DROP FUNCTION rag_reject_deployment_profile_model_binding_v1()")
    op.execute(
        "DROP TRIGGER trg_rag_generation_profile_deployments_validate_v1 "
        "ON rag_generation_profile_deployments"
    )
    op.execute("DROP FUNCTION rag_validate_deployment_profile_binding_v1()")
    for table in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_immutable_v1 ON {table}")
    op.execute(
        "DROP TRIGGER trg_rag_workspace_policy_restrict_v1 "
        "ON rag_workspace_data_policy_versions"
    )
    op.execute("DROP FUNCTION rag_restrict_workspace_policy_v1()")


def _drop_approval_validation_triggers() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_external_approval_subscription_validate_v1 "
        "ON rag_configuration_workspace_subscriptions"
    )
    op.execute(
        "DROP TRIGGER trg_rag_external_approval_workspaces_validate_v1 "
        "ON rag_external_configuration_approval_workspaces"
    )
    op.execute(
        "DROP TRIGGER trg_rag_external_approvals_validate_v1 "
        "ON rag_external_configuration_approvals"
    )
    for table in reversed(
        (
            "rag_model_deployment_versions",
            "rag_generation_profile_deployments",
            "rag_installation_data_policy_versions",
            "rag_workspace_data_policy_versions",
            "rag_configuration_workspace_subscriptions",
            "rag_external_configuration_approvals",
            "rag_external_configuration_approval_workspaces",
        )
    ):
        op.execute(f"DROP TRIGGER trg_{table}_approval_contract_lock_v1 ON {table}")
    op.execute("DROP FUNCTION rag_validate_external_approval_subscription_v1()")
    op.execute("DROP FUNCTION rag_validate_external_approval_workspace_v1()")
    op.execute("DROP FUNCTION rag_validate_external_approval_parent_v1()")
    op.execute("DROP FUNCTION rag_validate_external_approval_v1(uuid)")
    op.execute("DROP FUNCTION rag_lock_external_approval_contract_v1()")


_APPROVAL_CONTRACT_LOCK_FUNCTION = """
CREATE FUNCTION rag_lock_external_approval_contract_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('ai-workshop:rag:external-approval-contract:v1', 0)
    );
    RETURN NULL;
END;
$$
"""


_APPROVAL_VALIDATION_FUNCTION = """
CREATE FUNCTION rag_validate_external_approval_v1(candidate_approval_id uuid)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    approval_configuration_id uuid;
    approval_deployment_id uuid;
    approval_installation_policy_id uuid;
    bound_deployment_id uuid;
    deployment_location text;
    deployment_external boolean;
    latest_installation_policy_id uuid;
BEGIN
    SELECT approval.configuration_version_id,
           approval.deployment_version_id,
           approval.installation_policy_version_id,
           binding.deployment_version_id,
           deployment.location,
           deployment.external_transfer
      INTO approval_configuration_id,
           approval_deployment_id,
           approval_installation_policy_id,
           bound_deployment_id,
           deployment_location,
           deployment_external
      FROM rag_external_configuration_approvals AS approval
      JOIN rag_configuration_versions AS configuration
        ON configuration.id = approval.configuration_version_id
      LEFT JOIN rag_generation_profile_deployments AS binding
        ON binding.profile_id = configuration.generation_profile_id
      LEFT JOIN rag_model_deployment_versions AS deployment
        ON deployment.id = approval.deployment_version_id
     WHERE approval.id = candidate_approval_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF bound_deployment_id IS DISTINCT FROM approval_deployment_id
       OR deployment_location IS DISTINCT FROM 'external'
       OR deployment_external IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'external approval deployment does not match configuration';
    END IF;

    SELECT id INTO latest_installation_policy_id
      FROM rag_installation_data_policy_versions
     ORDER BY version DESC, id DESC
     LIMIT 1;
    IF approval_installation_policy_id IS DISTINCT FROM latest_installation_policy_id THEN
        RAISE EXCEPTION 'external approval installation policy snapshot is not current';
    END IF;

    IF EXISTS (
        SELECT workspace_id
          FROM rag_configuration_workspace_subscriptions
         WHERE configuration_version_id = approval_configuration_id
        EXCEPT
        SELECT workspace_id
          FROM rag_external_configuration_approval_workspaces
         WHERE approval_id = candidate_approval_id
    ) OR EXISTS (
        SELECT workspace_id
          FROM rag_external_configuration_approval_workspaces
         WHERE approval_id = candidate_approval_id
        EXCEPT
        SELECT workspace_id
          FROM rag_configuration_workspace_subscriptions
         WHERE configuration_version_id = approval_configuration_id
    ) THEN
        RAISE EXCEPTION 'external approval workspace snapshot set is not exact';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM rag_external_configuration_approval_workspaces AS snapshot
         WHERE snapshot.approval_id = candidate_approval_id
           AND snapshot.workspace_policy_version_id IS DISTINCT FROM (
                SELECT policy.id
                  FROM rag_workspace_data_policy_versions AS policy
                 WHERE policy.workspace_id = snapshot.workspace_id
                 ORDER BY policy.version DESC, policy.id DESC
                 LIMIT 1
           )
    ) THEN
        RAISE EXCEPTION 'external approval workspace policy snapshot is not current';
    END IF;
END;
$$
"""


_APPROVAL_PARENT_TRIGGER_FUNCTION = """
CREATE FUNCTION rag_validate_external_approval_parent_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rag_validate_external_approval_v1(NEW.id);
    RETURN NULL;
END;
$$
"""


_APPROVAL_WORKSPACE_TRIGGER_FUNCTION = """
CREATE FUNCTION rag_validate_external_approval_workspace_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rag_validate_external_approval_v1(NEW.approval_id);
    RETURN NULL;
END;
$$
"""


_APPROVAL_SUBSCRIPTION_TRIGGER_FUNCTION = """
CREATE FUNCTION rag_validate_external_approval_subscription_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    approval_id uuid;
BEGIN
    FOR approval_id IN
        SELECT id FROM rag_external_configuration_approvals
         WHERE configuration_version_id = NEW.configuration_version_id
    LOOP
        PERFORM rag_validate_external_approval_v1(approval_id);
    END LOOP;
    RETURN NULL;
END;
$$
"""


_DEPLOYMENT_PROFILE_BINDING_VALIDATION_FUNCTION = """
CREATE FUNCTION rag_validate_deployment_profile_binding_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    profile_kind text;
BEGIN
    PERFORM rag_lock_technical_components(
        ARRAY[NEW.profile_id], ARRAY[]::uuid[]
    );
    SELECT kind INTO profile_kind
      FROM rag_profiles
     WHERE id = NEW.profile_id;
    IF profile_kind IS DISTINCT FROM 'generation' THEN
        RAISE EXCEPTION 'deployment binding requires a generation profile';
    END IF;
    IF EXISTS (
        SELECT 1 FROM rag_profile_model_bindings
         WHERE profile_id = NEW.profile_id
    ) THEN
        RAISE EXCEPTION 'deployment binding cannot coexist with a model binding';
    END IF;
    IF rag_profile_is_referenced(NEW.profile_id) THEN
        RAISE EXCEPTION 'deployment binding cannot be added to a referenced profile';
    END IF;
    RETURN NEW;
END;
$$
"""


_MODEL_PROFILE_BINDING_EXCLUSIVITY_FUNCTION = """
CREATE FUNCTION rag_reject_deployment_profile_model_binding_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rag_lock_technical_components(
        ARRAY[NEW.profile_id], ARRAY[NEW.model_id]
    );
    IF EXISTS (
        SELECT 1 FROM rag_generation_profile_deployments
         WHERE profile_id = NEW.profile_id
    ) THEN
        RAISE EXCEPTION 'model binding cannot coexist with a deployment binding';
    END IF;
    RETURN NEW;
END;
$$
"""


_WORKSPACE_POLICY_RESTRICTION_FUNCTION = """
CREATE FUNCTION rag_restrict_workspace_policy_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    installation_mode text;
    installation_providers jsonb;
BEGIN
    IF NEW.outbound_mode <> 'approved_providers' THEN
        RETURN NEW;
    END IF;
    SELECT outbound_mode, approved_providers::jsonb
      INTO installation_mode, installation_providers
      FROM rag_installation_data_policy_versions
     ORDER BY version DESC
     LIMIT 1;
    IF installation_mode <> 'approved_providers'
       OR EXISTS (
            SELECT 1
              FROM jsonb_array_elements_text(NEW.approved_providers::jsonb) provider
             WHERE NOT installation_providers ? provider
       ) THEN
        RAISE EXCEPTION 'a Workspace policy cannot widen the Installation policy';
    END IF;
    RETURN NEW;
END;
$$
"""


_RERANKER_VALIDATION = """
    SELECT config::jsonb INTO retrieval_config
    FROM rag_profiles
    WHERE id = NEW.retrieval_profile_id AND kind = 'retrieval';
    IF retrieval_config IS NULL THEN
        RAISE EXCEPTION 'configuration retrieval profile is invalid';
    END IF;
    IF retrieval_config ? 'reranker'
       AND retrieval_config -> 'reranker' <> '{"enabled": false}'::jsonb THEN
        RAISE EXCEPTION 'configured reranker execution is not supported';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(retrieval_config) AS key
        WHERE key LIKE 'reranker%' AND key <> 'reranker'
    ) THEN
        RAISE EXCEPTION 'configured reranker selection is not supported';
    END IF;
    IF EXISTS (
        SELECT 1 FROM rag_profile_model_bindings
        WHERE profile_id = NEW.retrieval_profile_id AND role = 'reranker'
    ) THEN
        RAISE EXCEPTION 'configured reranker binding is not supported';
    END IF;
"""


_CONFIGURATION_VALIDATION_V3 = f"""
CREATE FUNCTION rag_validate_configuration_version_v3()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    selected_profile_ids uuid[];
    bound_model_ids uuid[];
    retrieval_config jsonb;
    generation_config jsonb;
    answer_mode text;
    llm_binding_count integer;
    deployment_binding_count integer;
BEGIN
    selected_profile_ids := array_remove(
        ARRAY[NEW.indexing_profile_id, NEW.retrieval_profile_id, NEW.generation_profile_id],
        NULL
    );
    PERFORM rag_lock_technical_components(selected_profile_ids, ARRAY[]::uuid[]);
    SELECT COALESCE(array_agg(DISTINCT model_id ORDER BY model_id), ARRAY[]::uuid[])
      INTO bound_model_ids
      FROM rag_profile_model_bindings
     WHERE profile_id = ANY(selected_profile_ids);
    PERFORM rag_lock_technical_components(ARRAY[]::uuid[], bound_model_ids);

    SELECT mode INTO answer_mode
      FROM rag_answer_policy_versions
     WHERE id = NEW.answer_policy_version_id
       AND configuration_id = NEW.configuration_id
       AND version = NEW.version;
    IF answer_mode IS NULL THEN RAISE EXCEPTION 'configuration answer policy is invalid'; END IF;
    IF answer_mode = 'extractive' AND NEW.generation_profile_id IS NOT NULL THEN
        RAISE EXCEPTION 'extractive configuration cannot select generation';
    END IF;
    IF answer_mode = 'generative' AND NEW.generation_profile_id IS NULL THEN
        RAISE EXCEPTION 'generative configuration requires generation';
    END IF;
    {_RERANKER_VALIDATION}
    IF NEW.generation_profile_id IS NOT NULL THEN
        SELECT config::jsonb INTO generation_config
          FROM rag_profiles
         WHERE id = NEW.generation_profile_id AND kind = 'generation';
        IF generation_config IS NULL
           OR NOT generation_config ?& ARRAY[
                'prompt_ref', 'context_prompt_ref', 'citation_mode',
                'context_policy', 'generation'
           ]
           OR generation_config ->> 'citation_mode' <> 'required' THEN
            RAISE EXCEPTION 'configuration generation profile is invalid';
        END IF;
        SELECT count(*) INTO llm_binding_count
          FROM rag_profile_model_bindings AS binding
          JOIN rag_model_definitions AS model ON model.id = binding.model_id
         WHERE binding.profile_id = NEW.generation_profile_id
           AND binding.role = 'llm' AND model.kind = 'llm';
        SELECT count(*) INTO deployment_binding_count
          FROM rag_generation_profile_deployments
         WHERE profile_id = NEW.generation_profile_id;
        IF NOT (
            (llm_binding_count = 1 AND deployment_binding_count = 0)
            OR (llm_binding_count = 0 AND deployment_binding_count = 1)
        ) OR EXISTS (
            SELECT 1 FROM rag_profile_model_bindings
             WHERE profile_id = NEW.generation_profile_id AND role <> 'llm'
        ) THEN
            RAISE EXCEPTION 'configuration generation binding is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$
"""


_CONFIGURATION_VALIDATION_V2 = f"""
CREATE FUNCTION rag_validate_configuration_version_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    selected_profile_ids uuid[];
    bound_model_ids uuid[];
    retrieval_config jsonb;
    generation_config jsonb;
    answer_mode text;
    llm_binding_count integer;
BEGIN
    selected_profile_ids := array_remove(
        ARRAY[NEW.indexing_profile_id, NEW.retrieval_profile_id, NEW.generation_profile_id], NULL
    );
    PERFORM rag_lock_technical_components(selected_profile_ids, ARRAY[]::uuid[]);
    SELECT COALESCE(array_agg(DISTINCT model_id ORDER BY model_id), ARRAY[]::uuid[])
      INTO bound_model_ids FROM rag_profile_model_bindings
     WHERE profile_id = ANY(selected_profile_ids);
    PERFORM rag_lock_technical_components(ARRAY[]::uuid[], bound_model_ids);
    SELECT mode INTO answer_mode FROM rag_answer_policy_versions
     WHERE id = NEW.answer_policy_version_id
       AND configuration_id = NEW.configuration_id AND version = NEW.version;
    IF answer_mode IS NULL THEN RAISE EXCEPTION 'configuration answer policy is invalid'; END IF;
    IF answer_mode = 'extractive' AND NEW.generation_profile_id IS NOT NULL THEN
        RAISE EXCEPTION 'extractive configuration cannot select generation';
    END IF;
    IF answer_mode = 'generative' AND NEW.generation_profile_id IS NULL THEN
        RAISE EXCEPTION 'generative configuration requires generation';
    END IF;
    {_RERANKER_VALIDATION}
    IF NEW.generation_profile_id IS NOT NULL THEN
        SELECT config::jsonb INTO generation_config FROM rag_profiles
         WHERE id = NEW.generation_profile_id AND kind = 'generation';
        IF generation_config IS NULL
           OR NOT generation_config ?& ARRAY[
                'prompt_ref', 'context_prompt_ref', 'citation_mode',
                'context_policy', 'generation'
           ] OR generation_config ->> 'citation_mode' <> 'required' THEN
            RAISE EXCEPTION 'configuration generation profile is invalid';
        END IF;
        SELECT count(*) INTO llm_binding_count
          FROM rag_profile_model_bindings AS binding
          JOIN rag_model_definitions AS model ON model.id = binding.model_id
         WHERE binding.profile_id = NEW.generation_profile_id
           AND binding.role = 'llm' AND model.kind = 'llm';
        IF llm_binding_count <> 1 OR EXISTS (
            SELECT 1 FROM rag_profile_model_bindings
             WHERE profile_id = NEW.generation_profile_id AND role <> 'llm'
        ) THEN RAISE EXCEPTION 'configuration generation LLM binding is invalid'; END IF;
    END IF;
    RETURN NEW;
END;
$$
"""
