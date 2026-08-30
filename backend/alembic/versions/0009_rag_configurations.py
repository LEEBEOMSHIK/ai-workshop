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
        sa.UniqueConstraint("configuration_id", "id", "version"),
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
        sa.CheckConstraint(
            "evaluation_state <> 'passed'",
            name="ck_rag_config_versions_no_passed_pre_eval",
        ),
        sa.CheckConstraint(
            "NOT is_default",
            name="ck_rag_config_versions_no_default_pre_eval",
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"], ["rag_configurations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id", "answer_policy_version_id", "version"],
            [
                "rag_answer_policy_versions.configuration_id",
                "rag_answer_policy_versions.id",
                "rag_answer_policy_versions.version",
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
    op.create_table(
        "rag_ingestion_dispatches",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(700), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'sent')",
            name="ck_rag_ing_dispatch_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_rag_ing_dispatch_attempt",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'claimed' AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL AND sent_at IS NULL) OR "
            "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL)",
            name="ck_rag_ing_dispatch_state",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["rag_ingestion_jobs.job_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_rag_ing_dispatch_ready",
        "rag_ingestion_dispatches",
        ["status", "available_at"],
    )
    op.execute(
        """
        INSERT INTO rag_ingestion_dispatches (job_id, status, available_at)
        SELECT job_id, 'pending', now() FROM rag_ingestion_jobs
        ON CONFLICT (job_id) DO NOTHING
        """
    )

    _install_immutability_triggers()
    indexing_profile_id, retrieval_profile_id = _ensure_technical_profiles()
    _seed_baseline(indexing_profile_id, retrieval_profile_id)


def _ensure_technical_profiles() -> tuple[UUID, UUID]:
    connection = op.get_bind()
    model_rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config
            FROM rag_model_definitions
            WHERE id = :id OR (
                kind = 'embedding'
                AND name = 'multilingual-e5-base'
                AND version = 1
            )
            """
        ),
        {"id": E5_MODEL_ID},
    ).fetchall()
    if not model_rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO rag_model_definitions (kind, name, version, config, id)
                VALUES ('embedding', 'multilingual-e5-base', 1, CAST(:config AS json), :id)
                """
            ),
            {"config": json.dumps(E5_MODEL_CONFIG), "id": E5_MODEL_ID},
        )
        model_rows = [
            (
                E5_MODEL_ID,
                "embedding",
                "multilingual-e5-base",
                1,
                E5_MODEL_CONFIG,
            )
        ]
    if len(model_rows) != 1 or (
        UUID(str(model_rows[0][0])),
        *model_rows[0][1:4],
        model_rows[0][4],
    ) != (
        E5_MODEL_ID,
        "embedding",
        "multilingual-e5-base",
        1,
        E5_MODEL_CONFIG,
    ):
        raise RuntimeError(
            "The approved E5 Model Definition has a conflicting deterministic ID "
            "or technical shape."
        )
    model_id = E5_MODEL_ID

    indexing_rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :id OR (
                kind = 'indexing'
                AND name = 'e5-structure-aware'
                AND version = 2
            )
            """
        ),
        {"id": E5_INDEXING_PROFILE_ID},
    ).fetchall()
    if not indexing_rows:
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
        indexing_rows = [
            (
                E5_INDEXING_PROFILE_ID,
                "indexing",
                "e5-structure-aware",
                2,
                E5_INDEXING_CONFIG,
                "draft",
                False,
            )
        ]
    if len(indexing_rows) != 1 or (
        UUID(str(indexing_rows[0][0])),
        *indexing_rows[0][1:4],
        indexing_rows[0][4],
        indexing_rows[0][5],
        indexing_rows[0][6],
    ) != (
        E5_INDEXING_PROFILE_ID,
        "indexing",
        "e5-structure-aware",
        2,
        E5_INDEXING_CONFIG,
        "draft",
        False,
    ):
        raise RuntimeError(
            "The approved E5 Indexing Profile has a conflicting deterministic ID "
            "or technical shape."
        )
    indexing_profile_id = E5_INDEXING_PROFILE_ID
    binding = connection.execute(
        sa.text(
            """
            SELECT id, role, model_id
            FROM rag_profile_model_bindings
            WHERE profile_id = :profile_id
            ORDER BY id
            """
        ),
        {"profile_id": indexing_profile_id},
    ).fetchall()
    if len(binding) != 1 or (
        UUID(str(binding[0][0])),
        binding[0][1],
        UUID(str(binding[0][2])),
    ) != (
        E5_PROFILE_BINDING_ID,
        "embedding",
        E5_MODEL_ID,
    ):
        raise RuntimeError(
            "The existing E5 Indexing Profile bindings conflict with the approved shape."
        )

    retrieval_rows = connection.execute(
        sa.text(
            """
            SELECT id, kind, name, version, config, evaluation_state, is_default
            FROM rag_profiles
            WHERE id = :id OR (
                kind = 'retrieval'
                AND name = 'bm25-baseline'
                AND version = 1
            )
            """
        ),
        {"id": BM25_RETRIEVAL_PROFILE_ID},
    ).fetchall()
    if not retrieval_rows:
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
        retrieval_rows = [
            (
                BM25_RETRIEVAL_PROFILE_ID,
                "retrieval",
                "bm25-baseline",
                1,
                BM25_RETRIEVAL_CONFIG,
                "draft",
                False,
            )
        ]
    if len(retrieval_rows) != 1 or (
        UUID(str(retrieval_rows[0][0])),
        *retrieval_rows[0][1:4],
        retrieval_rows[0][4],
        retrieval_rows[0][5],
        retrieval_rows[0][6],
    ) != (
        BM25_RETRIEVAL_PROFILE_ID,
        "retrieval",
        "bm25-baseline",
        1,
        BM25_RETRIEVAL_CONFIG,
        "draft",
        False,
    ):
        raise RuntimeError(
            "The approved BM25 Retrieval Profile has a conflicting deterministic ID "
            "or technical shape."
        )
    retrieval_profile_id = BM25_RETRIEVAL_PROFILE_ID
    retrieval_bindings = connection.scalar(
        sa.text(
            """
            SELECT count(*) FROM rag_profile_model_bindings
            WHERE profile_id = :profile_id
            """
        ),
        {"profile_id": retrieval_profile_id},
    )
    if retrieval_bindings != 0:
        raise RuntimeError(
            "The existing BM25 Retrieval Profile bindings conflict with the approved "
            "BM25-only shape."
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
        CREATE FUNCTION rag_validate_configuration_version_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            retrieval_config jsonb;
        BEGIN
            SELECT config::jsonb INTO retrieval_config
            FROM rag_profiles
            WHERE id = NEW.retrieval_profile_id AND kind = 'retrieval';
            IF retrieval_config IS NULL THEN
                RAISE EXCEPTION 'configuration retrieval profile is invalid';
            END IF;
            IF retrieval_config ? 'reranker'
               AND retrieval_config -> 'reranker' <> '{"enabled": false}'::jsonb THEN
                RAISE EXCEPTION 'extractive V1 reranker is not supported';
            END IF;
            IF EXISTS (
                SELECT 1 FROM jsonb_object_keys(retrieval_config) AS key
                WHERE key LIKE 'reranker%' AND key <> 'reranker'
            ) THEN
                RAISE EXCEPTION 'extractive V1 reranker selection is not supported';
            END IF;
            IF EXISTS (
                SELECT 1 FROM rag_profile_model_bindings
                WHERE profile_id = NEW.retrieval_profile_id
                  AND role = 'reranker'
            ) THEN
                RAISE EXCEPTION 'extractive V1 reranker binding is not supported';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_validate_v1
        BEFORE INSERT OR UPDATE ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_validate_configuration_version_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_profile_is_referenced(candidate_profile_id uuid)
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM rag_configuration_versions
                WHERE indexing_profile_id = candidate_profile_id
                   OR retrieval_profile_id = candidate_profile_id
                   OR generation_profile_id = candidate_profile_id
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_protect_referenced_profile()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF rag_profile_is_referenced(OLD.id) THEN
                RAISE EXCEPTION 'referenced profile version is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_profiles_protect_referenced
        BEFORE UPDATE OR DELETE ON rag_profiles
        FOR EACH ROW EXECUTE FUNCTION rag_protect_referenced_profile()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_protect_referenced_profile_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF rag_profile_is_referenced(NEW.profile_id) THEN
                    RAISE EXCEPTION 'referenced binding set is immutable';
                END IF;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                IF rag_profile_is_referenced(OLD.profile_id) THEN
                    RAISE EXCEPTION 'referenced binding set is immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF rag_profile_is_referenced(OLD.profile_id)
               OR rag_profile_is_referenced(NEW.profile_id) THEN
                RAISE EXCEPTION 'referenced binding set is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_profile_bindings_protect_referenced
        BEFORE INSERT OR UPDATE OR DELETE ON rag_profile_model_bindings
        FOR EACH ROW EXECUTE FUNCTION rag_protect_referenced_profile_binding()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_model_is_referenced(candidate_model_id uuid)
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1
                FROM rag_profile_model_bindings AS binding
                WHERE binding.model_id = candidate_model_id
                  AND rag_profile_is_referenced(binding.profile_id)
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_protect_referenced_model()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF rag_model_is_referenced(OLD.id) THEN
                RAISE EXCEPTION 'referenced model definition version is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_models_protect_referenced
        BEFORE UPDATE OR DELETE ON rag_model_definitions
        FOR EACH ROW EXECUTE FUNCTION rag_protect_referenced_model()
        """
    )
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
    op.execute(
        "DROP TRIGGER trg_rag_models_protect_referenced ON rag_model_definitions"
    )
    op.execute(
        "DROP TRIGGER trg_rag_profile_bindings_protect_referenced "
        "ON rag_profile_model_bindings"
    )
    op.execute("DROP TRIGGER trg_rag_profiles_protect_referenced ON rag_profiles")
    op.execute("DROP FUNCTION rag_protect_referenced_model()")
    op.execute("DROP FUNCTION rag_model_is_referenced(uuid)")
    op.execute("DROP FUNCTION rag_protect_referenced_profile_binding()")
    op.execute("DROP FUNCTION rag_protect_referenced_profile()")
    op.execute("DROP FUNCTION rag_profile_is_referenced(uuid)")
    op.drop_table("rag_ingestion_dispatches")
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
    op.execute("DROP FUNCTION rag_validate_configuration_version_v1()")
