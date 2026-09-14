"""Persist versioned purge inventories, receipts, and minimal proofs."""

import sqlalchemy as sa

from alembic import op

revision = "0039_asset_purge_inventory"
down_revision = "0038_asset_provenance"
branch_labels = None
depends_on = None

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_SHA256_SQL = r"^[0-9a-f]{64}$"
_TABLES = (
    "asset_purge_inventories",
    "asset_purge_inventory_targets",
    "asset_purge_inventory_participants",
    "asset_purge_inventory_resources",
    "asset_purge_receipts",
    "asset_purge_proofs",
    "asset_purge_proof_targets",
    "asset_purge_proof_participants",
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_asset_purge_jobs_workspace_id",
        "asset_purge_jobs",
        ["workspace_id", "id"],
    )
    op.create_table(
        "asset_purge_inventories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("binding", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_inventories"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["asset_purge_jobs.workspace_id", "asset_purge_jobs.id"],
            name="fk_asset_purge_inventories_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            "version",
            name="uq_asset_purge_inventories_workspace_job_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_purge_inventories_workspace_id",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_asset_purge_inventories_version_positive",
        ),
        sa.CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_inventories_binding",
        ),
    )
    op.create_table(
        "asset_purge_inventory_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_inventory_targets"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "inventory_id"],
            ["asset_purge_inventories.workspace_id", "asset_purge_inventories.id"],
            name="fk_asset_purge_inventory_targets_inventory",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "target_kind IN ('document','folder')",
            name="ck_asset_purge_inventory_targets_kind",
        ),
        sa.CheckConstraint(
            "generation > 0",
            name="ck_asset_purge_inventory_targets_generation_positive",
        ),
        sa.CheckConstraint(
            "(target_kind='document' AND asset_version_id IS NOT NULL) OR "
            "(target_kind='folder' AND asset_version_id IS NULL)",
            name="ck_asset_purge_inventory_targets_shape",
        ),
    )
    op.create_index(
        "uq_asset_purge_inventory_document_versions",
        "asset_purge_inventory_targets",
        ["inventory_id", "target_id", "asset_version_id"],
        unique=True,
        postgresql_where=sa.text("target_kind = 'document'"),
    )
    op.create_index(
        "uq_asset_purge_inventory_folders",
        "asset_purge_inventory_targets",
        ["inventory_id", "target_id"],
        unique=True,
        postgresql_where=sa.text("target_kind = 'folder'"),
    )
    op.create_table(
        "asset_purge_inventory_participants",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_id", sa.Uuid(), nullable=False),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("contract_version", sa.BigInteger(), nullable=False),
        sa.Column("exhausted", sa.Boolean(), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("legacy_resolved", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            name="pk_asset_purge_inventory_participants",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "inventory_id"],
            ["asset_purge_inventories.workspace_id", "asset_purge_inventories.id"],
            name="fk_asset_purge_inventory_participants_inventory",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "inventory_id",
            "participant",
            name="uq_asset_purge_inventory_participants_workspace_inventory_key",
        ),
        sa.CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_inventory_participants_participant",
        ),
        sa.CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_inventory_participants_contract_positive",
        ),
    )
    op.create_table(
        "asset_purge_inventory_resources",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_id", sa.Uuid(), nullable=False),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_revision", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            "kind",
            "resource_id",
            "resource_revision",
            name="pk_asset_purge_inventory_resources",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "inventory_id", "participant"],
            [
                "asset_purge_inventory_participants.workspace_id",
                "asset_purge_inventory_participants.inventory_id",
                "asset_purge_inventory_participants.participant",
            ],
            name="fk_asset_purge_inventory_resources_participant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"kind ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_inventory_resources_kind",
        ),
        sa.CheckConstraint(
            "resource_revision > 0",
            name="ck_asset_purge_inventory_resources_revision_positive",
        ),
    )
    op.create_table(
        "asset_purge_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_id", sa.Uuid(), nullable=False),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("attempt", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("binding", sa.CHAR(64), nullable=False),
        sa.Column("contract_version", sa.BigInteger(), nullable=False),
        sa.Column("deleted", sa.BigInteger(), nullable=False),
        sa.Column("retained_shared", sa.BigInteger(), nullable=False),
        sa.Column("residual_owned", sa.BigInteger(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            "attempt",
            name="pk_asset_purge_receipts",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "inventory_id", "participant"],
            [
                "asset_purge_inventory_participants.workspace_id",
                "asset_purge_inventory_participants.inventory_id",
                "asset_purge_inventory_participants.participant",
            ],
            name="fk_asset_purge_receipts_participant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "attempt > 0",
            name="ck_asset_purge_receipts_attempt_positive",
        ),
        sa.CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_receipts_binding",
        ),
        sa.CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_receipts_contract_positive",
        ),
        sa.CheckConstraint(
            "deleted >= 0 AND retained_shared >= 0 AND residual_owned >= 0",
            name="ck_asset_purge_receipts_counts_nonnegative",
        ),
    )
    _create_proof_tables()


