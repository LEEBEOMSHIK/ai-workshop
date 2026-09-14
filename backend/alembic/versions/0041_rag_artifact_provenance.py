"""Track RAG artifact bundles, slots, and exact writer attempts."""

import sqlalchemy as sa

from alembic import op

revision = "0041_rag_artifact_provenance"
down_revision = "0040_rag_content_revision"
branch_labels = None
depends_on = None

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_SHA256_SQL = r"^[0-9a-f]{64}$"
_PARTICIPANT = "rag_ingestion_artifacts"
_TABLES = ("rag_artifact_attempts", "rag_artifact_slots", "rag_artifact_bundles")


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_jobs_id_workspace_asset_version",
        "jobs",
        ["id", "workspace_id", "asset_version_id"],
    )
    op.create_unique_constraint(
        "uq_rag_document_projections_id_asset_version",
        "rag_document_projections",
        ["id", "asset_version_id"],
    )
    op.create_unique_constraint(
        "uq_rag_ingestion_jobs_job_projection_asset_version",
        "rag_ingestion_jobs",
        ["job_id", "projection_id", "asset_version_id"],
    )
    op.create_table(
        "rag_artifact_bundles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_artifact_bundles"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_rag_artifact_bundles_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_rag_artifact_bundles_asset_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "workspace_id", "asset_version_id"],
            ["jobs.id", "jobs.workspace_id", "jobs.asset_version_id"],
            name="fk_rag_artifact_bundles_job_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "projection_id", "asset_version_id"],
            [
                "rag_ingestion_jobs.job_id",
                "rag_ingestion_jobs.projection_id",
                "rag_ingestion_jobs.asset_version_id",
            ],
            name="fk_rag_artifact_bundles_ingestion_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["projection_id", "asset_version_id"],
            ["rag_document_projections.id", "rag_document_projections.asset_version_id"],
            name="fk_rag_artifact_bundles_projection_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "projection_id", name="uq_rag_artifact_bundles_projection"
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_rag_artifact_bundles_revision_positive"
        ),
    )
    op.create_table(
        "rag_artifact_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("store_id", sa.String(80), nullable=False),
        sa.Column("store_binding_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_key", sa.String(700), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("published_size", sa.BigInteger(), nullable=True),
        sa.Column("published_sha256", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_artifact_slots"),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["rag_artifact_bundles.id"],
            name="fk_rag_artifact_slots_bundle",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "bundle_id", "role", name="uq_rag_artifact_slots_bundle_role"
        ),
        sa.UniqueConstraint(
            "store_id", "canonical_key", name="uq_rag_artifact_slots_store_key"
        ),
        sa.UniqueConstraint(
            "id",
            "store_id",
            "store_binding_id",
            name="uq_rag_artifact_slots_id_store_binding",
        ),
        sa.CheckConstraint(
            "role IN ('parsed','chunks','embeddings')",
            name="ck_rag_artifact_slots_role",
        ),
        sa.CheckConstraint(
            f"store_id ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_slots_store_id",
        ),
        sa.CheckConstraint(
            "char_length(canonical_key) > 0",
            name="ck_rag_artifact_slots_canonical_key_nonempty",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','verified')", name="ck_rag_artifact_slots_state"
        ),
        sa.CheckConstraint(
            "(state = 'reserved' AND published_size IS NULL AND published_sha256 IS NULL) OR "
            "(state = 'verified' AND published_size IS NOT NULL AND published_size >= 0 AND "
            "published_sha256 IS NOT NULL AND "
            f"published_sha256 ~ '{_SHA256_SQL}')",
            name="ck_rag_artifact_slots_publication_shape",
        ),
    )
    op.create_table(
        "rag_artifact_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slot_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.String(80), nullable=False),
        sa.Column("store_binding_id", sa.Uuid(), nullable=False),
        sa.Column("temporary_key", sa.String(700), nullable=False),
        sa.Column("proposed_size", sa.BigInteger(), nullable=False),
        sa.Column("proposed_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("result_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rag_artifact_attempts"),
        sa.ForeignKeyConstraint(
            ["slot_id", "store_id", "store_binding_id"],
            [
                "rag_artifact_slots.id",
                "rag_artifact_slots.store_id",
                "rag_artifact_slots.store_binding_id",
            ],
            name="fk_rag_artifact_attempts_slot_store_binding",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "store_id",
            "temporary_key",
            name="uq_rag_artifact_attempts_store_temp_key",
        ),
        sa.CheckConstraint(
            f"store_id ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_attempts_store_id",
        ),
        sa.CheckConstraint(
            "char_length(temporary_key) > 0",
            name="ck_rag_artifact_attempts_temporary_key_nonempty",
        ),
        sa.CheckConstraint(
            "proposed_size >= 0",
            name="ck_rag_artifact_attempts_proposed_size_nonnegative",
        ),
        sa.CheckConstraint(
            f"proposed_sha256 ~ '{_SHA256_SQL}'",
            name="ck_rag_artifact_attempts_proposed_sha256",
        ),
        sa.CheckConstraint(
            "state IN ('open','closed')", name="ck_rag_artifact_attempts_state"
        ),
        sa.CheckConstraint(
            "result_code IS NULL OR "
            f"result_code ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_attempts_result_code",
        ),
        sa.CheckConstraint(
            "(state = 'open' AND result_code IS NULL AND closed_at IS NULL) OR "
            "(state = 'closed' AND result_code IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_rag_artifact_attempts_close_shape",
        ),
    )
    op.create_index(
        "uq_rag_artifact_attempts_open_slot",
        "rag_artifact_attempts",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE rag_artifact_attempts,rag_artifact_slots,rag_artifact_bundles,"
        "asset_source_relations IN SHARE ROW EXCLUSIVE MODE"
    )
    for table_name in _TABLES:
        if connection.exec_driver_sql(
            f"SELECT EXISTS (SELECT 1 FROM {table_name})"
        ).scalar_one():
            raise RuntimeError("rag_artifact_provenance_downgrade_unsafe")
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM asset_source_relations "
            "WHERE participant = :participant)"
        ),
        {"participant": _PARTICIPANT},
    ).scalar_one():
        raise RuntimeError("rag_artifact_provenance_downgrade_unsafe")

    op.drop_index(
        "uq_rag_artifact_attempts_open_slot", table_name="rag_artifact_attempts"
    )
    op.drop_table("rag_artifact_attempts")
    op.drop_table("rag_artifact_slots")
    op.drop_table("rag_artifact_bundles")
    op.drop_constraint(
        "uq_rag_ingestion_jobs_job_projection_asset_version",
        "rag_ingestion_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "uq_rag_document_projections_id_asset_version",
        "rag_document_projections",
        type_="unique",
    )
    op.drop_constraint(
        "uq_jobs_id_workspace_asset_version", "jobs", type_="unique"
    )
