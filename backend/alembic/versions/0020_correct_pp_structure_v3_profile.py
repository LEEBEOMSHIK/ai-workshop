"""Publish a corrected immutable PP-StructureV3 profile version."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0020_pp_structure_profile"
down_revision: str | Sequence[str] | None = "0019_pp_structure_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_V1_ID = UUID("00000000-0000-0000-0000-000000000208")
PROFILE_V2_ID = UUID("00000000-0000-0000-0000-000000000209")
MODEL_BINDINGS = (
    (UUID("00000000-0000-0000-0000-000000000301"), "ocr_layout_detection"),
    (UUID("00000000-0000-0000-0000-000000000302"), "ocr_text_detection"),
    (UUID("00000000-0000-0000-0000-000000000303"), "ocr_text_recognition"),
    (UUID("00000000-0000-0000-0000-000000000310"), "ocr_textline_orientation"),
    (UUID("00000000-0000-0000-0000-000000000304"), "ocr_table_classification"),
    (UUID("00000000-0000-0000-0000-000000000305"), "ocr_table_structure_wired"),
    (UUID("00000000-0000-0000-0000-000000000306"), "ocr_table_structure"),
    (UUID("00000000-0000-0000-0000-000000000307"), "ocr_table_cells_wired"),
    (UUID("00000000-0000-0000-0000-000000000308"), "ocr_table_cells_wireless"),
    (UUID("00000000-0000-0000-0000-000000000309"), "ocr_table_orientation"),
)

PROFILE_CONFIG = {
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
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
                "name": "docx-structure",
                "version": "1",
            },
        },
    },
    "ocr": {
        "enabled": True,
        "pipeline_name": "PP-StructureV3",
        "pipeline_version": "3.7.0",
        "languages": ["ko", "en"],
        "confidence_threshold": 0.7,
        "output_schema_version": 1,
        "data_policy": "local_only",
        "artifact_manifest": "rag/ocr/pp-structure-v3-v1.json",
        "enabled_modules": [
            "layout_detection",
            "general_ocr",
            "table_recognition",
            "table_ocr_textline_orientation",
        ],
        "disabled_modules": [
            "document_orientation",
            "document_unwarping",
            "general_ocr_textline_orientation",
            "formula_recognition",
            "seal_recognition",
            "chart_recognition",
            "region_detection",
        ],
    },
}


def _mark_v1_failed() -> None:
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE rag_profiles SET evaluation_state = 'failed'
            WHERE id = :profile_id
              AND kind = 'document_processing'
              AND name = 'pp-structure-v3-docx'
              AND version = 1
              AND evaluation_state = 'draft'
              AND is_default = false
            """
        ),
        {"profile_id": PROFILE_V1_ID},
    )
    if result.rowcount != 1:
        raise RuntimeError("PP-StructureV3 v1 profile identity conflicts.")


def _seed_profile() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config::jsonb, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :profile_id
               OR (kind = 'document_processing'
                   AND name = 'pp-structure-v3-docx' AND version = 2)
            """
        ),
        {"profile_id": PROFILE_V2_ID},
    ).mappings().all()
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != PROFILE_V2_ID
            or row["kind"] != "document_processing"
            or row["name"] != "pp-structure-v3-docx"
            or row["version"] != 2
            or row["config"] != PROFILE_CONFIG
            or row["evaluation_state"] != "draft"
            or row["is_default"] is not False
        ):
            raise RuntimeError("PP-StructureV3 v2 profile identity conflicts.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                id, kind, name, version, config, evaluation_state, is_default
            ) VALUES (
                :profile_id, 'document_processing', 'pp-structure-v3-docx', 2,
                CAST(:config AS json), 'draft', false
            )
            """
        ),
        {"profile_id": PROFILE_V2_ID, "config": json.dumps(PROFILE_CONFIG)},
    )


def _seed_binding(index: int, model_id: UUID, role: str) -> None:
    connection = op.get_bind()
    binding_id = UUID(f"00000000-0000-0000-0000-{340 + index:012d}")
    rows = connection.execute(
        sa.text(
            """
            SELECT id, profile_id, role, model_id
            FROM rag_profile_model_bindings
            WHERE id = :binding_id OR (profile_id = :profile_id AND role = :role)
            """
        ),
        {"binding_id": binding_id, "profile_id": PROFILE_V2_ID, "role": role},
    ).mappings().all()
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != binding_id
            or row["profile_id"] != PROFILE_V2_ID
            or row["role"] != role
            or row["model_id"] != model_id
        ):
            raise RuntimeError(f"PP-StructureV3 v2 binding conflicts: {role}.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profile_model_bindings (id, profile_id, role, model_id)
            VALUES (:binding_id, :profile_id, :role, :model_id)
            """
        ),
        {
            "binding_id": binding_id,
            "profile_id": PROFILE_V2_ID,
            "role": role,
            "model_id": model_id,
        },
    )


def upgrade() -> None:
    _mark_v1_failed()
    _seed_profile()
    for index, (model_id, role) in enumerate(MODEL_BINDINGS):
        _seed_binding(index, model_id, role)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT rag_profile_is_referenced(:profile_id)"),
        {"profile_id": PROFILE_V2_ID},
    ):
        raise RuntimeError(
            "Cannot downgrade while the corrected PP-StructureV3 profile is referenced."
        )
    connection.execute(
        sa.text("DELETE FROM rag_profiles WHERE id = :profile_id"),
        {"profile_id": PROFILE_V2_ID},
    )
    result = connection.execute(
        sa.text(
            """
            UPDATE rag_profiles SET evaluation_state = 'draft'
            WHERE id = :profile_id AND evaluation_state = 'failed'
            """
        ),
        {"profile_id": PROFILE_V1_ID},
    )
    if result.rowcount != 1:
        raise RuntimeError("PP-StructureV3 v1 profile downgrade conflicts.")
