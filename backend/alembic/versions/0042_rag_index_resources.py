"""Track immutable RAG index resources and attempts."""

# ruff: noqa: E501
import sqlalchemy as sa

from alembic import op

revision = "0042_rag_index_resources"
down_revision = "0041_rag_artifact_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_rag_index_builds_tracking_identity",
        "rag_index_builds",
        ["id", "projection_id", "document_processing_profile_id", "indexing_profile_id"],
    )
    op.create_unique_constraint(
        "uq_rag_projections_tracking_identity",
        "rag_document_projections",
        ["id", "asset_version_id", "document_processing_profile_id", "indexing_profile_id"],
    )
    op.create_unique_constraint(
        "uq_rag_ingestion_tracking_identity",
        "rag_ingestion_jobs",
        [
            "job_id",
            "projection_id",
            "asset_version_id",
            "document_processing_profile_id",
            "indexing_profile_id",
        ],
    )
    op.execute("""
CREATE TABLE rag_index_resources (
	build_id UUID NOT NULL,
	projection_id UUID NOT NULL,
	job_id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	document_id UUID NOT NULL,
	asset_version_id UUID NOT NULL,
	document_processing_profile_id UUID NOT NULL,
	indexing_profile_id UUID NOT NULL,
	revision BIGINT NOT NULL,
	store_id VARCHAR(80) NOT NULL,
	cluster_uuid VARCHAR(128) NOT NULL,
	index_name VARCHAR(255) NOT NULL,
	alias VARCHAR(255) NOT NULL,
	name_contract_version INTEGER NOT NULL,
	mapping_version INTEGER NOT NULL,
	vector_dimension INTEGER NOT NULL,
	similarity VARCHAR(32) NOT NULL,
	index_uuid VARCHAR(128),
	input_fingerprint VARCHAR(64),
	chunk_ids_sha256 VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (build_id),
	CONSTRAINT fk_rag_index_resources_build FOREIGN KEY(build_id, projection_id, document_processing_profile_id, indexing_profile_id) REFERENCES rag_index_builds (id, projection_id, document_processing_profile_id, indexing_profile_id) ON DELETE RESTRICT,
	CONSTRAINT fk_rag_index_resources_projection FOREIGN KEY(projection_id, asset_version_id, document_processing_profile_id, indexing_profile_id) REFERENCES rag_document_projections (id, asset_version_id, document_processing_profile_id, indexing_profile_id) ON DELETE RESTRICT,
	CONSTRAINT fk_rag_index_resources_ingestion FOREIGN KEY(job_id, projection_id, asset_version_id, document_processing_profile_id, indexing_profile_id) REFERENCES rag_ingestion_jobs (job_id, projection_id, asset_version_id, document_processing_profile_id, indexing_profile_id) ON DELETE RESTRICT,
	CONSTRAINT fk_rag_index_resources_job FOREIGN KEY(job_id, workspace_id, asset_version_id) REFERENCES jobs (id, workspace_id, asset_version_id) ON DELETE RESTRICT,
	CONSTRAINT fk_rag_index_resources_document FOREIGN KEY(workspace_id, document_id) REFERENCES documents (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_rag_index_resources_version FOREIGN KEY(document_id, asset_version_id) REFERENCES asset_versions (document_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_rag_index_resources_cluster_name UNIQUE (cluster_uuid, index_name),
	CONSTRAINT ck_rag_index_resources_input_pair CHECK ((input_fingerprint IS NULL AND chunk_ids_sha256 IS NULL) OR (input_fingerprint IS NOT NULL AND chunk_ids_sha256 IS NOT NULL AND chunk_ids_sha256 ~ '^[0-9a-f]{64}$')),
	CONSTRAINT ck_rag_index_resources_revision CHECK (revision > 0),
	CONSTRAINT ck_rag_index_resources_store CHECK (store_id ~ '^[a-z][a-z0-9_]{0,79}$'),
	CONSTRAINT ck_rag_index_resources_cluster CHECK (cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'),
	CONSTRAINT ck_rag_index_resources_uuid CHECK (index_uuid IS NULL OR index_uuid ~ '^[A-Za-z0-9_-]{1,128}$'),
	CONSTRAINT ck_rag_index_resources_fingerprint CHECK (input_fingerprint IS NULL OR input_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_rag_index_resources_names CHECK (index_name ~ '^[a-z0-9][a-z0-9._-]{0,254}$' AND alias ~ '^[a-z0-9][a-z0-9._-]{0,254}$'),
	CONSTRAINT ck_rag_index_resources_descriptor CHECK (name_contract_version = 1 AND mapping_version > 0 AND vector_dimension > 0 AND similarity = 'cosine')
)
""")
    op.execute("""
CREATE TABLE rag_index_attempts (
	build_id UUID NOT NULL,
	operation VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	result_code VARCHAR(80),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_rag_index_attempts_resource FOREIGN KEY(build_id) REFERENCES rag_index_resources (build_id) ON DELETE RESTRICT,
	CONSTRAINT ck_rag_index_attempts_operation CHECK (operation = 'prepare'),
	CONSTRAINT ck_rag_index_attempts_state CHECK (state IN ('open','closed')),
	CONSTRAINT ck_rag_index_attempts_result CHECK (result_code IS NULL OR result_code IN ('prepared','rag_index_binding_mismatch','rag_index_identity_conflict','rag_index_input_conflict','rag_index_observation_failed')),
	CONSTRAINT ck_rag_index_attempts_close_shape CHECK ((state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR (state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL))
)
""")
    op.execute(
        "CREATE UNIQUE INDEX uq_rag_index_attempts_open_resource ON rag_index_attempts (build_id) WHERE state = 'open'"
    )
    op.execute(
        """CREATE FUNCTION rag_index_resource_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF ROW(NEW.build_id,NEW.projection_id,NEW.job_id,NEW.workspace_id,NEW.document_id,NEW.asset_version_id,NEW.document_processing_profile_id,NEW.indexing_profile_id,NEW.store_id,NEW.cluster_uuid,NEW.index_name,NEW.alias,NEW.name_contract_version,NEW.mapping_version,NEW.vector_dimension,NEW.similarity,NEW.created_at) IS DISTINCT FROM ROW(OLD.build_id,OLD.projection_id,OLD.job_id,OLD.workspace_id,OLD.document_id,OLD.asset_version_id,OLD.document_processing_profile_id,OLD.indexing_profile_id,OLD.store_id,OLD.cluster_uuid,OLD.index_name,OLD.alias,OLD.name_contract_version,OLD.mapping_version,OLD.vector_dimension,OLD.similarity,OLD.created_at) OR (OLD.index_uuid IS NOT NULL AND NEW.index_uuid IS DISTINCT FROM OLD.index_uuid) OR (OLD.input_fingerprint IS NOT NULL AND NEW.input_fingerprint IS DISTINCT FROM OLD.input_fingerprint) OR (OLD.chunk_ids_sha256 IS NOT NULL AND NEW.chunk_ids_sha256 IS DISTINCT FROM OLD.chunk_ids_sha256) THEN RAISE EXCEPTION 'rag_index_identity_conflict' USING ERRCODE = '23514'; END IF; RETURN NEW; END $$"""
    )
    op.execute(
        "CREATE TRIGGER rag_index_resource_identity_guard BEFORE UPDATE ON rag_index_resources FOR EACH ROW EXECUTE FUNCTION rag_index_resource_identity_guard()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("rag_index_resources", "rag_index_attempts"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("rag_index_downgrade_blocked")
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM asset_source_relations WHERE participant = 'rag_index_resources')"
        )
    ):
        raise RuntimeError("rag_index_downgrade_blocked")
    op.drop_table("rag_index_attempts")
    op.drop_table("rag_index_resources")
    op.execute("DROP FUNCTION rag_index_resource_identity_guard()")
    op.drop_constraint("uq_rag_ingestion_tracking_identity", "rag_ingestion_jobs", type_="unique")
    op.drop_constraint(
        "uq_rag_projections_tracking_identity", "rag_document_projections", type_="unique"
    )
    op.drop_constraint("uq_rag_index_builds_tracking_identity", "rag_index_builds", type_="unique")
