"""Create immutable Saved RAG Configurations and the pending BM25 baseline."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0009_rag_configurations"
down_revision: str | Sequence[str] | None = "0008_rag_embedding_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

E5_MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")
E5_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
BM25_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000202")
E5_PROFILE_BINDING_ID = UUID("00000000-0000-0000-0000-000000000203")
BASELINE_CONFIGURATION_ID = UUID("00000000-0000-0000-0000-000000000501")
BASELINE_POLICY_ID = UUID("00000000-0000-0000-0000-000000000502")
BASELINE_VERSION_ID = UUID("00000000-0000-0000-0000-000000000503")

E5_MODEL_CONFIG = {
    "repo_id": "intfloat/multilingual-e5-base",
    "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
    "dimension": 768,
    "max_tokens": 512,
    "query_prefix": "query: ",
    "document_prefix": "passage: ",
    "normalize": True,
    "device": "cpu",
    "dtype": "float32",
    "output_mode": "dense",
    "data_policy": "local_only",
}
E5_INDEXING_CONFIG = {
    "chunker": {
        "name": "structure-aware",
        "version": 2,
        "target_tokens": 380,
        "overlap_tokens": 60,
    },
    "embedding": {"batch_size": 32, "similarity": "cosine"},
}
BM25_RETRIEVAL_CONFIG = {
    "bm25": {"analyzer": "standard", "top_k": 30},
    "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
}


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rag_configurations",
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "(is_system AND owner_id IS NULL) OR "
            "(NOT is_system AND owner_id IS NOT NULL)",
            name="ck_rag_configurations_system_owner",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name"),
    )
    op.create_index(
        "uq_rag_configurations_system_name",
        "rag_configurations",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_system"),
    )
    op.create_table(
        "rag_answer_policy_versions",
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("min_semantic_score", sa.Float(), nullable=False),
        sa.Column("min_keyword_coverage", sa.Float(), nullable=False),
        sa.Column("require_complete_provenance", sa.Boolean(), nullable=False),
        sa.Column("conflict_mode", sa.String(32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "version > 0", name="ck_rag_answer_policy_versions_positive"
        ),
        sa.CheckConstraint(
            "mode = 'extractive'", name="ck_rag_answer_policy_versions_mode"
        ),
        sa.CheckConstraint(
            "min_semantic_score >= 0 AND min_semantic_score <= 1",
            name="ck_rag_answer_policy_versions_semantic_score",
        ),
        sa.CheckConstraint(
            "min_keyword_coverage >= 0 AND min_keyword_coverage <= 1",
            name="ck_rag_answer_policy_versions_keyword_coverage",
        ),
        sa.CheckConstraint(
            "require_complete_provenance",
            name="ck_rag_answer_policy_versions_provenance",
        ),
        sa.CheckConstraint(
            "conflict_mode = 'separate_sources'",
            name="ck_rag_answer_policy_versions_conflict_mode",
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"], ["rag_configurations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("configuration_id", "version"),
        sa.UniqueConstraint("configuration_id", "id"),
    )
    op.create_table(
        "rag_configuration_versions",
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("indexing_profile_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_profile_id", sa.Uuid(), nullable=False),
        sa.Column("generation_profile_id", sa.Uuid(), nullable=True),
        sa.Column("answer_policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_state", sa.String(32), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "version > 0", name="ck_rag_configuration_versions_positive"
        ),
        sa.CheckConstraint(
            "generation_profile_id IS NULL",
            name="ck_rag_configuration_versions_no_generation_v1",
        ),
        sa.CheckConstraint(
            "evaluation_state IN ('draft', 'pending', 'passed', 'failed')",
            name="ck_rag_configuration_versions_evaluation_state",
        ),
        sa.CheckConstraint(
            "NOT is_default OR evaluation_state = 'passed'",
            name="ck_rag_configuration_versions_default_passed",
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"], ["rag_configurations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id", "answer_policy_version_id"],
            [
                "rag_answer_policy_versions.configuration_id",
                "rag_answer_policy_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["indexing_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generation_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("configuration_id", "version"),
    )
    op.create_index(
        "uq_rag_configuration_versions_passed_default",
        "rag_configuration_versions",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default AND evaluation_state = 'passed'"),
    )
    op.create_table(
        "rag_configuration_workspace_subscriptions",
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["rag_configuration_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("configuration_version_id", "workspace_id"),
    )

    _install_immutability_triggers()
    indexing_profile_id, retrieval_profile_id = _ensure_technical_profiles()
    _seed_baseline(indexing_profile_id, retrieval_profile_id)


def _ensure_technical_profiles() -> tuple[UUID, UUID]:
    connection = op.get_bind()
    model_id = connection.scalar(
        sa.text(
            """
            SELECT id FROM rag_model_definitions
            WHERE kind = 'embedding' AND name = 'multilingual-e5-base' AND version = 1
            """
        )
    )
    if model_id is None:
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_model_definitions (kind, name, version, config, id)
                VALUES ('embedding', 'multilingual-e5-base', 1, CAST(:config AS json), :id)
                """
            ),
            {"config": json.dumps(E5_MODEL_CONFIG), "id": E5_MODEL_ID},
        )
        model_id = E5_MODEL_ID
    elif UUID(str(model_id)) != E5_MODEL_ID:
        raise RuntimeError(
            "The approved E5 Model Definition has a conflicting deterministic ID."
        )
    stored_model_config = connection.scalar(
        sa.text("SELECT config FROM rag_model_definitions WHERE id = :id"),
        {"id": model_id},
    )
    if stored_model_config != E5_MODEL_CONFIG:
        raise RuntimeError(
            "The existing E5 Model Definition conflicts with the approved revision."
        )

    indexing_profile_id = connection.scalar(
        sa.text(
            """
            SELECT id FROM rag_profiles
            WHERE kind = 'indexing' AND name = 'e5-structure-aware' AND version = 2
            """
        )
    )
    if indexing_profile_id is None:
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_profiles (
                    kind, name, version, config, evaluation_state, is_default, id
                ) VALUES (
                    'indexing', 'e5-structure-aware', 2, CAST(:config AS json),
                    'draft', false, :id
                )
                """
            ),
            {"config": json.dumps(E5_INDEXING_CONFIG), "id": E5_INDEXING_PROFILE_ID},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
                VALUES (:profile_id, 'embedding', :model_id, :id)
                """
            ),
            {
                "profile_id": E5_INDEXING_PROFILE_ID,
                "model_id": model_id,
                "id": E5_PROFILE_BINDING_ID,
            },
        )
        indexing_profile_id = E5_INDEXING_PROFILE_ID
    elif UUID(str(indexing_profile_id)) != E5_INDEXING_PROFILE_ID:
        raise RuntimeError(
            "The approved E5 Indexing Profile has a conflicting deterministic ID."
        )
    stored_indexing_config = connection.scalar(
        sa.text("SELECT config FROM rag_profiles WHERE id = :id"),
        {"id": indexing_profile_id},
    )
    if stored_indexing_config != E5_INDEXING_CONFIG:
        raise RuntimeError(
            "The existing E5 Indexing Profile conflicts with the approved version."
        )
    binding = connection.execute(
        sa.text(
            """
            SELECT binding.model_id, model.kind, model.name, model.version
            FROM rag_profile_model_bindings AS binding
            JOIN rag_model_definitions AS model ON model.id = binding.model_id
            WHERE binding.profile_id = :profile_id AND binding.role = 'embedding'
            """
        ),
        {"profile_id": indexing_profile_id},
    ).fetchall()
    if len(binding) != 1 or binding[0][1:] != (
        "embedding",
        "multilingual-e5-base",
        1,
    ):
        raise RuntimeError(
            "The existing E5 Indexing Profile is not bound to the approved model version."
        )

    retrieval_profile_id = connection.scalar(
        sa.text(
            """
            SELECT id FROM rag_profiles
            WHERE kind = 'retrieval' AND name = 'bm25-baseline' AND version = 1
            """
        )
    )
    if retrieval_profile_id is None:
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_profiles (
                    kind, name, version, config, evaluation_state, is_default, id
                ) VALUES (
                    'retrieval', 'bm25-baseline', 1, CAST(:config AS json),
                    'draft', false, :id
                )
                """
            ),
            {
                "config": json.dumps(BM25_RETRIEVAL_CONFIG),
                "id": BM25_RETRIEVAL_PROFILE_ID,
            },
        )
        retrieval_profile_id = BM25_RETRIEVAL_PROFILE_ID
    elif UUID(str(retrieval_profile_id)) != BM25_RETRIEVAL_PROFILE_ID:
        raise RuntimeError(
            "The approved BM25 Retrieval Profile has a conflicting deterministic ID."
        )
    stored_retrieval_config = connection.scalar(
        sa.text("SELECT config FROM rag_profiles WHERE id = :id"),
        {"id": retrieval_profile_id},
    )
    if not isinstance(stored_retrieval_config, dict) or stored_retrieval_config.get(
        "indexing_profile_id"
    ) != str(indexing_profile_id):
        raise RuntimeError(
            "The existing BM25 Retrieval Profile does not reference the approved "
            "Indexing Profile."
        )
    return UUID(str(indexing_profile_id)), UUID(str(retrieval_profile_id))


def _seed_baseline(indexing_profile_id: UUID, retrieval_profile_id: UUID) -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_configurations (owner_id, name, is_system, id)
            VALUES (NULL, 'BM25 기준선', true, :id)
            """
        ),
        {"id": BASELINE_CONFIGURATION_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_answer_policy_versions (
                configuration_id, version, mode, min_semantic_score,
                min_keyword_coverage, require_complete_provenance,
                conflict_mode, id
            ) VALUES (
                :configuration_id, 1, 'extractive', 0.8, 0.7, true,
                'separate_sources', :id
            )
            """
        ),
        {"configuration_id": BASELINE_CONFIGURATION_ID, "id": BASELINE_POLICY_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_configuration_versions (
                configuration_id, version, indexing_profile_id,
                retrieval_profile_id, generation_profile_id,
                answer_policy_version_id, evaluation_state, is_default, id
            ) VALUES (
                :configuration_id, 1, :indexing_profile_id,
                :retrieval_profile_id, NULL, :policy_id, 'pending', false, :id
            )
            """
        ),
        {
            "configuration_id": BASELINE_CONFIGURATION_ID,
            "indexing_profile_id": indexing_profile_id,
            "retrieval_profile_id": retrieval_profile_id,
            "policy_id": BASELINE_POLICY_ID,
            "id": BASELINE_VERSION_ID,
        },
    )


