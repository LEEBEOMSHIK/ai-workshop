"""Add document-processing identity to RAG configurations and artifacts."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0017_rag_document_processing_ocr"
down_revision: str | Sequence[str] | None = "0016_rag_llm_deployments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_DOCUMENT_PROCESSING_PROFILE_ID = UUID(
    "00000000-0000-0000-0000-000000000207"
)
LEGACY_DOCUMENT_PROCESSING_CONFIG = {
    "parser_policy": {
        "schema_version": 1,
        "routes": {
            "text/plain": {"name": "plain_text", "version": "1"},
            "text/markdown": {"name": "markdown", "version": "2"},
            "text/x-markdown": {"name": "markdown", "version": "2"},
            "application/pdf": {
                "name": "pymupdf",
                "version": "legacy-per-element",
            },
        },
    },
    "ocr": {"enabled": False},
}

_TABLES_WITH_PROCESSING_ID = (
    "rag_configuration_versions",
    "rag_document_projections",
    "rag_ingestion_jobs",
    "rag_index_builds",
    "rag_asset_handoff_failures",
)


def _unique_name(table_name: str, columns: tuple[str, ...]) -> str:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint["column_names"]) == columns:
            name = constraint.get("name")
            if isinstance(name, str):
                return name
    raise RuntimeError(f"Unique constraint for {table_name}{columns!r} was not found.")


def _seed_legacy_profile() -> None:
    connection = op.get_bind()
    existing = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config::jsonb, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :profile_id
               OR (kind = 'document_processing'
                   AND name = 'legacy-text-document-processing'
                   AND version = 1)
            """
        ),
        {"profile_id": LEGACY_DOCUMENT_PROCESSING_PROFILE_ID},
    ).mappings().all()
    expected_config = LEGACY_DOCUMENT_PROCESSING_CONFIG
    if existing:
        row = existing[0]
        if (
            len(existing) != 1
            or row["id"] != LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
            or row["kind"] != "document_processing"
            or row["name"] != "legacy-text-document-processing"
            or row["version"] != 1
            or row["config"] != expected_config
            or row["evaluation_state"] != "passed"
            or row["is_default"] is not True
        ):
            raise RuntimeError("Legacy document-processing profile identity conflicts.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                id, kind, name, version, config, evaluation_state, is_default
            ) VALUES (
                :profile_id, 'document_processing',
                'legacy-text-document-processing', 1,
                CAST(:config AS json), 'passed', true
            )
            """
        ),
        {
            "profile_id": LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
            "config": json.dumps(expected_config),
        },
    )


def _replace_profile_reference_function(*, include_document_processing: bool) -> None:
    processing_clause = (
        "OR document_processing_profile_id = candidate_profile_id"
        if include_document_processing
        else ""
    )
    artifact_clauses = ""
    if include_document_processing:
        artifact_clauses = """
            OR EXISTS (
                SELECT 1 FROM rag_document_projections
                WHERE document_processing_profile_id = candidate_profile_id
            )
            OR EXISTS (
                SELECT 1 FROM rag_ingestion_jobs
                WHERE document_processing_profile_id = candidate_profile_id
            )
            OR EXISTS (
                SELECT 1 FROM rag_index_builds
                WHERE document_processing_profile_id = candidate_profile_id
            )
            OR EXISTS (
                SELECT 1 FROM rag_asset_handoff_failures
                WHERE document_processing_profile_id = candidate_profile_id
            )
        """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION rag_profile_is_referenced(candidate_profile_id uuid)
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM rag_configuration_versions
                WHERE indexing_profile_id = candidate_profile_id
                   OR retrieval_profile_id = candidate_profile_id
                   OR generation_profile_id = candidate_profile_id
                   {processing_clause}
            )
            {artifact_clauses}
        $$
        """
    )


def _create_configuration_validation() -> None:
    op.execute(
        """
        CREATE FUNCTION rag_validate_document_processing_selection_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            selected_config jsonb;
        BEGIN
            PERFORM rag_lock_technical_components(
                ARRAY[NEW.document_processing_profile_id], ARRAY[]::uuid[]
            );
            SELECT config::jsonb INTO selected_config
              FROM rag_profiles
             WHERE id = NEW.document_processing_profile_id
               AND kind = 'document_processing';
            IF selected_config IS NULL
               OR NOT selected_config ?& ARRAY['parser_policy', 'ocr'] THEN
                RAISE EXCEPTION 'configuration document-processing profile is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_validate_document_processing
        BEFORE INSERT OR UPDATE ON rag_configuration_versions
        FOR EACH ROW
        EXECUTE FUNCTION rag_validate_document_processing_selection_v1()
        """
    )


