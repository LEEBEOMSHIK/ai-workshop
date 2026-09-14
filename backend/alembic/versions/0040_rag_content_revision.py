"""Track the current revision of each RAG SQL projection bundle."""

import sqlalchemy as sa

from alembic import op

revision = "0040_rag_content_revision"
down_revision = "0039_asset_purge_inventory"
branch_labels = None
depends_on = None

_PARTICIPANT = "rag_document_sql"


def upgrade() -> None:
    op.add_column(
        "rag_document_projections",
        sa.Column("content_revision", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_rag_document_projections_content_revision_positive",
        "rag_document_projections",
        "content_revision IS NULL OR content_revision > 0",
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE rag_document_projections,asset_source_relations IN SHARE ROW EXCLUSIVE MODE"
    )
    tracked_revision = connection.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM rag_document_projections WHERE content_revision IS NOT NULL)"
    ).scalar_one()
    tracked_relation = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM asset_source_relations WHERE participant = :participant)"
        ),
        {"participant": _PARTICIPANT},
    ).scalar_one()
    if tracked_revision or tracked_relation:
        raise RuntimeError("rag_content_revision_downgrade_unsafe")

    op.drop_constraint(
        "ck_rag_document_projections_content_revision_positive",
        "rag_document_projections",
        type_="check",
    )
    op.drop_column("rag_document_projections", "content_revision")