def _create_proof_tables() -> None:
    op.create_table(
        "asset_purge_proofs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_version", sa.BigInteger(), nullable=False),
        sa.Column("inventory_binding", sa.CHAR(64), nullable=False),
        sa.Column("binding", sa.CHAR(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("policy_version", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "backup_state", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "external_state",
            sa.String(32),
            nullable=False,
            server_default="unverified",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_proofs"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["asset_purge_jobs.workspace_id", "asset_purge_jobs.id"],
            name="fk_asset_purge_proofs_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            name="uq_asset_purge_proofs_workspace_job",
        ),
        sa.CheckConstraint(
            "inventory_version > 0",
            name="ck_asset_purge_proofs_inventory_version_positive",
        ),
        sa.CheckConstraint(
            f"inventory_binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_proofs_inventory_binding",
        ),
        sa.CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_proofs_binding",
        ),
        sa.CheckConstraint(
            "policy_version > 0",
            name="ck_asset_purge_proofs_policy_version_positive",
        ),
        sa.CheckConstraint(
            "backup_state = 'pending'",
            name="ck_asset_purge_proofs_backup_state",
        ),
        sa.CheckConstraint(
            "external_state = 'unverified'",
            name="ck_asset_purge_proofs_external_state",
        ),
    )
    op.create_table(
        "asset_purge_proof_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proof_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_proof_targets"),
        sa.ForeignKeyConstraint(
            ["proof_id"],
            ["asset_purge_proofs.id"],
            name="fk_asset_purge_proof_targets_proof",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "target_kind IN ('document','folder')",
            name="ck_asset_purge_proof_targets_kind",
        ),
        sa.CheckConstraint(
            "generation > 0",
            name="ck_asset_purge_proof_targets_generation_positive",
        ),
        sa.CheckConstraint(
            "(target_kind='document' AND asset_version_id IS NOT NULL) OR "
            "(target_kind='folder' AND asset_version_id IS NULL)",
            name="ck_asset_purge_proof_targets_shape",
        ),
    )
    op.create_index(
        "uq_asset_purge_proof_document_versions",
        "asset_purge_proof_targets",
        ["proof_id", "target_id", "asset_version_id"],
        unique=True,
        postgresql_where=sa.text("target_kind = 'document'"),
    )
    op.create_index(
        "uq_asset_purge_proof_folders",
        "asset_purge_proof_targets",
        ["proof_id", "target_id"],
        unique=True,
        postgresql_where=sa.text("target_kind = 'folder'"),
    )
    op.create_table(
        "asset_purge_proof_participants",
        sa.Column("proof_id", sa.Uuid(), nullable=False),
        sa.Column("participant", sa.String(80), nullable=False),
        sa.Column("contract_version", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted", sa.BigInteger(), nullable=False),
        sa.Column("retained_shared", sa.BigInteger(), nullable=False),
        sa.Column("residual_owned", sa.BigInteger(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint(
            "proof_id",
            "participant",
            name="pk_asset_purge_proof_participants",
        ),
        sa.ForeignKeyConstraint(
            ["proof_id"],
            ["asset_purge_proofs.id"],
            name="fk_asset_purge_proof_participants_proof",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_proof_participants_participant",
        ),
        sa.CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_proof_participants_contract_positive",
        ),
        sa.CheckConstraint(
            "attempt > 0",
            name="ck_asset_purge_proof_participants_attempt_positive",
        ),
        sa.CheckConstraint(
            "deleted >= 0 AND retained_shared >= 0 AND residual_owned >= 0",
            name="ck_asset_purge_proof_participants_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "verified AND residual_owned = 0",
            name="ck_asset_purge_proof_participants_successful",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE " + ",".join(_TABLES) + " IN SHARE ROW EXCLUSIVE MODE"
    )
    for table_name in _TABLES:
        if connection.exec_driver_sql(
            f"SELECT EXISTS (SELECT 1 FROM {table_name})"
        ).scalar_one():
            raise RuntimeError("asset_purge_inventory_downgrade_unsafe")

    op.drop_table("asset_purge_proof_participants")
    op.drop_index(
        "uq_asset_purge_proof_folders", table_name="asset_purge_proof_targets"
    )
    op.drop_index(
        "uq_asset_purge_proof_document_versions",
        table_name="asset_purge_proof_targets",
    )
    op.drop_table("asset_purge_proof_targets")
    op.drop_table("asset_purge_proofs")
    op.drop_table("asset_purge_receipts")
    op.drop_table("asset_purge_inventory_resources")
    op.drop_table("asset_purge_inventory_participants")
    op.drop_index(
        "uq_asset_purge_inventory_folders",
        table_name="asset_purge_inventory_targets",
    )
    op.drop_index(
        "uq_asset_purge_inventory_document_versions",
        table_name="asset_purge_inventory_targets",
    )
    op.drop_table("asset_purge_inventory_targets")
    op.drop_table("asset_purge_inventories")
    op.drop_constraint(
        "uq_asset_purge_jobs_workspace_id",
        "asset_purge_jobs",
        type_="unique",
    )
