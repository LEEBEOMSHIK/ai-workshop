"""Add immutable comparable RAG evaluation and evidence-backed promotion."""
# ruff: noqa: E501 -- SQL constraints stay aligned with ORM metadata verbatim.

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
            IF FOUND THEN
                INSERT INTO rag_evaluation_seed_ownership (seed_kind, seed_id)
                VALUES ('model', '{BGE_MODEL_ID}'::uuid);
            END IF;

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
            IF FOUND THEN
                INSERT INTO rag_evaluation_seed_ownership (seed_kind, seed_id)
                VALUES ('profile', '{BGE_INDEXING_PROFILE_ID}'::uuid);
            END IF;

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
            IF FOUND THEN
                INSERT INTO rag_evaluation_seed_ownership (seed_kind, seed_id)
                VALUES ('profile', '{BGE_RETRIEVAL_PROFILE_ID}'::uuid);
            END IF;

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
            IF FOUND THEN
                INSERT INTO rag_evaluation_seed_ownership (seed_kind, seed_id)
                VALUES ('binding', '{BGE_PROFILE_BINDING_ID}'::uuid);
            END IF;
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
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "rag_evaluation_seed_ownership",
        sa.Column("seed_kind", sa.String(32), nullable=False),
        sa.Column("seed_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("seed_kind", "seed_id"),
    )
    _seed_bge_technical_profiles()
    op.create_table(
        "rag_evaluation_datasets",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fixture_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("fixture_sha256", sa.String(64), nullable=False),
        sa.Column("document_snapshot", sa.JSON(), nullable=False),
        sa.Column("document_snapshot_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("document_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("query_set_bytes", sa.LargeBinary(), nullable=False),
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
        "rag_evaluation_dataset_cases",
        sa.Column("dataset_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("canonical_case_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("canonical_case_sha256", sa.String(64), nullable=False),
        sa.Column("query_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("permission_scenario", sa.JSON(), nullable=False),
        sa.Column("expected_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("authorized_source_ids", sa.JSON(), nullable=False),
        sa.Column("forbidden_source_ids", sa.JSON(), nullable=False),
        sa.Column("expected_highlight", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_rag_eval_dataset_cases_ordinal"),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id"], ["rag_evaluation_datasets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dataset_snapshot_id", "id"),
        sa.UniqueConstraint("dataset_snapshot_id", "ordinal"),
    )
    op.create_table(
        "rag_evaluation_policies",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_definition_version", sa.Integer(), nullable=False),
        sa.Column("retrieval_k", sa.Integer(), nullable=False),
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
            "metric_definition_version = 1 AND retrieval_k BETWEEN 1 AND 50",
            name="ck_rag_eval_policies_metric_definition",
        ),
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
        sa.CheckConstraint(
            "min_recall_at_k NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "min_mrr NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "min_ndcg NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "min_supported_precision NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "max_false_grounding_rate NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "min_highlight_iou NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "max_p50_latency_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "max_p95_latency_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "required_reproducibility NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)",
            name="ck_rag_eval_policies_finite",
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
        sa.Column("worker_runtime_environment", sa.JSON(), nullable=True),
        sa.Column("metric_definition_version", sa.Integer(), nullable=False),
        sa.Column("retrieval_k", sa.Integer(), nullable=False),
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
            "metric_definition_version = 1 AND retrieval_k BETWEEN 1 AND 50",
            name="ck_rag_eval_runs_metric_definition",
        ),
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
        sa.CheckConstraint(
            "(recall_at_k IS NULL OR recall_at_k NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(mrr IS NULL OR mrr NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(ndcg IS NULL OR ndcg NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(supported_precision IS NULL OR supported_precision NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(false_grounding_rate IS NULL OR false_grounding_rate NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(highlight_iou IS NULL OR highlight_iou NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(p50_latency_ms IS NULL OR p50_latency_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(p95_latency_ms IS NULL OR p95_latency_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(reproducibility IS NULL OR reproducibility NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8))",
            name="ck_rag_eval_candidates_finite",
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
        sa.Column("dataset_snapshot_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "duration_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "(recall_at_k IS NULL OR recall_at_k NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(reciprocal_rank IS NULL OR reciprocal_rank NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(ndcg IS NULL OR ndcg NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(highlight_iou IS NULL OR highlight_iou NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8))",
            name="ck_rag_eval_cases_finite",
        ),
        sa.ForeignKeyConstraint(
            ["run_configuration_id"],
            ["rag_evaluation_run_configurations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id", "evaluation_case_id"],
            ["rag_evaluation_dataset_cases.dataset_snapshot_id", "rag_evaluation_dataset_cases.id"],
            ondelete="RESTRICT",
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
        CREATE FUNCTION rag_verify_evaluation_dataset_snapshot()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            fixture jsonb;
            expected_query_set jsonb;
        BEGIN
            fixture := convert_from(NEW.fixture_bytes, 'UTF8')::jsonb;
            IF fixture->>'schema_version' <> '1'
               OR fixture->>'name' <> NEW.name
               OR (fixture->>'version')::integer <> NEW.version
               OR jsonb_typeof(fixture->'document_snapshot') <> 'array'
               OR jsonb_typeof(fixture->'cases') <> 'array'
               OR encode(digest(NEW.fixture_bytes, 'sha256'), 'hex') <> NEW.fixture_sha256
               OR encode(digest(NEW.document_snapshot_bytes, 'sha256'), 'hex')
                    <> NEW.document_snapshot_sha256
               OR encode(digest(NEW.query_set_bytes, 'sha256'), 'hex')
                    <> NEW.query_set_sha256
               OR convert_from(NEW.document_snapshot_bytes, 'UTF8')::jsonb
                    <> fixture->'document_snapshot'
               OR NEW.document_snapshot::jsonb <> fixture->'document_snapshot'
               OR NEW.case_count <> jsonb_array_length(fixture->'cases') THEN
                RAISE EXCEPTION 'invalid immutable evaluation dataset snapshot';
            END IF;
            SELECT jsonb_agg(
                       jsonb_build_object(
                           'id', item->>'id',
                           'query_sha256', item->>'query_sha256',
                           'permission_scenario', item->'permission_scenario'->>'name'
                       ) ORDER BY ordinal
                   )
              INTO expected_query_set
              FROM jsonb_array_elements(fixture->'cases') WITH ORDINALITY AS c(item, ordinal);
            IF convert_from(NEW.query_set_bytes, 'UTF8')::jsonb <> expected_query_set THEN
                RAISE EXCEPTION 'invalid immutable evaluation query set';
            END IF;
            RETURN NEW;
        EXCEPTION
            WHEN character_not_in_repertoire OR invalid_text_representation THEN
                RAISE EXCEPTION 'evaluation fixture bytes must be valid UTF-8 JSON';
        END;
        $$;
        CREATE TRIGGER trg_rag_evaluation_datasets_verify
        BEFORE INSERT ON rag_evaluation_datasets
        FOR EACH ROW EXECUTE FUNCTION rag_verify_evaluation_dataset_snapshot();

        CREATE FUNCTION rag_verify_evaluation_dataset_case()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            fixture_case jsonb;
            scenario jsonb;
            expected jsonb;
        BEGIN
            SELECT (convert_from(dataset.fixture_bytes, 'UTF8')::jsonb->'cases')->NEW.ordinal
              INTO fixture_case
              FROM rag_evaluation_datasets AS dataset
             WHERE dataset.id = NEW.dataset_snapshot_id;
            scenario := fixture_case->'permission_scenario';
            expected := fixture_case->'expected';
            IF fixture_case IS NULL
               OR convert_from(NEW.canonical_case_bytes, 'UTF8')::jsonb <> fixture_case
               OR encode(digest(NEW.canonical_case_bytes, 'sha256'), 'hex')
                    <> NEW.canonical_case_sha256
               OR fixture_case->>'id' <> NEW.id::text
               OR convert_from(NEW.query_bytes, 'UTF8') <> fixture_case->>'query'
               OR encode(digest(NEW.query_bytes, 'sha256'), 'hex') <> NEW.query_sha256
               OR NEW.query_sha256 <> fixture_case->>'query_sha256'
               OR NEW.permission_scenario::jsonb <> scenario
               OR NEW.expected_evidence_ids::jsonb <> expected->'evidence_unit_ids'
               OR NEW.authorized_source_ids::jsonb <> scenario->'authorized_source_ids'
               OR NEW.forbidden_source_ids::jsonb <> scenario->'forbidden_source_ids'
               OR NEW.expected_highlight::jsonb IS DISTINCT FROM expected->'highlight' THEN
                RAISE EXCEPTION 'invalid immutable evaluation dataset case';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_rag_evaluation_dataset_cases_verify
        BEFORE INSERT ON rag_evaluation_dataset_cases
        FOR EACH ROW EXECUTE FUNCTION rag_verify_evaluation_dataset_case();

        CREATE FUNCTION rag_require_complete_evaluation_dataset()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (SELECT count(*) FROM rag_evaluation_dataset_cases AS c
                WHERE c.dataset_snapshot_id = NEW.dataset_snapshot_id)
               <> (SELECT case_count FROM rag_evaluation_datasets AS d
                   WHERE d.id = NEW.dataset_snapshot_id) THEN
                RAISE EXCEPTION 'evaluation dataset cases are incomplete';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_rag_evaluation_runs_complete_dataset
        BEFORE INSERT ON rag_evaluation_runs
        FOR EACH ROW EXECUTE FUNCTION rag_require_complete_evaluation_dataset();

        CREATE FUNCTION rag_verify_evaluation_case_result()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            frozen rag_evaluation_dataset_cases%ROWTYPE;
            expected_dataset uuid;
            expected_repetitions integer;
            observation jsonb;
            exposure jsonb;
            highlight jsonb;
            calculated_duration float8;
            calculated_leaks integer;
            calculated_reproducible boolean;
        BEGIN
            SELECT run.dataset_snapshot_id, run.repetition_count
              INTO expected_dataset, expected_repetitions
              FROM rag_evaluation_run_configurations AS candidate
              JOIN rag_evaluation_runs AS run ON run.id = candidate.run_id
             WHERE candidate.id = NEW.run_configuration_id;
            SELECT * INTO frozen
              FROM rag_evaluation_dataset_cases
             WHERE dataset_snapshot_id = NEW.dataset_snapshot_id
               AND id = NEW.evaluation_case_id;
            IF expected_dataset IS NULL
               OR NEW.dataset_snapshot_id <> expected_dataset
               OR frozen.id IS NULL
               OR NEW.ordinal <> frozen.ordinal
               OR NEW.query_sha256 <> frozen.query_sha256
               OR NEW.permission_scenario::jsonb <> frozen.permission_scenario::jsonb
               OR NEW.expected_evidence_ids::jsonb <> frozen.expected_evidence_ids::jsonb
               OR jsonb_typeof(NEW.raw_observations::jsonb) <> 'array'
               OR jsonb_array_length(NEW.raw_observations::jsonb) <> expected_repetitions THEN
                RAISE EXCEPTION 'evaluation case result does not match the frozen case';
            END IF;
            FOR observation IN
                SELECT value FROM jsonb_array_elements(NEW.raw_observations::jsonb)
            LOOP
                IF jsonb_typeof(observation) <> 'object'
                   OR NOT observation ?& ARRAY[
                       'retrieved_evidence_ids', 'answer_status',
                       'answer_evidence_ids', 'conflict_evidence_ids',
                       'related_evidence_ids', 'highlight_kind',
                       'highlight_spans', 'highlight_bboxes', 'highlights',
                       'exposures', 'duration_ms'
                   ]
                   OR jsonb_typeof(observation->'retrieved_evidence_ids') <> 'array'
                   OR jsonb_typeof(observation->'answer_status') <> 'string'
                   OR observation->>'answer_status' NOT IN (
                       'supported', 'conflicting_evidence', 'insufficient_evidence'
                   )
                   OR jsonb_typeof(observation->'answer_evidence_ids') <> 'array'
                   OR jsonb_typeof(observation->'conflict_evidence_ids') <> 'array'
                   OR jsonb_typeof(observation->'related_evidence_ids') <> 'array'
                   OR jsonb_typeof(observation->'highlight_spans') <> 'array'
                   OR jsonb_typeof(observation->'highlight_bboxes') <> 'array'
                   OR jsonb_typeof(observation->'highlights') <> 'array'
                   OR jsonb_typeof(observation->'exposures') <> 'array'
                   OR jsonb_typeof(observation->'duration_ms') <> 'number'
                   OR (observation->>'duration_ms')::float8 < 0
                   OR (observation->>'duration_ms')::float8 IN (
                       'NaN'::float8, 'Infinity'::float8, '-Infinity'::float8
                   ) THEN
                    RAISE EXCEPTION 'invalid evaluation raw observation';
                END IF;
                PERFORM value::uuid
                  FROM jsonb_array_elements_text(
                      observation->'retrieved_evidence_ids'
                  );
                PERFORM value::uuid
                  FROM jsonb_array_elements_text(observation->'answer_evidence_ids');
                PERFORM value::uuid
                  FROM jsonb_array_elements_text(
                      observation->'conflict_evidence_ids'
                  );
                PERFORM value::uuid
                  FROM jsonb_array_elements_text(
                      observation->'related_evidence_ids'
                  );
                FOR exposure IN
                    SELECT value FROM jsonb_array_elements(observation->'exposures')
                LOOP
                    IF jsonb_typeof(exposure) <> 'object'
                       OR jsonb_typeof(exposure->'surface') <> 'string'
                       OR coalesce(exposure->>'surface', '') = ''
                       OR jsonb_typeof(exposure->'source_id') <> 'string' THEN
                        RAISE EXCEPTION 'invalid evaluation raw observation exposure';
                    END IF;
                    PERFORM (exposure->>'source_id')::uuid;
                END LOOP;
                FOR highlight IN
                    SELECT value FROM jsonb_array_elements(observation->'highlights')
                LOOP
                    IF jsonb_typeof(highlight) <> 'object'
                       OR NOT highlight ?& ARRAY[
                           'surface', 'document_id', 'asset_version_id',
                           'evidence_unit_id', 'page', 'kind', 'spans', 'bboxes'
                       ]
                       OR highlight->>'surface' NOT IN ('answer', 'conflict')
                       OR jsonb_typeof(highlight->'document_id') <> 'string'
                       OR jsonb_typeof(highlight->'asset_version_id') <> 'string'
                       OR jsonb_typeof(highlight->'evidence_unit_id') <> 'string'
                       OR jsonb_typeof(highlight->'kind') <> 'string'
                       OR jsonb_typeof(highlight->'spans') <> 'array'
                       OR jsonb_typeof(highlight->'bboxes') <> 'array'
                       OR (jsonb_typeof(highlight->'page') NOT IN ('number', 'null')) THEN
                        RAISE EXCEPTION 'invalid evaluation raw observation highlight';
                    END IF;
                    PERFORM (highlight->>'document_id')::uuid,
                            (highlight->>'asset_version_id')::uuid,
                            (highlight->>'evidence_unit_id')::uuid;
                END LOOP;
            END LOOP;
            SELECT sum((item->>'duration_ms')::float8)
              INTO calculated_duration
              FROM jsonb_array_elements(NEW.raw_observations::jsonb) AS raw(item);
            SELECT count(*)
              INTO calculated_leaks
              FROM jsonb_array_elements(NEW.raw_observations::jsonb) AS raw(item)
              CROSS JOIN LATERAL jsonb_array_elements(item->'exposures') AS e(exposed)
             WHERE frozen.forbidden_source_ids::jsonb ? (exposed->>'source_id')
                OR NOT frozen.authorized_source_ids::jsonb ? (exposed->>'source_id');
            SELECT count(DISTINCT item - 'duration_ms' - 'exposures') = 1
              INTO calculated_reproducible
              FROM jsonb_array_elements(NEW.raw_observations::jsonb) AS raw(item);
            NEW.duration_ms := calculated_duration;
            NEW.access_leaks := calculated_leaks;
            NEW.reproducible := calculated_reproducible;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_rag_evaluation_case_results_verify
        BEFORE INSERT ON rag_evaluation_case_results
        FOR EACH ROW EXECUTE FUNCTION rag_verify_evaluation_case_result();
        COMMENT ON FUNCTION rag_verify_evaluation_case_result() IS
            'Trust boundary: authenticated workers attest retrieval and highlight outputs; PostgreSQL validates their complete structured shape and derives duration, access leaks, reproducibility, exact case binding, and repetition count.';
        """
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
        "rag_evaluation_dataset_cases",
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
            IF OLD.status IN ('completed', 'failed')
               AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
                RAISE EXCEPTION 'terminal RAG evaluation run is immutable';
            END IF;
            IF NEW.owner_id <> OLD.owner_id
               OR NEW.dataset_snapshot_id <> OLD.dataset_snapshot_id
               OR NEW.evaluation_policy_version_id IS DISTINCT FROM OLD.evaluation_policy_version_id
               OR NEW.fixture_sha256 <> OLD.fixture_sha256
               OR NEW.document_snapshot_sha256 <> OLD.document_snapshot_sha256
               OR NEW.query_set_sha256 <> OLD.query_set_sha256
               OR NEW.runtime_environment::jsonb <> OLD.runtime_environment::jsonb
               OR NEW.metric_definition_version <> OLD.metric_definition_version
               OR NEW.retrieval_k <> OLD.retrieval_k
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
            IF OLD.status IN ('completed', 'failed')
               AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
                RAISE EXCEPTION 'terminal RAG evaluation candidate is immutable';
            END IF;
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
        CREATE FUNCTION rag_recompute_evaluation_candidate_metrics()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            expected_cases integer;
            actual_cases integer;
            expected_repetitions integer;
            calculated_recall float8;
            calculated_mrr float8;
            calculated_ndcg float8;
            calculated_precision float8;
            calculated_grounding float8;
            calculated_highlight float8;
            calculated_leaks bigint;
            calculated_reproducibility float8;
        BEGIN
            IF NEW.status <> 'completed'
               OR (TG_OP = 'UPDATE' AND OLD.status = 'completed') THEN
                RETURN NEW;
            END IF;
            SELECT dataset.case_count, run.repetition_count
              INTO expected_cases, expected_repetitions
              FROM rag_evaluation_runs AS run
              JOIN rag_evaluation_datasets AS dataset
                ON dataset.id = run.dataset_snapshot_id
             WHERE run.id = NEW.run_id;
            SELECT count(*),
                   avg(recall_at_k), avg(reciprocal_rank), avg(ndcg),
                   avg(correct_supported::integer)
                       FILTER (WHERE correct_supported IS NOT NULL),
                   avg(false_grounding::integer)
                       FILTER (WHERE false_grounding IS NOT NULL),
                   avg(highlight_iou) FILTER (WHERE highlight_iou IS NOT NULL),
                   sum(access_leaks), avg(reproducible::integer)
              INTO actual_cases, calculated_recall, calculated_mrr,
                   calculated_ndcg, calculated_precision, calculated_grounding,
                   calculated_highlight, calculated_leaks,
                   calculated_reproducibility
              FROM rag_evaluation_case_results
             WHERE run_configuration_id = NEW.id;
            IF actual_cases <> expected_cases
               OR EXISTS (
                    SELECT 1 FROM rag_evaluation_case_results AS result
                     WHERE result.run_configuration_id = NEW.id
                       AND jsonb_array_length(result.raw_observations::jsonb)
                           <> expected_repetitions
               )
               OR calculated_recall IS NULL
               OR calculated_mrr IS NULL
               OR calculated_ndcg IS NULL
               OR calculated_precision IS NULL
               OR calculated_grounding IS NULL
               OR calculated_highlight IS NULL
               OR calculated_leaks IS NULL
               OR calculated_reproducibility IS NULL THEN
                RAISE EXCEPTION 'candidate completion requires complete exact case results';
            END IF;
            NEW.recall_at_k := calculated_recall;
            NEW.mrr := calculated_mrr;
            NEW.ndcg := calculated_ndcg;
            NEW.supported_precision := calculated_precision;
            NEW.false_grounding_rate := calculated_grounding;
            NEW.highlight_iou := calculated_highlight;
            SELECT percentile_cont(0.50) WITHIN GROUP (
                       ORDER BY (observation->>'duration_ms')::float8
                   ),
                   percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY (observation->>'duration_ms')::float8
                   )
              INTO NEW.p50_latency_ms, NEW.p95_latency_ms
              FROM rag_evaluation_case_results AS result
              CROSS JOIN LATERAL jsonb_array_elements(
                  result.raw_observations::jsonb
              ) AS observation
             WHERE result.run_configuration_id = NEW.id;
            NEW.access_leaks := calculated_leaks;
            NEW.reproducibility := calculated_reproducibility;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_rag_eval_candidates_recompute_metrics
        BEFORE INSERT OR UPDATE ON rag_evaluation_run_configurations
        FOR EACH ROW EXECUTE FUNCTION rag_recompute_evaluation_candidate_metrics();
        COMMENT ON FUNCTION rag_recompute_evaluation_candidate_metrics() IS
            'Promotion cannot trust caller-supplied candidate aggregates; PostgreSQL recomputes them from the complete frozen set of immutable case rows.';

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
                      AND run.metric_definition_version = policy.metric_definition_version
                      AND run.retrieval_k = policy.retrieval_k
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
        "UPDATE rag_configuration_versions "
        "SET is_default = false, evaluation_state = 'pending' "
        "WHERE is_default OR evaluation_state = 'passed'"
    )
    op.execute(
        "DROP TRIGGER trg_rag_eval_candidates_recompute_metrics "
        "ON rag_evaluation_run_configurations"
    )
    op.execute("DROP FUNCTION rag_recompute_evaluation_candidate_metrics")
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
        "rag_evaluation_dataset_cases",
        "rag_evaluation_datasets",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION rag_evaluation_reject_immutable_mutation")
    op.execute(
        "DROP TRIGGER trg_rag_evaluation_case_results_verify "
        "ON rag_evaluation_case_results"
    )
    op.execute("DROP FUNCTION rag_verify_evaluation_case_result")
    op.execute(
        "DROP TRIGGER trg_rag_evaluation_runs_complete_dataset "
        "ON rag_evaluation_runs"
    )
    op.execute("DROP FUNCTION rag_require_complete_evaluation_dataset")
    op.execute(
        "DROP TRIGGER trg_rag_evaluation_dataset_cases_verify "
        "ON rag_evaluation_dataset_cases"
    )
    op.execute("DROP FUNCTION rag_verify_evaluation_dataset_case")
    op.execute(
        "DROP TRIGGER trg_rag_evaluation_datasets_verify "
        "ON rag_evaluation_datasets"
    )
    op.execute("DROP FUNCTION rag_verify_evaluation_dataset_snapshot")
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
    op.drop_table("rag_evaluation_dataset_cases")
    op.drop_table("rag_evaluation_datasets")
    op.execute(
        f"""
        DELETE FROM rag_profile_model_bindings
         WHERE id = '{BGE_PROFILE_BINDING_ID}'::uuid
           AND EXISTS (
               SELECT 1 FROM rag_evaluation_seed_ownership
                WHERE seed_kind = 'binding' AND seed_id = '{BGE_PROFILE_BINDING_ID}'::uuid
           );
        DELETE FROM rag_profiles
         WHERE id IN ('{BGE_INDEXING_PROFILE_ID}'::uuid, '{BGE_RETRIEVAL_PROFILE_ID}'::uuid)
           AND EXISTS (
               SELECT 1 FROM rag_evaluation_seed_ownership AS owned
                WHERE owned.seed_kind = 'profile' AND owned.seed_id = rag_profiles.id
           );
        DELETE FROM rag_model_definitions
         WHERE id = '{BGE_MODEL_ID}'::uuid
           AND EXISTS (
               SELECT 1 FROM rag_evaluation_seed_ownership
                WHERE seed_kind = 'model' AND seed_id = '{BGE_MODEL_ID}'::uuid
           );
        """
    )
    op.drop_table("rag_evaluation_seed_ownership")
