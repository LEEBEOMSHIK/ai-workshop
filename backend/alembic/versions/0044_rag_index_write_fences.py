"""Add immutable document-scoped RAG write fences."""

import sqlalchemy as sa

from alembic import op

revision = "0044_rag_index_write_fences"
down_revision = "0043_rag_alias_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_index_write_fences",
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_rag_index_write_fences_document",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_rag_index_write_fences_generation"),
    )
    op.execute("""
        CREATE FUNCTION rag_index_write_fence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'rag_index_inventory_changed' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER rag_index_write_fence_guard BEFORE UPDATE ON rag_index_write_fences
        FOR EACH ROW EXECUTE FUNCTION rag_index_write_fence_guard()
    """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM rag_index_write_fences)")):
        raise RuntimeError("rag_index_write_fence_downgrade_blocked")
    op.drop_table("rag_index_write_fences")
    op.execute("DROP FUNCTION rag_index_write_fence_guard()")
