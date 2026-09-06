"""Persist OCR image provenance for structural elements and evidence units."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_rag_ocr_provenance"
down_revision: str | Sequence[str] | None = "0017_rag_document_processing_ocr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("rag_structural_elements", "rag_evidence_units")


def upgrade() -> None:
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "source_kind",
                sa.String(length=32),
                nullable=False,
                server_default="normalized_text",
            ),
        )
        op.add_column(table_name, sa.Column("source_part", sa.String(length=700)))
        op.add_column(table_name, sa.Column("image_sha256", sa.String(length=64)))
        op.add_column(table_name, sa.Column("table_cell", sa.JSON()))
        if table_name == "rag_structural_elements":
            op.add_column(
                table_name,
                sa.Column(
                    "evidence_eligible",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )
            op.add_column(table_name, sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"))
        op.execute(
            f"UPDATE {table_name} SET source_kind = 'pdf_page' WHERE page IS NOT NULL"
        )
        op.alter_column(table_name, "source_kind", server_default=None)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        if table_name == "rag_structural_elements":
            op.drop_column(table_name, "warnings")
            op.drop_column(table_name, "evidence_eligible")
        op.drop_column(table_name, "table_cell")
        op.drop_column(table_name, "image_sha256")
        op.drop_column(table_name, "source_part")
        op.drop_column(table_name, "source_kind")
