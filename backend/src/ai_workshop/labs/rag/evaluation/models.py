# ruff: noqa: E501 -- SQL constraints stay aligned with the migration verbatim.

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EvaluationDatasetRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", "version"),
        UniqueConstraint("owner_id", "fixture_sha256"),
        CheckConstraint("version > 0", name="ck_rag_eval_datasets_version"),
        CheckConstraint("case_count > 0", name="ck_rag_eval_datasets_cases"),
        CheckConstraint(
            "length(fixture_sha256) = 64 AND "
            "length(document_snapshot_sha256) = 64 AND "
            "length(query_set_sha256) = 64",
            name="ck_rag_eval_datasets_hashes",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fixture_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    fixture_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    document_snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    document_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_set_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)


class EvaluationDatasetCaseRecord(TimestampMixin, Base):
    __tablename__ = "rag_evaluation_dataset_cases"
    __table_args__ = (
        UniqueConstraint("dataset_snapshot_id", "ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_rag_eval_dataset_cases_ordinal"),
    )

    dataset_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_datasets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_case_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    canonical_case_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_scenario: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    expected_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    authorized_source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    forbidden_source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expected_highlight: Mapped[dict[str, object] | None] = mapped_column(JSON)


class EvaluationSeedOwnershipRecord(Base):
    __tablename__ = "rag_evaluation_seed_ownership"

    seed_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    seed_id: Mapped[UUID] = mapped_column(primary_key=True)


class EvaluationPolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_policies"
    __table_args__ = (
        UniqueConstraint("owner_id", "dataset_snapshot_id", "version"),
        CheckConstraint("version > 0", name="ck_rag_eval_policies_version"),
        CheckConstraint(
            "min_recall_at_k BETWEEN 0 AND 1 AND "
            "min_mrr BETWEEN 0 AND 1 AND min_ndcg BETWEEN 0 AND 1 AND "
            "min_supported_precision BETWEEN 0 AND 1 AND "
            "max_false_grounding_rate BETWEEN 0 AND 1 AND "
            "min_highlight_iou BETWEEN 0 AND 1",
            name="ck_rag_eval_policies_ratios",
        ),
        CheckConstraint(
            "max_p50_latency_ms >= 0 AND max_p95_latency_ms >= max_p50_latency_ms",
            name="ck_rag_eval_policies_latency",
        ),
        CheckConstraint(
            "max_access_leaks = 0", name="ck_rag_eval_policies_zero_leaks"
        ),
        CheckConstraint(
            "required_reproducibility = 1.0",
            name="ck_rag_eval_policies_reproducibility",
        ),
        CheckConstraint(
            "metric_definition_version = 1 AND retrieval_k BETWEEN 1 AND 50",
            name="ck_rag_eval_policies_metric_definition",
        ),
        CheckConstraint(
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
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_datasets.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_k: Mapped[int] = mapped_column(Integer, nullable=False)
    min_recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    min_mrr: Mapped[float] = mapped_column(Float, nullable=False)
    min_ndcg: Mapped[float] = mapped_column(Float, nullable=False)
    min_supported_precision: Mapped[float] = mapped_column(Float, nullable=False)
    max_false_grounding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    min_highlight_iou: Mapped[float] = mapped_column(Float, nullable=False)
    max_p50_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    max_p95_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    max_access_leaks: Mapped[int] = mapped_column(Integer, nullable=False)
    required_reproducibility: Mapped[float] = mapped_column(Float, nullable=False)


class EvaluationRunRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_rag_eval_runs_status",
        ),
        CheckConstraint("repetition_count >= 2", name="ck_rag_eval_runs_repetitions"),
        CheckConstraint("candidate_count > 0", name="ck_rag_eval_runs_candidates"),
        CheckConstraint(
            "metric_definition_version = 1 AND retrieval_k BETWEEN 1 AND 50",
            name="ck_rag_eval_runs_metric_definition",
        ),
        CheckConstraint(
            "length(execution_snapshot_sha256) = 64",
            name="ck_rag_eval_runs_execution_snapshot_hash",
        ),
        CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND finished_at IS NULL) OR "
            "(status = 'running' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND claim_token IS NULL "
            "AND claimed_at IS NULL AND finished_at IS NOT NULL)",
            name="ck_rag_eval_runs_claim_state",
        ),
        Index("ix_rag_eval_runs_claim", "status", "claimed_at"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_datasets.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_policy_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_evaluation_policies.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    fixture_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    execution_snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    execution_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_environment: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    worker_runtime_environment: Mapped[dict[str, object] | None] = mapped_column(JSON)
    metric_definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_k: Mapped[int] = mapped_column(Integer, nullable=False)
    repetition_count: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure: Mapped[str | None] = mapped_column(String(700))


class EvaluationRunConfigurationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_run_configurations"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal"),
        UniqueConstraint("run_id", "configuration_version_id"),
        CheckConstraint("ordinal >= 0", name="ck_rag_eval_candidates_ordinal"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_rag_eval_candidates_status",
        ),
        CheckConstraint(
            "access_leaks IS NULL OR access_leaks >= 0",
            name="ck_rag_eval_candidates_leaks",
        ),
        CheckConstraint(
            "(recall_at_k IS NULL OR recall_at_k BETWEEN 0 AND 1) AND "
            "(mrr IS NULL OR mrr BETWEEN 0 AND 1) AND "
            "(ndcg IS NULL OR ndcg BETWEEN 0 AND 1) AND "
            "(supported_precision IS NULL OR supported_precision BETWEEN 0 AND 1) AND "
            "(false_grounding_rate IS NULL OR false_grounding_rate BETWEEN 0 AND 1) AND "
            "(highlight_iou IS NULL OR highlight_iou BETWEEN 0 AND 1) AND "
            "(reproducibility IS NULL OR reproducibility BETWEEN 0 AND 1)",
            name="ck_rag_eval_candidates_ratios",
        ),
        CheckConstraint(
            "(p50_latency_ms IS NULL OR "
            "(p50_latency_ms >= 0 AND p50_latency_ms <> 'Infinity'::float8)) AND "
            "(p95_latency_ms IS NULL OR "
            "(p95_latency_ms >= 0 AND p95_latency_ms <> 'Infinity'::float8)) AND "
            "(p50_latency_ms IS NULL OR p95_latency_ms IS NULL OR "
            "p95_latency_ms >= p50_latency_ms)",
            name="ck_rag_eval_candidates_latency",
        ),
        CheckConstraint(
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
        CheckConstraint(
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
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    retrieval_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    answer_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_answer_policy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    generation_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT")
    )
    component_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    failure: Mapped[str | None] = mapped_column(String(700))
    recall_at_k: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    ndcg: Mapped[float | None] = mapped_column(Float)
    supported_precision: Mapped[float | None] = mapped_column(Float)
    false_grounding_rate: Mapped[float | None] = mapped_column(Float)
    highlight_iou: Mapped[float | None] = mapped_column(Float)
    p50_latency_ms: Mapped[float | None] = mapped_column(Float)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float)
    access_leaks: Mapped[int | None] = mapped_column(Integer)
    reproducibility: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationCaseResultRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evaluation_case_results"
    __table_args__ = (
        UniqueConstraint("run_configuration_id", "evaluation_case_id"),
        UniqueConstraint("run_configuration_id", "ordinal"),
        ForeignKeyConstraint(
            ["dataset_snapshot_id", "evaluation_case_id"],
            ["rag_evaluation_dataset_cases.dataset_snapshot_id", "rag_evaluation_dataset_cases.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("ordinal >= 0", name="ck_rag_eval_cases_ordinal"),
        CheckConstraint("duration_ms >= 0", name="ck_rag_eval_cases_duration"),
        CheckConstraint("access_leaks >= 0", name="ck_rag_eval_cases_leaks"),
        CheckConstraint(
            "duration_ms NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) AND "
            "(recall_at_k IS NULL OR recall_at_k NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(reciprocal_rank IS NULL OR reciprocal_rank NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(ndcg IS NULL OR ndcg NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)) AND "
            "(highlight_iou IS NULL OR highlight_iou NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8))",
            name="ck_rag_eval_cases_finite",
        ),
    )

    run_configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_run_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    evaluation_case_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_scenario: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    expected_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    raw_observations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float | None] = mapped_column(Float)
    reciprocal_rank: Mapped[float | None] = mapped_column(Float)
    ndcg: Mapped[float | None] = mapped_column(Float)
    correct_supported: Mapped[bool | None]
    false_grounding: Mapped[bool | None]
    highlight_iou: Mapped[float | None] = mapped_column(Float)
    access_leaks: Mapped[int] = mapped_column(Integer, nullable=False)
    reproducible: Mapped[bool] = mapped_column(nullable=False)


class EvaluationDispatchRecord(TimestampMixin, Base):
    __tablename__ = "rag_evaluation_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent')",
            name="ck_rag_eval_dispatch_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_rag_eval_dispatch_attempt"),
        CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL)",
            name="ck_rag_eval_dispatch_state",
        ),
        Index("ix_rag_eval_dispatch_ready", "status", "available_at"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(String(700))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