def upgrade() -> None:
    _seed_legacy_profile()
    for table_name in _TABLES_WITH_PROCESSING_ID:
        op.add_column(
            table_name,
            sa.Column("document_processing_profile_id", sa.Uuid(), nullable=True),
        )

    for table_name in _TABLES_WITH_PROCESSING_ID:
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET document_processing_profile_id = :profile_id"
            ).bindparams(profile_id=LEGACY_DOCUMENT_PROCESSING_PROFILE_ID)
        )
        op.alter_column(table_name, "document_processing_profile_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table_name}_document_processing_profile_id",
            table_name,
            "rag_profiles",
            ["document_processing_profile_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    projection_unique = _unique_name(
        "rag_document_projections", ("asset_version_id", "indexing_profile_id")
    )
    op.drop_constraint(
        projection_unique, "rag_document_projections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_rag_document_projections_processing_indexing",
        "rag_document_projections",
        ["asset_version_id", "document_processing_profile_id", "indexing_profile_id"],
    )

    ingestion_unique = _unique_name(
        "rag_ingestion_jobs", ("asset_version_id", "indexing_profile_id")
    )
    op.drop_constraint(ingestion_unique, "rag_ingestion_jobs", type_="unique")
    op.create_unique_constraint(
        "uq_rag_ingestion_jobs_processing_indexing",
        "rag_ingestion_jobs",
        ["asset_version_id", "document_processing_profile_id", "indexing_profile_id"],
    )

    op.drop_constraint(
        "rag_asset_handoff_failures_pkey",
        "rag_asset_handoff_failures",
        type_="primary",
    )
    op.create_primary_key(
        "pk_rag_asset_handoff_failures_processing_indexing",
        "rag_asset_handoff_failures",
        ["asset_version_id", "document_processing_profile_id", "indexing_profile_id"],
    )
    _replace_profile_reference_function(include_document_processing=True)
    _create_configuration_validation()


def downgrade() -> None:
    connection = op.get_bind()
    non_legacy_references = 0
    for table_name in _TABLES_WITH_PROCESSING_ID:
        non_legacy_references += int(
            connection.scalar(
                sa.text(
                    f"SELECT count(*) FROM {table_name} "
                    "WHERE document_processing_profile_id <> :profile_id"
                ),
                {"profile_id": LEGACY_DOCUMENT_PROCESSING_PROFILE_ID},
            )
            or 0
        )
    if non_legacy_references:
        raise RuntimeError(
            "Cannot downgrade while non-legacy document-processing references exist."
        )

    op.execute(
        "DROP TRIGGER trg_rag_configuration_versions_validate_document_processing "
        "ON rag_configuration_versions"
    )
    op.execute("DROP FUNCTION rag_validate_document_processing_selection_v1()")
    _replace_profile_reference_function(include_document_processing=False)

    op.drop_constraint(
        "pk_rag_asset_handoff_failures_processing_indexing",
        "rag_asset_handoff_failures",
        type_="primary",
    )
    op.create_primary_key(
        "rag_asset_handoff_failures_pkey",
        "rag_asset_handoff_failures",
        ["asset_version_id", "indexing_profile_id"],
    )
    op.drop_constraint(
        "uq_rag_ingestion_jobs_processing_indexing",
        "rag_ingestion_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_rag_ingestion_jobs_asset_indexing",
        "rag_ingestion_jobs",
        ["asset_version_id", "indexing_profile_id"],
    )
    op.drop_constraint(
        "uq_rag_document_projections_processing_indexing",
        "rag_document_projections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_rag_document_projections_asset_indexing",
        "rag_document_projections",
        ["asset_version_id", "indexing_profile_id"],
    )

    for table_name in reversed(_TABLES_WITH_PROCESSING_ID):
        op.drop_constraint(
            f"fk_{table_name}_document_processing_profile_id",
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "document_processing_profile_id")

    connection.execute(
        sa.text("DELETE FROM rag_profiles WHERE id = :profile_id"),
        {"profile_id": LEGACY_DOCUMENT_PROCESSING_PROFILE_ID},
    )
