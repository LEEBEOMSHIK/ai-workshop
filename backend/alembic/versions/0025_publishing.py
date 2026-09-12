"""Add private publishing drafts, immutable revisions, and delivery outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_publishing"
down_revision: str | Sequence[str] | None = "0024_learning_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publishing_studies",
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("approved_digest", sa.String(length=64), nullable=True),
        sa.Column("applied_sequence", sa.Integer(), nullable=False),
        sa.Column("applied_action", sa.String(length=16), nullable=True),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_revision > 0",
            name="ck_publishing_studies_current_revision_positive",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_publishing_studies_sequence_nonnegative",
        ),
        sa.CheckConstraint(
            "applied_sequence >= 0 AND applied_sequence <= sequence",
            name="ck_publishing_studies_applied_sequence",
        ),
        sa.CheckConstraint(
            "(applied_sequence = 0 AND applied_action IS NULL AND applied_revision IS NULL) "
            "OR (applied_sequence > 0 AND ((applied_action = 'publish' AND "
            "applied_revision IS NOT NULL AND applied_revision > 0) OR "
            "(applied_action = 'withdraw' AND applied_revision IS NULL)))",
            name="ck_publishing_studies_applied_state",
        ),
        sa.PrimaryKeyConstraint("slug", name="pk_publishing_studies"),
    )
    op.create_index(
        "ix_publishing_studies_updated_slug",
        "publishing_studies",
        ["updated_at", "slug"],
        unique=False,
    )
    op.create_table(
        "publishing_revisions",
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("canonical_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_publishing_revisions_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["slug"],
            ["publishing_studies.slug"],
            name="fk_publishing_revisions_study",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("slug", "revision", name="pk_publishing_revisions"),
    )
    op.create_foreign_key(
        "fk_publishing_studies_current_revision",
        "publishing_studies",
        "publishing_revisions",
        ["slug", "current_revision"],
        ["slug", "revision"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "publishing_commands",
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("expected_digest", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("export_payload", sa.LargeBinary(), nullable=True),
        sa.Column("receipt_slug", sa.String(length=200), nullable=True),
        sa.Column("receipt_sequence", sa.Integer(), nullable=True),
        sa.Column("receipt_request_id", sa.String(length=200), nullable=True),
        sa.Column("receipt_action", sa.String(length=16), nullable=True),
        sa.Column("delivery_error_code", sa.String(length=100), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_publishing_commands_sequence_positive",
        ),
        sa.CheckConstraint(
            "expected_revision > 0",
            name="ck_publishing_commands_expected_revision_positive",
        ),
        sa.CheckConstraint(
            "(action = 'publish' AND export_payload IS NOT NULL) OR "
            "(action = 'withdraw' AND export_payload IS NULL)",
            name="ck_publishing_commands_action_payload",
        ),
        sa.CheckConstraint(
            "(applied_at IS NULL AND receipt_slug IS NULL AND receipt_sequence IS NULL "
            "AND receipt_request_id IS NULL AND receipt_action IS NULL) OR "
            "(applied_at IS NOT NULL AND receipt_slug = slug AND receipt_sequence = sequence "
            "AND receipt_request_id = request_id AND receipt_action = action)",
            name="ck_publishing_commands_receipt_state",
        ),
        sa.ForeignKeyConstraint(
            ["slug"],
            ["publishing_studies.slug"],
            name="fk_publishing_commands_study",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_id", name="pk_publishing_commands"),
        sa.UniqueConstraint(
            "slug",
            "sequence",
            name="uq_publishing_commands_slug_sequence",
        ),
    )
    op.create_index(
        "ix_publishing_commands_pending",
        "publishing_commands",
        ["applied_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_publishing_commands_pending", table_name="publishing_commands")
    op.drop_table("publishing_commands")
    op.drop_constraint(
        "fk_publishing_studies_current_revision",
        "publishing_studies",
        type_="foreignkey",
    )
    op.drop_table("publishing_revisions")
    op.drop_index("ix_publishing_studies_updated_slug", table_name="publishing_studies")
    op.drop_table("publishing_studies")
