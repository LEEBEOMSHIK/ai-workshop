"""Seed an immutable mixed PDF and DOCX OCR profile without changing v1."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0022_mixed_pdf_ocr_profile"
down_revision: str | Sequence[str] | None = "0021_pdf_ocr_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000211")
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
                "name": "pymupdf-ocr",
                "version": "2",
                "options": {"raster_dpi": 144, "max_page_pixels": 16000000, "max_pages": 200},
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


def _seed_profile() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                """
            SELECT id, kind, name, version, config::jsonb, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :profile_id
               OR (kind = 'document_processing'
                   AND name = 'pp-structure-v3-pdf-docx' AND version = 2)
            """
            ),
            {"profile_id": PROFILE_ID},
        )
        .mappings()
        .all()
    )
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != PROFILE_ID
            or row["kind"] != "document_processing"
            or row["name"] != "pp-structure-v3-pdf-docx"
            or row["version"] != 2
            or row["config"] != PROFILE_CONFIG
            or row["evaluation_state"] != "draft"
            or row["is_default"] is not False
        ):
            raise RuntimeError("PP-StructureV3 mixed PDF profile identity conflicts.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                id, kind, name, version, config, evaluation_state, is_default
            ) VALUES (
                :profile_id, 'document_processing', 'pp-structure-v3-pdf-docx', 2,
                CAST(:config AS json), 'draft', false
            )
            """
        ),
        {"profile_id": PROFILE_ID, "config": json.dumps(PROFILE_CONFIG)},
    )


def _seed_binding(index: int, model_id: UUID, role: str) -> None:
    connection = op.get_bind()
    binding_id = UUID(f"00000000-0000-0000-0000-{360 + index:012d}")
    rows = (
        connection.execute(
            sa.text(
                """
            SELECT id, profile_id, role, model_id
            FROM rag_profile_model_bindings
            WHERE id = :binding_id OR (profile_id = :profile_id AND role = :role)
            """
            ),
            {"binding_id": binding_id, "profile_id": PROFILE_ID, "role": role},
        )
        .mappings()
        .all()
    )
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != binding_id
            or row["profile_id"] != PROFILE_ID
            or row["role"] != role
            or row["model_id"] != model_id
        ):
            raise RuntimeError(f"PP-StructureV3 mixed PDF binding conflicts: {role}.")
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
            "profile_id": PROFILE_ID,
            "role": role,
            "model_id": model_id,
        },
    )


def upgrade() -> None:
    _seed_profile()
    for index, (model_id, role) in enumerate(MODEL_BINDINGS):
        _seed_binding(index, model_id, role)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT rag_profile_is_referenced(:profile_id)"),
        {"profile_id": PROFILE_ID},
    ):
        raise RuntimeError(
            "Cannot downgrade while the mixed PDF PP-StructureV3 profile is referenced."
        )
    connection.execute(
        sa.text("DELETE FROM rag_profiles WHERE id = :profile_id"),
        {"profile_id": PROFILE_ID},
    )

