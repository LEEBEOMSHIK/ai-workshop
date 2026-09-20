"""Reserve HTTP intake before body consumption; retain planned and actual ownership."""

import sqlalchemy as sa

from alembic import op

revision = "0047_http_upload_intake"
down_revision = "0046_document_temporary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "http_upload_intakes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("new_document", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=True),
        sa.Column("existing_document_id", sa.Uuid(), nullable=True),
        sa.Column("original_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("actual_document_id", sa.Uuid(), nullable=True),
        sa.Column("actual_version_id", sa.Uuid(), nullable=True),
        sa.Column("attached_original_id", sa.Uuid(), nullable=True),
        sa.Column("attached", sa.Boolean(), nullable=False),
        sa.Column("store_id", sa.String(length=80), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(NOT attached AND actual_document_id IS NULL AND actual_version_id IS NULL AND "
            "attached_original_id IS NULL) OR (attached AND original_attempt_id IS NOT NULL AND "
            "actual_document_id IS NOT NULL AND actual_version_id IS NOT NULL AND "
            "attached_original_id IS NOT NULL AND actual_document_id = document_id AND "
            "actual_version_id = asset_version_id AND attached_original_id = "
            "original_attempt_id)",
            name="ck_intake_attachment",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('writer_unconfirmed','cleanup_unconfirmed','ownership_failed')",
            name="ck_intake_error_code",
        ),
        sa.CheckConstraint(
            "(new_document AND generation IS NULL AND existing_document_id IS NULL) OR (NOT "
            "new_document AND generation IS NOT NULL AND generation >= 1 AND "
            "existing_document_id IS NOT NULL AND existing_document_id = document_id)",
            name="ck_intake_existing_source",
        ),
        sa.CheckConstraint(
            "state IN ('open','closed','cleaning','cleaned') AND revision = CASE state WHEN "
            "'open' THEN 1 WHEN 'closed' THEN 2 WHEN 'cleaning' THEN 3 WHEN 'cleaned' THEN 4 "
            "END + CASE WHEN original_attempt_id IS NULL THEN 0 ELSE 1 END + CASE WHEN attached "
            "THEN 1 ELSE 0 END",
            name="ck_intake_state_revision",
        ),
        sa.CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_intake_store"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actual_document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_intake_actual_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actual_document_id", "actual_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_intake_actual_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attached_original_id"],
            ["original_file_resources.id"],
            name="fk_intake_attached_original",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "existing_document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_intake_existing_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_attempt_id", "workspace_id", "document_id", "asset_version_id"],
            [
                "original_upload_attempts.id",
                "original_upload_attempts.workspace_id",
                "original_upload_attempts.document_id",
                "original_upload_attempts.asset_version_id",
            ],
            name="fk_intake_original_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("original_attempt_id", name="uq_intake_original_attempt"),
    )
    op.create_index("ix_intake_document", "http_upload_intakes", ["workspace_id", "document_id"])
    op.create_index("ix_intake_unattached", "http_upload_intakes", ["workspace_id", "attached"])


def downgrade() -> None:
    op.drop_table("http_upload_intakes")
