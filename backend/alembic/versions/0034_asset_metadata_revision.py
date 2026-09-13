"""Independent location metadata revisions for folders and documents."""

import sqlalchemy as sa

from alembic import op

revision = "0034_asset_metadata_revision"
down_revision = "0033_workspace_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, constraint in (
        ("folders", "ck_folder_metadata_revision"),
        ("documents", "ck_document_metadata_revision"),
    ):
        op.add_column(
            table, sa.Column("metadata_revision", sa.Integer(), nullable=False, server_default="1")
        )
        op.create_check_constraint(constraint, table, "metadata_revision >= 1")


def downgrade() -> None:
    for table, constraint in (
        ("folders", "ck_folder_metadata_revision"),
        ("documents", "ck_document_metadata_revision"),
    ):
        op.drop_constraint(constraint, table)
        op.drop_column(table, "metadata_revision")
