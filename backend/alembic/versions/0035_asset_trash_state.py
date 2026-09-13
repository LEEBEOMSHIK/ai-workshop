"""Persist asset lifecycle state, retention policies, and trash batches."""

import sqlalchemy as sa

from ai_workshop.platform.assets.trash_migration_preflight import (
    assert_trash_migration_ready,
)
from alembic import op

revision = "0035_asset_trash_state"
down_revision = "0034_asset_metadata_revision"
branch_labels = None
depends_on = None

_LIFECYCLE_VALUES = (
    "active",
    "trashed",
    "purge_pending",
    "purging",
    "retry_wait",
    "blocked",
)


def _add_asset_state(table: str, entity: str) -> None:
    op.add_column(
        table,
        sa.Column("lifecycle", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        table,
        sa.Column(
            "lifecycle_generation",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(table, sa.Column("trash_batch_id", sa.Uuid(), nullable=True))
    op.add_column(
        table,
        sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        table,
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    lifecycle_values = ", ".join(f"'{value}'" for value in _LIFECYCLE_VALUES)
    op.create_check_constraint(
        f"ck_{entity}_lifecycle",
        table,
        f"lifecycle IN ({lifecycle_values})",
    )
    op.create_check_constraint(
        f"ck_{entity}_lifecycle_generation",
        table,
        "lifecycle_generation >= 1",
    )
    op.create_check_constraint(
        f"ck_{entity}_trash_state",
        table,
        "(lifecycle = 'active' AND trash_batch_id IS NULL "
        "AND trashed_at IS NULL AND purge_after IS NULL) OR "
        "(lifecycle <> 'active' AND trash_batch_id IS NOT NULL "
        "AND trashed_at IS NOT NULL AND purge_after IS NOT NULL "
        "AND purge_after > trashed_at)",
    )
    op.create_foreign_key(
        f"fk_{entity}_trash_batch",
        table,
        "asset_trash_batches",
        ["workspace_id", "trash_batch_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents IN SHARE ROW EXCLUSIVE MODE"
    )
    assert_trash_migration_ready(connection)

    op.create_table(
        "asset_retention_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_retention_policies"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_asset_retention_policies_workspace",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_retention_policies_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_asset_retention_policies_workspace_version",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_asset_retention_policies_version_positive",
        ),
        sa.CheckConstraint(
            "days > 0",
            name="ck_asset_retention_policies_days_positive",
        ),
    )
    op.execute("""
        CREATE FUNCTION asset_retention_policy_reject_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'asset_retention_policy_immutable';
        END $$;
        CREATE TRIGGER trg_asset_retention_policies_reject_update
        BEFORE UPDATE ON asset_retention_policies FOR EACH ROW
        EXECUTE FUNCTION asset_retention_policy_reject_update();
    """)
    op.create_table(
        "asset_trash_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_trash_batches"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_asset_trash_batches_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "policy_version_id"],
            ["asset_retention_policies.workspace_id", "asset_retention_policies.id"],
            name="fk_asset_trash_batches_policy",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_trash_batches_workspace_id",
        ),
        sa.CheckConstraint(
            "purge_after > trashed_at",
            name="ck_asset_trash_batches_deadline",
        ),
    )
    _add_asset_state("folders", "folder")
    _add_asset_state("documents", "document")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents, asset_retention_policies, asset_trash_batches "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    unsafe = connection.exec_driver_sql("""
        SELECT
          EXISTS (SELECT 1 FROM asset_retention_policies)
          OR EXISTS (SELECT 1 FROM asset_trash_batches)
          OR EXISTS (
            SELECT 1 FROM folders
            WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
               OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL OR purge_after IS NOT NULL
          )
          OR EXISTS (
            SELECT 1 FROM documents
            WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
               OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL OR purge_after IS NOT NULL
          )
    """).scalar_one()
    if unsafe:
        raise RuntimeError("asset_trash_downgrade_unsafe")

    for table, entity in (("documents", "document"), ("folders", "folder")):
        op.drop_constraint(f"fk_{entity}_trash_batch", table, type_="foreignkey")
        op.drop_constraint(f"ck_{entity}_trash_state", table, type_="check")
        op.drop_constraint(f"ck_{entity}_lifecycle_generation", table, type_="check")
        op.drop_constraint(f"ck_{entity}_lifecycle", table, type_="check")
        for column in (
            "purge_after",
            "trashed_at",
            "trash_batch_id",
            "lifecycle_generation",
            "lifecycle",
        ):
            op.drop_column(table, column)
    op.drop_table("asset_trash_batches")
    op.execute(
        "DROP TRIGGER trg_asset_retention_policies_reject_update "
        "ON asset_retention_policies"
    )
    op.execute("DROP FUNCTION asset_retention_policy_reject_update()")
    op.drop_table("asset_retention_policies")
