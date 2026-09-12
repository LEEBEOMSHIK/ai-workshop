"""Append-only exact Codex connectivity proof and body-free stage audit."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0029_codex_verification"
down_revision = "0028_codex_execution_slots"
branch_labels = None
depends_on = None


def _binding_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "configuration_version_id",
            sa.Uuid(),
            sa.ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "generation_profile_id",
            sa.Uuid(),
            sa.ForeignKey("rag_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "deployment_version_id",
            sa.Uuid(),
            sa.ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rag_codex_verification_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), unique=True, nullable=False),
        *_binding_columns(),
        sa.Column(
            "checked_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("binding", JSONB(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("usage_present", sa.Boolean(), nullable=False),
        sa.Column("safe_error_code", sa.String(80)),
        sa.Column("requested_provider_model_id", sa.String(180), nullable=False),
        sa.Column("observed_provider_model_id", sa.String(180)),
        sa.CheckConstraint(
            "binding IS NULL OR jsonb_typeof(binding) = 'object'", name="ck_codex_verify_binding"
        ),
        sa.CheckConstraint(
            "(success AND binding IS NOT NULL AND usage_present AND safe_error_code IS NULL) "
            "OR (NOT success AND safe_error_code IS NOT NULL)",
            name="ck_codex_verify_outcome",
        ),
    )
    op.create_index(
        "ix_codex_verify_configuration_sequence",
        "rag_codex_verification_attempts",
        ["configuration_version_id", "sequence"],
    )
    op.create_table(
        "rag_codex_stage_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        *_binding_columns(),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.CheckConstraint("stage IN ('contextualize','generate')", name="ck_codex_audit_stage"),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name="ck_codex_audit_details"),
    )
    op.create_index(
        "ix_codex_stage_audit_request", "rag_codex_stage_audits", ["request_id", "created_at"]
    )
    op.execute("""CREATE FUNCTION codex_verification_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'codex_verification_append_only'; END; $$""")
    for table in ("rag_codex_verification_attempts", "rag_codex_stage_audits"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION codex_verification_append_only()"
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE rag_codex_verification_attempts, rag_codex_stage_audits "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM rag_codex_verification_attempts) "
            "OR EXISTS (SELECT 1 FROM rag_codex_stage_audits)"
        )
    ):
        raise RuntimeError("codex_verification_records_exist")
    op.drop_table("rag_codex_stage_audits")
    op.drop_table("rag_codex_verification_attempts")
    op.execute("DROP FUNCTION codex_verification_append_only()")
