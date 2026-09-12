"""Body-free exact Codex approvals and independent durable consumption ledger."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027_codex_call_approvals"
down_revision = "0026_codex_runner_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_codex_call_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "configuration_version_id",
            sa.Uuid(),
            sa.ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "deployment_version_id",
            sa.Uuid(),
            sa.ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "generation_profile_id",
            sa.Uuid(),
            sa.ForeignKey("rag_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("binding", postgresql.JSONB(), nullable=False),
        sa.Column("approved_payload_sha256", sa.String(64), nullable=False),
        sa.Column("input_classification", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "operation IN ('search','evaluation','connection_check')",
            name="ck_codex_call_operation",
        ),
        sa.CheckConstraint("stage IN ('contextualize','generate')", name="ck_codex_call_stage"),
        sa.CheckConstraint(
            "approved_payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_call_digest"
        ),
        sa.CheckConstraint("expires_at > issued_at", name="ck_codex_call_expiry"),
        sa.CheckConstraint(
            "input_classification IN ('public','synthetic')", name="ck_codex_call_classification"
        ),
        sa.CheckConstraint("jsonb_typeof(binding) = 'object'", name="ck_codex_call_binding"),
    )
    op.create_table(
        "rag_codex_evidence_approvals",
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column(
            "approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_evidence_digest"),
        sa.CheckConstraint(
            "classification IN ('public','synthetic')", name="ck_codex_evidence_classification"
        ),
    )
    op.create_table(
        "rag_codex_call_consumptions",
        sa.Column("approval_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('contextualize','generate')", name="ck_codex_consumption_stage"
        ),
    )
    op.execute("""
        CREATE FUNCTION rag_codex_approval_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'codex_approval_immutable';
            END IF;
            IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM
               (to_jsonb(OLD) - 'revoked_at') OR
               (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
                RAISE EXCEPTION 'codex_approval_immutable';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("rag_codex_call_approvals", "rag_codex_evidence_approvals"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION rag_codex_approval_immutable()"
        )
    op.execute("""
        CREATE FUNCTION rag_codex_consumption_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'codex_consumption_append_only';
        END $$
    """)
    op.execute(
        "CREATE TRIGGER rag_codex_consumptions_immutable BEFORE UPDATE OR DELETE "
        "ON rag_codex_call_consumptions FOR EACH ROW "
        "EXECUTE FUNCTION rag_codex_consumption_immutable()"
    )


def downgrade() -> None:
    # Acquire all table locks before checking: concurrent inserts cannot bypass refusal.
    op.execute(
        "LOCK TABLE rag_codex_call_approvals, rag_codex_evidence_approvals, "
        "rag_codex_call_consumptions IN ACCESS EXCLUSIVE MODE"
    )
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM rag_codex_call_approvals) OR
               EXISTS (SELECT 1 FROM rag_codex_evidence_approvals) OR
               EXISTS (SELECT 1 FROM rag_codex_call_consumptions) THEN
                RAISE EXCEPTION 'codex_approval_downgrade_requires_empty_tables';
            END IF;
        END $$
    """)
    op.drop_table("rag_codex_call_consumptions")
    op.drop_table("rag_codex_evidence_approvals")
    op.drop_table("rag_codex_call_approvals")
    op.execute("DROP FUNCTION rag_codex_consumption_immutable()")
    op.execute("DROP FUNCTION rag_codex_approval_immutable()")
