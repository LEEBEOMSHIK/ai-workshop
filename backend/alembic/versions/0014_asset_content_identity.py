"""Use content hashes for document duplicate identity."""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_asset_content_identity"
down_revision: str | Sequence[str] | None = "0013_system_baseline_indexing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "documents_workspace_id_folder_id_name_key",
        "documents",
        type_="unique",
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index("ix_asset_versions_sha256", "asset_versions", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_asset_versions_sha256", table_name="asset_versions")
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.create_unique_constraint(
        "documents_workspace_id_folder_id_name_key",
        "documents",
        ["workspace_id", "folder_id", "name"],
    )
