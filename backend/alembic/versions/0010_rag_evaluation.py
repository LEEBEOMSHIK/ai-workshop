"""Add immutable comparable RAG evaluation and evidence-backed promotion."""

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0010_rag_evaluation"
down_revision: str | Sequence[str] | None = "0009_rag_configurations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BGE_MODEL_ID = UUID("00000000-0000-0000-0000-000000000102")
BGE_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000204")
BGE_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000205")
BGE_PROFILE_BINDING_ID = UUID("00000000-0000-0000-0000-000000000206")
BGE_MODEL_CONFIG = {
    "repo_id": "BAAI/bge-m3",
    "revision": "5617a9f61b028005a4858fdac845db406aefb181",
    "dimension": 1024,
    "max_tokens": 8192,
    "query_prefix": "",
    "document_prefix": "",
    "normalize": True,
    "device": "cpu",
    "dtype": "float32",
    "output_mode": "dense",
    "sparse_enabled": False,
    "colbert_enabled": False,
    "data_policy": "local_only",
}
BGE_INDEXING_CONFIG = {
    "chunker": {
        "name": "structure-aware",
        "version": 1,
        "target_tokens": 380,
        "overlap_tokens": 60,
    },
    "embedding": {"batch_size": 8, "similarity": "cosine"},
}
BGE_RETRIEVAL_CONFIG = {
    "bm25": {"analyzer": "standard", "top_k": 30},
    "dense": {"top_k": 30},
    "rrf": {"k": 60},
    "indexing_profile_id": str(BGE_INDEXING_PROFILE_ID),
    "reranker": {"enabled": False},
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


def _seed_bge_technical_profiles() -> None:
    model_config = json.dumps(BGE_MODEL_CONFIG, sort_keys=True)
    indexing_config = json.dumps(BGE_INDEXING_CONFIG, sort_keys=True)
    retrieval_config = json.dumps(BGE_RETRIEVAL_CONFIG, sort_keys=True)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM rag_model_definitions
                WHERE (id = '{BGE_MODEL_ID}'::uuid
                       OR (kind = 'embedding' AND name = 'bge-m3' AND version = 1))
                  AND NOT (
                      id = '{BGE_MODEL_ID}'::uuid AND kind = 'embedding'
                      AND name = 'bge-m3' AND version = 1
                      AND config::jsonb = '{model_config}'::jsonb
                  )
            ) THEN
                RAISE EXCEPTION 'conflicting immutable BGE-M3 model definition';
            END IF;
            INSERT INTO rag_model_definitions (kind, name, version, config, id)
            SELECT 'embedding', 'bge-m3', 1, '{model_config}'::json,
                   '{BGE_MODEL_ID}'::uuid
            WHERE NOT EXISTS (
                SELECT 1 FROM rag_model_definitions WHERE id = '{BGE_MODEL_ID}'::uuid
            );

            IF EXISTS (
                SELECT 1 FROM rag_profiles
                WHERE (id = '{BGE_INDEXING_PROFILE_ID}'::uuid
                       OR (kind = 'indexing' AND name = 'bge-m3-structure-aware'
                           AND version = 1))
                  AND NOT (
                      id = '{BGE_INDEXING_PROFILE_ID}'::uuid AND kind = 'indexing'
                      AND name = 'bge-m3-structure-aware' AND version = 1
                      AND config::jsonb = '{indexing_config}'::jsonb
                      AND evaluation_state = 'draft' AND NOT is_default
                  )
            ) THEN
                RAISE EXCEPTION 'conflicting immutable BGE-M3 indexing profile';
            END IF;
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            )
            SELECT 'indexing', 'bge-m3-structure-aware', 1,
                   '{indexing_config}'::json, 'draft', false,
                   '{BGE_INDEXING_PROFILE_ID}'::uuid
            WHERE NOT EXISTS (
                SELECT 1 FROM rag_profiles
                WHERE id = '{BGE_INDEXING_PROFILE_ID}'::uuid
            );

            IF EXISTS (
                SELECT 1 FROM rag_profiles
                WHERE (id = '{BGE_RETRIEVAL_PROFILE_ID}'::uuid
                       OR (kind = 'retrieval' AND name = 'hybrid-bge-m3-rrf'
                           AND version = 1))
                  AND NOT (
                      id = '{BGE_RETRIEVAL_PROFILE_ID}'::uuid AND kind = 'retrieval'
                      AND name = 'hybrid-bge-m3-rrf' AND version = 1
                      AND config::jsonb = '{retrieval_config}'::jsonb
                      AND evaluation_state = 'draft' AND NOT is_default
                  )
            ) THEN
                RAISE EXCEPTION 'conflicting immutable BGE-M3 retrieval profile';
            END IF;
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            )
            SELECT 'retrieval', 'hybrid-bge-m3-rrf', 1,
                   '{retrieval_config}'::json, 'draft', false,
                   '{BGE_RETRIEVAL_PROFILE_ID}'::uuid
            WHERE NOT EXISTS (
                SELECT 1 FROM rag_profiles
                WHERE id = '{BGE_RETRIEVAL_PROFILE_ID}'::uuid
            );

            IF EXISTS (
                SELECT 1 FROM rag_profile_model_bindings
                WHERE (id = '{BGE_PROFILE_BINDING_ID}'::uuid
                       OR profile_id = '{BGE_INDEXING_PROFILE_ID}'::uuid)
                  AND NOT (
                      id = '{BGE_PROFILE_BINDING_ID}'::uuid
                      AND profile_id = '{BGE_INDEXING_PROFILE_ID}'::uuid
                      AND role = 'embedding' AND model_id = '{BGE_MODEL_ID}'::uuid
                  )
            ) THEN
                RAISE EXCEPTION 'conflicting immutable BGE-M3 profile binding';
            END IF;
            INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
            SELECT '{BGE_INDEXING_PROFILE_ID}'::uuid, 'embedding',
                   '{BGE_MODEL_ID}'::uuid, '{BGE_PROFILE_BINDING_ID}'::uuid
            WHERE NOT EXISTS (
                SELECT 1 FROM rag_profile_model_bindings
                WHERE id = '{BGE_PROFILE_BINDING_ID}'::uuid
            );
            IF EXISTS (
                SELECT 1 FROM rag_profile_model_bindings
                WHERE profile_id = '{BGE_RETRIEVAL_PROFILE_ID}'::uuid
            ) THEN
                RAISE EXCEPTION
                    'BGE-M3 dense retrieval cannot bind auxiliary output models';
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _seed_bge_technical_profiles()
    op.create_table(
        "rag_evaluation_datasets",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fixture_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("fixture_sha256", sa.String(64), nullable=False),
        sa.Column("document_snapshot", sa.JSON(), nullable=False),
        sa.Column("document_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("query_set_sha256", sa.String(64), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("version > 0", name="ck_rag_eval_datasets_version"),
        sa.CheckConstraint("case_count > 0", name="ck_rag_eval_datasets_cases"),
        sa.CheckConstraint(
            "length(fixture_sha256) = 64 AND "
            "length(document_snapshot_sha256) = 64 AND "
            "length(query_set_sha256) = 64",
            name="ck_rag_eval_datasets_hashes",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", "version"),
        sa.UniqueConstraint("owner_id", "fixture_sha256"),
    )
    op.create_table(
        "rag_evaluation_policies",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("min_recall_at_k", sa.Float(), nullable=False),
        sa.Column("min_mrr", sa.Float(), nullable=False),
        sa.Column("min_ndcg", sa.Float(), nullable=False),
        sa.Column("min_supported_precision", sa.Float(), nullable=False),
        sa.Column("max_false_grounding_rate", sa.Float(), nullable=False),
        sa.Column("min_highlight_iou", sa.Float(), nullable=False),
        sa.Column("max_p50_latency_ms", sa.Float(), nullable=False),
        sa.Column("max_p95_latency_ms", sa.Float(), nullable=False),
        sa.Column("max_access_leaks", sa.Integer(), nullable=False),
        sa.Column("required_reproducibility", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("version > 0", name="ck_rag_eval_policies_version"),
        sa.CheckConstraint(
            "min_recall_at_k BETWEEN 0 AND 1 AND min_mrr BETWEEN 0 AND 1 AND "
            "min_ndcg BETWEEN 0 AND 1 AND min_supported_precision BETWEEN 0 AND 1 "
            "AND max_false_grounding_rate BETWEEN 0 AND 1 "
            "AND min_highlight_iou BETWEEN 0 AND 1",
            name="ck_rag_eval_policies_ratios",
        ),
        sa.CheckConstraint(
            "max_p50_latency_ms >= 0 AND max_p95_latency_ms >= max_p50_latency_ms "
            "AND max_p50_latency_ms <> 'Infinity'::float8 "
            "AND max_p95_latency_ms <> 'Infinity'::float8",
            name="ck_rag_eval_policies_latency",
        ),
        sa.CheckConstraint(
            "max_access_leaks = 0", name="ck_rag_eval_policies_zero_leaks"
        ),
        sa.CheckConstraint(
            "required_reproducibility = 1.0",
            name="ck_rag_eval_policies_reproducibility",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id"], ["rag_evaluation_datasets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "dataset_snapshot_id", "version"),
    )
    op.create_table(
        "rag_evaluation_runs",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_policy_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("fixture_sha256", sa.String(64), nullable=False),
        sa.Column("document_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("query_set_sha256", sa.String(64), nullable=False),
        sa.Column("runtime_environment", sa.JSON(), nullable=False),
        sa.Column("repetition_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.String(700), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_rag_eval_runs_status",
        ),
        sa.CheckConstraint("repetition_count >= 2", name="ck_rag_eval_runs_repetitions"),
        sa.CheckConstraint("candidate_count > 0", name="ck_rag_eval_runs_candidates"),
        sa.CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND finished_at IS NULL) OR "
            "(status = 'running' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND claim_token IS NULL "
            "AND claimed_at IS NULL AND finished_at IS NOT NULL)",
            name="ck_rag_eval_runs_claim_state",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id"], ["rag_evaluation_datasets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_policy_version_id"],
            ["rag_evaluation_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_eval_runs_claim", "rag_evaluation_runs", ["status", "claimed_at"]
    )
    op.create_table(
        "rag_evaluation_run_configurations",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("indexing_profile_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_profile_id", sa.Uuid(), nullable=False),
        sa.Column("answer_policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("generation_profile_id", sa.Uuid(), nullable=True),
        sa.Column("component_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("failure", sa.String(700), nullable=True),
        sa.Column("recall_at_k", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("ndcg", sa.Float(), nullable=True),
        sa.Column("supported_precision", sa.Float(), nullable=True),
        sa.Column("false_grounding_rate", sa.Float(), nullable=True),
        sa.Column("highlight_iou", sa.Float(), nullable=True),
        sa.Column("p50_latency_ms", sa.Float(), nullable=True),
        sa.Column("p95_latency_ms", sa.Float(), nullable=True),
        sa.Column("access_leaks", sa.Integer(), nullable=True),
        sa.Column("reproducibility", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_rag_eval_candidates_ordinal"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_rag_eval_candidates_status",
        ),
        sa.CheckConstraint(
            "access_leaks IS NULL OR access_leaks >= 0",
            name="ck_rag_eval_candidates_leaks",
        ),
        sa.CheckConstraint(
            "(recall_at_k IS NULL OR recall_at_k BETWEEN 0 AND 1) AND "
            "(mrr IS NULL OR mrr BETWEEN 0 AND 1) AND "
            "(ndcg IS NULL OR ndcg BETWEEN 0 AND 1) AND "
            "(supported_precision IS NULL OR supported_precision BETWEEN 0 AND 1) AND "
            "(false_grounding_rate IS NULL OR false_grounding_rate BETWEEN 0 AND 1) AND "
            "(highlight_iou IS NULL OR highlight_iou BETWEEN 0 AND 1) AND "
            "(reproducibility IS NULL OR reproducibility BETWEEN 0 AND 1)",
            name="ck_rag_eval_candidates_ratios",
        ),
        sa.CheckConstraint(
            "(p50_latency_ms IS NULL OR "
            "(p50_latency_ms >= 0 AND p50_latency_ms <> 'Infinity'::float8)) AND "
            "(p95_latency_ms IS NULL OR "
            "(p95_latency_ms >= 0 AND p95_latency_ms <> 'Infinity'::float8)) AND "
            "(p50_latency_ms IS NULL OR p95_latency_ms IS NULL OR "
            "p95_latency_ms >= p50_latency_ms)",
            name="ck_rag_eval_candidates_latency",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'running') AND completed_at IS NULL) OR "
            "(status = 'failed' AND failure IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status = 'completed' AND failure IS NULL AND completed_at IS NOT NULL AND "
            "recall_at_k IS NOT NULL AND mrr IS NOT NULL AND ndcg IS NOT NULL AND "
            "supported_precision IS NOT NULL AND false_grounding_rate IS NOT NULL AND "
            "highlight_iou IS NOT NULL AND p50_latency_ms IS NOT NULL AND "
            "p95_latency_ms IS NOT NULL AND access_leaks IS NOT NULL AND "
            "reproducibility IS NOT NULL)",
            name="ck_rag_eval_candidates_completion",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["rag_evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["rag_configuration_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["indexing_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["answer_policy_version_id"],
            ["rag_answer_policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
        sa.UniqueConstraint("run_id", "configuration_version_id"),
    )
    op.create_table(
        "rag_evaluation_case_results",
        sa.Column("run_configuration_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_case_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("permission_scenario", sa.JSON(), nullable=False),
        sa.Column("expected_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("raw_observations", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=True),
        sa.Column("reciprocal_rank", sa.Float(), nullable=True),
        sa.Column("ndcg", sa.Float(), nullable=True),
        sa.Column("correct_supported", sa.Boolean(), nullable=True),
        sa.Column("false_grounding", sa.Boolean(), nullable=True),
        sa.Column("highlight_iou", sa.Float(), nullable=True),
        sa.Column("access_leaks", sa.Integer(), nullable=False),
        sa.Column("reproducible", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_rag_eval_cases_ordinal"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_rag_eval_cases_duration"),
        sa.CheckConstraint("access_leaks >= 0", name="ck_rag_eval_cases_leaks"),
        sa.ForeignKeyConstraint(
            ["run_configuration_id"],
            ["rag_evaluation_run_configurations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_configuration_id", "evaluation_case_id"),
        sa.UniqueConstraint("run_configuration_id", "ordinal"),
    )
    op.create_table(
        "rag_evaluation_dispatches",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(700), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'sent')",
            name="ck_rag_eval_dispatch_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_rag_eval_dispatch_attempt"),
        sa.CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL)",
            name="ck_rag_eval_dispatch_state",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["rag_evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_rag_eval_dispatch_ready",
        "rag_evaluation_dispatches",
        ["status", "available_at"],
    )

    op.drop_constraint(
        "ck_rag_config_versions_no_passed_pre_eval",
        "rag_configuration_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_rag_config_versions_no_default_pre_eval",
        "rag_configuration_versions",
        type_="check",
    )
    op.execute(
        """
        CREATE FUNCTION rag_evaluation_reject_immutable_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'immutable RAG evaluation row';
        END;
        $$
        """
    )
    for table in (
        "rag_evaluation_datasets",
        "rag_evaluation_policies",
        "rag_evaluation_case_results",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION rag_evaluation_reject_immutable_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION rag_protect_evaluation_run_inputs()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.owner_id <> OLD.owner_id
               OR NEW.dataset_snapshot_id <> OLD.dataset_snapshot_id
               OR NEW.evaluation_policy_version_id IS DISTINCT FROM OLD.evaluation_policy_version_id
               OR NEW.fixture_sha256 <> OLD.fixture_sha256
               OR NEW.document_snapshot_sha256 <> OLD.document_snapshot_sha256
               OR NEW.query_set_sha256 <> OLD.query_set_sha256
               OR NEW.runtime_environment::jsonb <> OLD.runtime_environment::jsonb
               OR NEW.repetition_count <> OLD.repetition_count
               OR NEW.candidate_count <> OLD.candidate_count THEN
                RAISE EXCEPTION 'immutable RAG evaluation run inputs';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_evaluation_runs_immutable_inputs
        BEFORE UPDATE ON rag_evaluation_runs
        FOR EACH ROW EXECUTE FUNCTION rag_protect_evaluation_run_inputs()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_evaluation_runs_no_delete
        BEFORE DELETE ON rag_evaluation_runs
        FOR EACH ROW EXECUTE FUNCTION rag_evaluation_reject_immutable_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_protect_evaluation_candidate_inputs()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.run_id <> OLD.run_id
               OR NEW.configuration_version_id <> OLD.configuration_version_id
               OR NEW.ordinal <> OLD.ordinal
               OR NEW.indexing_profile_id <> OLD.indexing_profile_id
               OR NEW.retrieval_profile_id <> OLD.retrieval_profile_id
               OR NEW.answer_policy_version_id <> OLD.answer_policy_version_id
               OR NEW.generation_profile_id IS DISTINCT FROM OLD.generation_profile_id
               OR NEW.component_snapshot::jsonb <> OLD.component_snapshot::jsonb THEN
                RAISE EXCEPTION 'immutable RAG evaluation candidate inputs';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_eval_candidates_immutable_inputs
        BEFORE UPDATE ON rag_evaluation_run_configurations
        FOR EACH ROW EXECUTE FUNCTION rag_protect_evaluation_candidate_inputs()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_eval_candidates_no_delete
        BEFORE DELETE ON rag_evaluation_run_configurations
        FOR EACH ROW EXECUTE FUNCTION rag_evaluation_reject_immutable_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_require_qualifying_evaluation_for_promotion()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.evaluation_state = 'passed' AND NEW.evaluation_state <> 'passed' THEN
                RAISE EXCEPTION 'passed evaluation state is evidence-backed and immutable';
            END IF;
            IF (NEW.evaluation_state = 'passed' AND OLD.evaluation_state <> 'passed')
               OR (NEW.is_default AND NOT OLD.is_default) THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM rag_evaluation_run_configurations AS candidate
                    JOIN rag_evaluation_runs AS run ON run.id = candidate.run_id
                    JOIN rag_evaluation_datasets AS dataset
                      ON dataset.id = run.dataset_snapshot_id
                    JOIN rag_evaluation_policies AS policy
                      ON policy.id = run.evaluation_policy_version_id
                     AND policy.dataset_snapshot_id = run.dataset_snapshot_id
                     AND policy.owner_id = run.owner_id
                    JOIN rag_configurations AS identity
                      ON identity.id = NEW.configuration_id
                    JOIN rag_configuration_versions AS evaluated_version
                      ON evaluated_version.id = candidate.configuration_version_id
                    WHERE candidate.configuration_version_id = NEW.id
                      AND candidate.indexing_profile_id = evaluated_version.indexing_profile_id
                      AND candidate.retrieval_profile_id = evaluated_version.retrieval_profile_id
                      AND candidate.answer_policy_version_id =
                          evaluated_version.answer_policy_version_id
                      AND candidate.generation_profile_id IS NOT DISTINCT FROM
                          evaluated_version.generation_profile_id
                      AND candidate.status = 'completed'
                      AND candidate.failure IS NULL
                      AND run.status = 'completed'
                      AND run.failure IS NULL
                      AND (identity.owner_id IS NULL OR identity.owner_id = run.owner_id)
                      AND run.fixture_sha256 = dataset.fixture_sha256
                      AND run.document_snapshot_sha256 = dataset.document_snapshot_sha256
                      AND run.query_set_sha256 = dataset.query_set_sha256
                      AND (
                          SELECT count(*)
                          FROM rag_evaluation_case_results AS case_result
                          WHERE case_result.run_configuration_id = candidate.id
                      ) = dataset.case_count
                      AND NOT EXISTS (
                          SELECT 1
                          FROM rag_evaluation_case_results AS case_result
                          WHERE case_result.run_configuration_id = candidate.id
                            AND json_array_length(case_result.raw_observations)
                                <> run.repetition_count
                      )
                      AND candidate.recall_at_k IS NOT NULL
                      AND candidate.mrr IS NOT NULL
                      AND candidate.ndcg IS NOT NULL
                      AND candidate.supported_precision IS NOT NULL
                      AND candidate.false_grounding_rate IS NOT NULL
                      AND candidate.highlight_iou IS NOT NULL
                      AND candidate.p50_latency_ms IS NOT NULL
                      AND candidate.p95_latency_ms IS NOT NULL
                      AND candidate.access_leaks IS NOT NULL
                      AND candidate.reproducibility IS NOT NULL
                      AND candidate.recall_at_k <> 'NaN'::float8
                      AND candidate.mrr <> 'NaN'::float8
                      AND candidate.ndcg <> 'NaN'::float8
                      AND candidate.supported_precision <> 'NaN'::float8
                      AND candidate.false_grounding_rate <> 'NaN'::float8
                      AND candidate.highlight_iou <> 'NaN'::float8
                      AND candidate.p50_latency_ms <> 'NaN'::float8
                      AND candidate.p95_latency_ms <> 'NaN'::float8
                      AND candidate.reproducibility <> 'NaN'::float8
                      AND candidate.recall_at_k >= policy.min_recall_at_k
                      AND candidate.mrr >= policy.min_mrr
                      AND candidate.ndcg >= policy.min_ndcg
                      AND candidate.supported_precision >= policy.min_supported_precision
                      AND candidate.false_grounding_rate <= policy.max_false_grounding_rate
                      AND candidate.highlight_iou >= policy.min_highlight_iou
                      AND candidate.p50_latency_ms <= policy.max_p50_latency_ms
                      AND candidate.p95_latency_ms <= policy.max_p95_latency_ms
                      AND candidate.access_leaks <= policy.max_access_leaks
                      AND policy.max_access_leaks = 0
                      AND candidate.reproducibility >= policy.required_reproducibility
                      AND policy.required_reproducibility = 1.0
                ) THEN
                    RAISE EXCEPTION 'a completed qualifying exact evaluation is required';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_configuration_versions_evaluation_gate
        BEFORE UPDATE OF evaluation_state, is_default ON rag_configuration_versions
        FOR EACH ROW EXECUTE FUNCTION rag_require_qualifying_evaluation_for_promotion()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_configuration_versions_evaluation_gate "
        "ON rag_configuration_versions"
    )
    op.execute("DROP FUNCTION rag_require_qualifying_evaluation_for_promotion")
    op.execute(
        "DROP TRIGGER trg_rag_eval_candidates_no_delete "
        "ON rag_evaluation_run_configurations"
    )
    op.execute(
        "DROP TRIGGER trg_rag_eval_candidates_immutable_inputs "
        "ON rag_evaluation_run_configurations"
    )
    op.execute("DROP FUNCTION rag_protect_evaluation_candidate_inputs")
    op.execute("DROP TRIGGER trg_rag_evaluation_runs_no_delete ON rag_evaluation_runs")
    op.execute(
        "DROP TRIGGER trg_rag_evaluation_runs_immutable_inputs ON rag_evaluation_runs"
    )
    op.execute("DROP FUNCTION rag_protect_evaluation_run_inputs")
    for table in (
        "rag_evaluation_case_results",
        "rag_evaluation_policies",
        "rag_evaluation_datasets",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION rag_evaluation_reject_immutable_mutation")
    op.create_check_constraint(
        "ck_rag_config_versions_no_passed_pre_eval",
        "rag_configuration_versions",
        "evaluation_state <> 'passed'",
    )
    op.create_check_constraint(
        "ck_rag_config_versions_no_default_pre_eval",
        "rag_configuration_versions",
        "NOT is_default",
    )
    op.drop_index("ix_rag_eval_dispatch_ready", table_name="rag_evaluation_dispatches")
    op.drop_table("rag_evaluation_dispatches")
    op.drop_table("rag_evaluation_case_results")
    op.drop_table("rag_evaluation_run_configurations")
    op.drop_index("ix_rag_eval_runs_claim", table_name="rag_evaluation_runs")
    op.drop_table("rag_evaluation_runs")
    op.drop_table("rag_evaluation_policies")
    op.drop_table("rag_evaluation_datasets")