def _install_immutability_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION rag_reject_immutable_row_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'immutable Saved RAG Configuration row';
        END;
        $$
        """
    )
    for table in (
        "rag_configurations",
        "rag_answer_policy_versions",
        "rag_configuration_workspace_subscriptions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION rag_reject_immutable_row_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION rag_protect_configuration_version_components()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.configuration_id <> OLD.configuration_id
               OR NEW.version <> OLD.version
               OR NEW.indexing_profile_id <> OLD.indexing_profile_id
               OR NEW.retrieval_profile_id <> OLD.retrieval_profile_id
               OR NEW.generation_profile_id IS DISTINCT FROM OLD.generation_profile_id
               OR NEW.answer_policy_version_id <> OLD.answer_policy_version_id THEN
                RAISE EXCEPTION 'immutable Saved RAG Configuration components';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_immutable_components
        BEFORE UPDATE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_protect_configuration_version_components()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_no_delete
        BEFORE DELETE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_reject_immutable_row_mutation()
        """
    )


def downgrade() -> None:
    op.drop_table("rag_configuration_workspace_subscriptions")
    op.drop_index(
        "uq_rag_configuration_versions_passed_default",
        table_name="rag_configuration_versions",
    )
    op.drop_table("rag_configuration_versions")
    op.drop_table("rag_answer_policy_versions")
    op.drop_index(
        "uq_rag_configurations_system_name", table_name="rag_configurations"
    )
    op.drop_table("rag_configurations")
    op.execute("DROP FUNCTION rag_protect_configuration_version_components()")
    op.execute("DROP FUNCTION rag_reject_immutable_row_mutation()")
