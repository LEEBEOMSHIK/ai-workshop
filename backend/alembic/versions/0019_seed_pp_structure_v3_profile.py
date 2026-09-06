"""Seed the complete pinned PP-StructureV3 document-processing profile."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0019_pp_structure_v3"
down_revision: str | Sequence[str] | None = "0018_rag_ocr_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000208")
MODELS = (
    (
        UUID("00000000-0000-0000-0000-000000000301"),
        "ocr_layout_detection",
        "PP-DocLayout_plus-L",
        "layout",
        "PaddlePaddle/PP-DocLayout_plus-L",
        "aa52b8528c84f9b1a34ac3a88fe0e576edb9d11d",
        "24ca3e2e442164505e250deef59f7ee9a54ea12dd32875c9cd6155d959dc97da",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000302"),
        "ocr_text_detection",
        "PP-OCRv5_server_det",
        "detection",
        "PaddlePaddle/PP-OCRv5_server_det",
        "ca867c897ecbca8873081573a802ad70d499cb94",
        "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000303"),
        "ocr_text_recognition",
        "korean_PP-OCRv5_mobile_rec",
        "recognition",
        "PaddlePaddle/korean_PP-OCRv5_mobile_rec",
        "c02ecaf1f22bfd1c618cce154fd19185b47e663a",
        "cac3e5f12cf04aaa77f6a5bc704e4e736ef2908476551891d84b41b4e9090462",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000310"),
        "ocr_textline_orientation",
        "PP-LCNet_x1_0_textline_ori",
        "textline_orientation",
        "PaddlePaddle/PP-LCNet_x1_0_textline_ori",
        "cd237a44b0e359d4fe38310a416203cf7403faa5",
        "0de2bcf996cf553e2b848dd7b1769dafffc6917b1ccdf55c1d8efe7909fbf743",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000304"),
        "ocr_table_classification",
        "PP-LCNet_x1_0_table_cls",
        "table_classification",
        "PaddlePaddle/PP-LCNet_x1_0_table_cls",
        "2fa6323e7dab88fa883081db1460995f46af2922",
        "d0224afd9cfddf22da17407c6c78491baaa1f25922fbb312c9b0d2037c802db0",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000305"),
        "ocr_table_structure_wired",
        "SLANeXt_wired",
        "wired_table_structure",
        "PaddlePaddle/SLANeXt_wired",
        "763069fcda6a065f2171753205a32bf899a88d15",
        "ff0362a30f707fa7d27d8453c4396b992fca287377a42d01515bca6eeb3908f5",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000306"),
        "ocr_table_structure",
        "SLANet_plus",
        "wireless_table_structure",
        "PaddlePaddle/SLANet_plus",
        "bae6e5f8c3c4e7da0c0b7639fdf3228fe76184e2",
        "012986b0e2bfe90410618bfb4b7cf4fcb6c978caefd84c63c2934f8387b09ab8",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000307"),
        "ocr_table_cells_wired",
        "RT-DETR-L_wired_table_cell_det",
        "wired_table_cells",
        "PaddlePaddle/RT-DETR-L_wired_table_cell_det",
        "e2bd53c06b3a815d86acbf5c6779dada58819cfe",
        "357321c2845f0a035e8d118622649685a3cdb89d28b09a64e45a5a3df7a9fedc",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000308"),
        "ocr_table_cells_wireless",
        "RT-DETR-L_wireless_table_cell_det",
        "wireless_table_cells",
        "PaddlePaddle/RT-DETR-L_wireless_table_cell_det",
        "25ca86356a601c877476bb0dcc5fd09153d9d64d",
        "c0f8c9ea07be8916ece73a8acf807bd21aed3ef11969b319c2dccb2406774c34",
    ),
    (
        UUID("00000000-0000-0000-0000-000000000309"),
        "ocr_table_orientation",
        "PP-LCNet_x1_0_doc_ori",
        "table_orientation",
        "PaddlePaddle/PP-LCNet_x1_0_doc_ori",
        "d3b95a6dff5fe8a94f2748e12b61cb26818a0df8",
        "e8d6e7c5d264507e40e58a655779059d616b20d7441ea22047d829eb3931989c",
    ),
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
        ],
        "disabled_modules": [
            "document_orientation",
            "document_unwarping",
            "textline_orientation",
            "formula_recognition",
            "seal_recognition",
            "chart_recognition",
            "region_detection",
        ],
    },
}


def _model_config(
    runtime_role: str,
    source: str,
    model_revision: str,
    artifact_sha256: str,
) -> dict[str, str]:
    return {
        "runtime_role": runtime_role,
        "source": source,
        "revision": model_revision,
        "artifact_sha256": artifact_sha256,
        "license": "Apache-2.0",
        "data_policy": "local_only",
        "artifact_manifest": "rag/ocr/pp-structure-v3-v1.json",
    }


def _seed_model(
    model_id: UUID,
    kind: str,
    name: str,
    runtime_role: str,
    source: str,
    model_revision: str,
    artifact_sha256: str,
) -> None:
    connection = op.get_bind()
    expected = _model_config(runtime_role, source, model_revision, artifact_sha256)
    rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config::jsonb
            FROM rag_model_definitions
            WHERE id = :model_id OR (kind = :kind AND name = :name AND version = 1)
            """
        ),
        {"model_id": model_id, "kind": kind, "name": name},
    ).mappings().all()
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != model_id
            or row["kind"] != kind
            or row["name"] != name
            or row["version"] != 1
            or row["config"] != expected
        ):
            raise RuntimeError(f"PP-StructureV3 model identity conflicts: {kind}.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_model_definitions (id, kind, name, version, config)
            VALUES (:model_id, :kind, :name, 1, CAST(:config AS json))
            """
        ),
        {
            "model_id": model_id,
            "kind": kind,
            "name": name,
            "config": json.dumps(expected),
        },
    )


def _seed_profile() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config::jsonb, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :profile_id
               OR (kind = 'document_processing'
                   AND name = 'pp-structure-v3-docx' AND version = 1)
            """
        ),
        {"profile_id": PROFILE_ID},
    ).mappings().all()
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != PROFILE_ID
            or row["kind"] != "document_processing"
            or row["name"] != "pp-structure-v3-docx"
            or row["version"] != 1
            or row["config"] != PROFILE_CONFIG
            or row["evaluation_state"] != "draft"
            or row["is_default"] is not False
        ):
            raise RuntimeError("PP-StructureV3 document-processing profile conflicts.")
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                id, kind, name, version, config, evaluation_state, is_default
            ) VALUES (
                :profile_id, 'document_processing', 'pp-structure-v3-docx', 1,
                CAST(:config AS json), 'draft', false
            )
            """
        ),
        {"profile_id": PROFILE_ID, "config": json.dumps(PROFILE_CONFIG)},
    )


def _seed_binding(index: int, model_id: UUID, role: str) -> None:
    binding_id = UUID(f"00000000-0000-0000-0000-{320 + index:012d}")
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, profile_id, role, model_id
            FROM rag_profile_model_bindings
            WHERE id = :binding_id OR (profile_id = :profile_id AND role = :role)
            """
        ),
        {
            "binding_id": binding_id,
            "profile_id": PROFILE_ID,
            "role": role,
        },
    ).mappings().all()
    if rows:
        row = rows[0]
        if (
            len(rows) != 1
            or row["id"] != binding_id
            or row["profile_id"] != PROFILE_ID
            or row["role"] != role
            or row["model_id"] != model_id
        ):
            raise RuntimeError(f"PP-StructureV3 model binding conflicts: {role}.")
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
    for model in MODELS:
        _seed_model(*model)
    _seed_profile()
    for index, model in enumerate(MODELS):
        _seed_binding(index, model[0], model[1])


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT rag_profile_is_referenced(:profile_id)"),
        {"profile_id": PROFILE_ID},
    ):
        raise RuntimeError(
            "Cannot downgrade while the PP-StructureV3 profile is referenced."
        )
    connection.execute(
        sa.text("DELETE FROM rag_profiles WHERE id = :profile_id"),
        {"profile_id": PROFILE_ID},
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM rag_model_definitions
            WHERE id = ANY(:model_ids)
              AND NOT EXISTS (
                  SELECT 1 FROM rag_profile_model_bindings
                  WHERE model_id = rag_model_definitions.id
              )
            """
        ),
        {"model_ids": [model[0] for model in MODELS]},
    )
