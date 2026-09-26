"""Persist internal issue history and immutable document versions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0051_issue_history"
down_revision = "0050_conversation_attachments"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def actor(table: str) -> sa.Column:
    return sa.Column(
        "actor_id",
        sa.Uuid(),
        sa.ForeignKey("users.id", ondelete="RESTRICT", name=f"fk_{table}_users"),
    )


def upgrade() -> None:
    op.create_table(
        "issue_categories",
        sa.UniqueConstraint("code", name="uq_issue_categories_code"),
        sa.PrimaryKeyConstraint("id", name="pk_issue_categories"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(100), unique=False, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("revision > 0", name="ck_issue_categories_1"),
    )
    op.create_table(
        "issues",
        sa.UniqueConstraint("issue_key", name="uq_issues_issue_key"),
        sa.PrimaryKeyConstraint("id", name="pk_issues"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("issue_key", sa.String(100), unique=False, nullable=False),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey(
                "issue_categories.id", ondelete="RESTRICT", name="fk_issues_issue_categories"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *[
            sa.Column(name, sa.Text(), nullable=False)
            for name in ["symptom", "cause", "resolution"]
        ],
        *[
            sa.Column(name, JSONB(), nullable=False)
            for name in ["verification", "remaining", "commits"]
        ],
        sa.Column("revision", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("revision > 0", name="ck_issues_1"),
        sa.CheckConstraint("status IN ('open','implemented','verified')", name="ck_issues_2"),
    )
    op.create_index("ix_issues_updated_id", "issues", ["updated_at", "id"])
    op.create_table(
        "issue_events",
        sa.PrimaryKeyConstraint("id", name="pk_issue_events"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Uuid(),
            sa.ForeignKey("issues.id", ondelete="RESTRICT", name="fk_issue_events_issues"),
            nullable=False,
        ),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        actor("issue_events"),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("before_revision", sa.Integer()),
        sa.Column("after_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
    )
    op.create_index("ix_issue_events_issue_id", "issue_events", ["issue_id"])
    op.create_table(
        "issue_documents",
        sa.UniqueConstraint("import_source_key", name="uq_issue_documents_import_source_key"),
        sa.PrimaryKeyConstraint("id", name="pk_issue_documents"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("import_source_key", sa.String(2000), unique=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("revision > 0 AND current_version > 0", name="ck_issue_documents_1"),
    )
    op.create_table(
        "issue_document_versions",
        sa.PrimaryKeyConstraint("document_id", "version", name="pk_issue_document_versions"),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey(
                "issue_documents.id",
                ondelete="RESTRICT",
                name="fk_issue_document_versions_issue_documents",
            ),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source_path", sa.String(2000)),
        sa.Column("source_commit", sa.String(200)),
        actor("issue_document_versions"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_issue_document_versions_1"),
        sa.CheckConstraint("octet_length(content) <= 524288", name="ck_issue_document_versions_2"),
        sa.UniqueConstraint("document_id", "sha256", name="uq_issue_document_versions_content"),
    )
    op.create_foreign_key(
        "fk_issue_document_current_version",
        "issue_documents",
        "issue_document_versions",
        ["id", "current_version"],
        ["document_id", "version"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "issue_document_links",
        sa.PrimaryKeyConstraint(
            "issue_id", "document_id", "version", name="pk_issue_document_links"
        ),
        sa.Column(
            "issue_id",
            sa.Uuid(),
            sa.ForeignKey("issues.id", ondelete="RESTRICT", name="fk_issue_document_links_issues"),
            primary_key=True,
        ),
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "version"],
            ["issue_document_versions.document_id", "issue_document_versions.version"],
            name="fk_issue_document_links_version",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "issue_import_runs",
        sa.PrimaryKeyConstraint("source_key", name="pk_issue_import_runs"),
        sa.Column("source_key", sa.String(200), primary_key=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_import_runs_users"),
            nullable=False,
        ),
        sa.Column("summary", JSONB(), nullable=False),
    )
    op.create_table(
        "issue_commands",
        sa.PrimaryKeyConstraint("actor_id", "operation", "request_id", name="pk_issue_commands"),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_commands_users"),
            primary_key=True,
        ),
        sa.Column("operation", sa.String(200), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("issue_commands")
    op.drop_table("issue_import_runs")
    op.drop_table("issue_document_links")
    op.drop_constraint("fk_issue_document_current_version", "issue_documents", type_="foreignkey")
    op.drop_table("issue_document_versions")
    op.drop_table("issue_documents")
    op.drop_table("issue_events")
    op.drop_table("issues")
    op.drop_table("issue_categories")
