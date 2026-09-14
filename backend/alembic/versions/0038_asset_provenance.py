"""Persist exact asset source-to-resource provenance relations."""

import sqlalchemy as sa

from alembic import op

revision = "0038_asset_provenance"
down_revision = "0037_active_folder_names"
branch_labels = None
depends_on = None

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_documents_workspace_id_id",
        "documents",
        ["workspace_id", "id"],
    )
    op.create_unique_constraint(
        "uq_asset_versions_document_id_id",
        "asset_versions",
        ["document_id", "id"],
    )
    op.create_table(
        "asset_source_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_revision", sa.BigInteger(), nullable=False),
        sa.Column("relation_kind", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_source_relations"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_asset_source_relations_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_asset_source_relations_asset_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "asset_version_id",
            "participant",
            "kind",
            "resource_id",
            "resource_revision",
            "relation_kind",
            name="uq_asset_source_relations_source_resource_relation",
        ),
        sa.CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_source_relations_participant",
        ),
        sa.CheckConstraint(
            f"kind ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_source_relations_kind",
        ),
        sa.CheckConstraint(
            "resource_revision > 0",
            name="ck_asset_source_relations_resource_revision_positive",
        ),
        sa.CheckConstraint(
            "relation_kind IN ('source_copy','derived_artifact','authored_reference')",
            name="ck_asset_source_relations_relation_kind",
        ),
    )
    op.create_index(
        "ix_asset_source_relations_resource",
        "asset_source_relations",
        ["workspace_id", "participant", "kind", "resource_id", "resource_revision"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE asset_source_relations IN SHARE ROW EXCLUSIVE MODE"
    )
    if connection.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM asset_source_relations)"
    ).scalar_one():
        raise RuntimeError("asset_provenance_downgrade_unsafe")

    op.drop_index(
        "ix_asset_source_relations_resource",
        table_name="asset_source_relations",
    )
    op.drop_table("asset_source_relations")
    op.drop_constraint(
        "uq_asset_versions_document_id_id",
        "asset_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_documents_workspace_id_id",
        "documents",
        type_="unique",
    )
