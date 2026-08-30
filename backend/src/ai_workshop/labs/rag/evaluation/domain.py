import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from ai_workshop.labs.rag.evaluation.metrics import BoundingBox, CharacterSpan
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus, HighlightKind


class EvaluationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PromotionPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PermissionScenario:
    name: str
    actor: str
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    allowed_source_ids: frozenset[UUID]
    forbidden_source_ids: frozenset[UUID]
    as_of: str


@dataclass(frozen=True, slots=True)
class ExpectedHighlight:
    kind: HighlightKind
    spans: tuple[CharacterSpan, ...]
    bboxes: tuple[BoundingBox, ...]


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: UUID
    kind: str
    query: str
    query_sha256: str
    permission_scenario: PermissionScenario
    expected_answer_status: AnswerStatus
    expected_evidence_ids: frozenset[UUID]
    expected_highlight: ExpectedHighlight | None


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    id: UUID
    name: str
    version: int
    fixture_bytes: bytes
    fixture_sha256: str
    document_snapshot: tuple[Mapping[str, object], ...]
    document_snapshot_sha256: str
    query_set_sha256: str
    cases: tuple[EvaluationCase, ...]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings.")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")
    return value


def _uuid_tuple(value: object, name: str) -> tuple[UUID, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array.")
    try:
        result = tuple(UUID(_string(item, name)) for item in value)
    except ValueError as exc:
        raise ValueError(f"{name} must contain UUIDs.") from exc
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique UUIDs.")
    return result


def _load_highlight(value: object) -> ExpectedHighlight | None:
    if value is None:
        return None
    document = _mapping(value, "expected.highlight")
    kind = HighlightKind(_string(document.get("kind"), "expected.highlight.kind"))
    raw_spans = document.get("spans", [])
    raw_bboxes = document.get("bboxes", [])
    if not isinstance(raw_spans, list) or not isinstance(raw_bboxes, list):
        raise ValueError("Expected highlight locations must be arrays.")
    spans: list[CharacterSpan] = []
    for raw in raw_spans:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in raw)
        ):
            raise ValueError("Expected highlight spans must contain integer pairs.")
        spans.append(CharacterSpan(raw[0], raw[1]))
    bboxes: list[BoundingBox] = []
    for raw in raw_bboxes:
        if (
            not isinstance(raw, list)
            or len(raw) != 4
            or not all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in raw
            )
        ):
            raise ValueError("Expected highlight bboxes must contain four numbers.")
        bboxes.append(BoundingBox(*(float(item) for item in raw)))
    if not spans and not bboxes:
        raise ValueError("An expected highlight requires a truthful location.")
    return ExpectedHighlight(kind, tuple(spans), tuple(bboxes))


def load_evaluation_dataset(fixture_bytes: bytes) -> EvaluationDataset:
    try:
        root = _mapping(json.loads(fixture_bytes), "evaluation fixture")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The evaluation fixture must be UTF-8 JSON.") from exc
    if root.get("schema_version") != 1:
        raise ValueError("The evaluation fixture schema version is unsupported.")
    raw_snapshot = root.get("document_snapshot")
    raw_cases = root.get("cases")
    if not isinstance(raw_snapshot, list) or not raw_snapshot:
        raise ValueError("The evaluation fixture requires a document snapshot.")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("The evaluation fixture requires cases.")
    snapshot = tuple(_mapping(item, "document snapshot item") for item in raw_snapshot)
    cases: list[EvaluationCase] = []
    for raw_case in raw_cases:
        case = _mapping(raw_case, "evaluation case")
        query = _string(case.get("query"), "evaluation case query")
        query_sha256 = _string(
            case.get("query_sha256"), "evaluation case query_sha256"
        )
        if query_sha256 != _sha256(query.encode("utf-8")):
            raise ValueError("The evaluation case query SHA-256 does not match its query.")
        raw_scenario = _mapping(
            case.get("permission_scenario"), "permission scenario"
        )
        scenario = PermissionScenario(
            name=_string(raw_scenario.get("name"), "permission scenario name"),
            actor=_string(raw_scenario.get("actor"), "permission scenario actor"),
            workspace_ids=_uuid_tuple(
                raw_scenario.get("workspace_ids"), "permission workspace_ids"
            ),
            folder_ids=_uuid_tuple(
                raw_scenario.get("folder_ids", []), "permission folder_ids"
            ),
            allowed_source_ids=frozenset(
                _uuid_tuple(
                    raw_scenario.get("allowed_source_ids", []),
                    "permission allowed_source_ids",
                )
            ),
            forbidden_source_ids=frozenset(
                _uuid_tuple(
                    raw_scenario.get("forbidden_source_ids", []),
                    "permission forbidden_source_ids",
                )
            ),
            as_of=_string(raw_scenario.get("as_of"), "permission as_of"),
        )
        expected = _mapping(case.get("expected"), "evaluation case expected")
        cases.append(
            EvaluationCase(
                id=UUID(_string(case.get("id"), "evaluation case id")),
                kind=_string(case.get("kind"), "evaluation case kind"),
                query=query,
                query_sha256=query_sha256,
                permission_scenario=scenario,
                expected_answer_status=AnswerStatus(
                    _string(expected.get("answer_status"), "expected answer status")
                ),
                expected_evidence_ids=frozenset(
                    _uuid_tuple(
                        expected.get("evidence_unit_ids", []),
                        "expected evidence_unit_ids",
                    )
                ),
                expected_highlight=_load_highlight(expected.get("highlight")),
            )
        )
    if len(cases) != len({case.id for case in cases}):
        raise ValueError("Evaluation case IDs must be unique.")
    query_identity = [
        {
            "id": str(case.id),
            "query_sha256": case.query_sha256,
            "permission_scenario": case.permission_scenario.name,
        }
        for case in cases
    ]
    version = root.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("The evaluation dataset version must be positive.")
    return EvaluationDataset(
        id=UUID(_string(root.get("id"), "evaluation dataset id")),
        name=_string(root.get("name"), "evaluation dataset name"),
        version=version,
        fixture_bytes=bytes(fixture_bytes),
        fixture_sha256=_sha256(fixture_bytes),
        document_snapshot=snapshot,
        document_snapshot_sha256=_sha256(_canonical_bytes(raw_snapshot)),
        query_set_sha256=_sha256(_canonical_bytes(query_identity)),
        cases=tuple(cases),
    )


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    recall_at_k: float
    mrr: float
    ndcg: float
    supported_precision: float
    false_grounding_rate: float
    highlight_iou: float
    p50_latency_ms: float
    p95_latency_ms: float
    access_leaks: int
    reproducibility: float

    def __post_init__(self) -> None:
        ratios = (
            self.recall_at_k,
            self.mrr,
            self.ndcg,
            self.supported_precision,
            self.false_grounding_rate,
            self.highlight_iou,
            self.reproducibility,
        )
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in ratios):
            raise PromotionPolicyError("Evaluation ratio metrics must be finite and bounded.")
        if not all(
            math.isfinite(value) and value >= 0.0
            for value in (self.p50_latency_ms, self.p95_latency_ms)
        ):
            raise PromotionPolicyError("Evaluation latency metrics must be finite and nonnegative.")
        if self.p95_latency_ms < self.p50_latency_ms:
            raise PromotionPolicyError("P95 latency cannot be below P50 latency.")
        if self.access_leaks < 0:
            raise PromotionPolicyError("Access leak count cannot be negative.")


@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    id: UUID
    owner_id: UUID
    dataset_snapshot_id: UUID
    version: int
    recall_at_k: float
    mrr: float
    ndcg: float
    supported_precision: float
    max_false_grounding_rate: float
    min_highlight_iou: float
    max_p50_latency_ms: float
    max_p95_latency_ms: float
    max_access_leaks: int
    required_reproducibility: float

    @classmethod
    def create(
        cls,
        *,
        owner_id: UUID,
        dataset_snapshot_id: UUID,
        version: int,
        recall_at_k: float,
        mrr: float,
        ndcg: float,
        supported_precision: float,
        max_false_grounding_rate: float,
        min_highlight_iou: float,
        max_p50_latency_ms: float,
        max_p95_latency_ms: float,
        max_access_leaks: int,
        required_reproducibility: float,
    ) -> "EvaluationPolicy":
        policy = cls(
            id=uuid4(),
            owner_id=owner_id,
            dataset_snapshot_id=dataset_snapshot_id,
            version=version,
            recall_at_k=recall_at_k,
            mrr=mrr,
            ndcg=ndcg,
            supported_precision=supported_precision,
            max_false_grounding_rate=max_false_grounding_rate,
            min_highlight_iou=min_highlight_iou,
            max_p50_latency_ms=max_p50_latency_ms,
            max_p95_latency_ms=max_p95_latency_ms,
            max_access_leaks=max_access_leaks,
            required_reproducibility=required_reproducibility,
        )
        return policy.validate()

    def validate(self) -> "EvaluationPolicy":
        if self.version < 1:
            raise PromotionPolicyError("An Evaluation Policy version must be positive.")
        ratios = (
            self.recall_at_k,
            self.mrr,
            self.ndcg,
            self.supported_precision,
            self.max_false_grounding_rate,
            self.min_highlight_iou,
            self.required_reproducibility,
        )
        if not all(math.isfinite(value) for value in ratios):
            raise PromotionPolicyError("Evaluation Policy thresholds must be finite.")
        if not all(0.0 <= value <= 1.0 for value in ratios):
            raise PromotionPolicyError("Evaluation Policy ratio thresholds must be bounded.")
        latencies = (self.max_p50_latency_ms, self.max_p95_latency_ms)
        if not all(math.isfinite(value) and value >= 0.0 for value in latencies):
            raise PromotionPolicyError("Evaluation Policy latency thresholds must be finite.")
        if self.max_p95_latency_ms < self.max_p50_latency_ms:
            raise PromotionPolicyError("P95 latency threshold cannot be below P50.")
        if self.max_access_leaks != 0:
            raise PromotionPolicyError("max_access_leaks must be exactly zero.")
        if self.required_reproducibility != 1.0:
            raise PromotionPolicyError("required_reproducibility must be exactly 1.0.")
        return self


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    configuration_version_id: UUID
    evaluated_configuration_version_id: UUID
    run_status: EvaluationRunStatus
    candidate_status: CandidateStatus
    failure: str | None
    metrics: EvaluationMetrics | None


class PromotionGate:
    @staticmethod
    def qualifies(
        policy: EvaluationPolicy | None,
        evidence: PromotionEvidence,
    ) -> bool:
        if policy is None:
            return False
        policy.validate()
        metrics = evidence.metrics
        if (
            evidence.run_status is not EvaluationRunStatus.COMPLETED
            or evidence.candidate_status is not CandidateStatus.COMPLETED
            or evidence.failure is not None
            or metrics is None
            or evidence.configuration_version_id
            != evidence.evaluated_configuration_version_id
        ):
            return False
        return (
            metrics.recall_at_k >= policy.recall_at_k
            and metrics.mrr >= policy.mrr
            and metrics.ndcg >= policy.ndcg
            and metrics.supported_precision >= policy.supported_precision
            and metrics.false_grounding_rate <= policy.max_false_grounding_rate
            and metrics.highlight_iou >= policy.min_highlight_iou
            and metrics.p50_latency_ms <= policy.max_p50_latency_ms
            and metrics.p95_latency_ms <= policy.max_p95_latency_ms
            and metrics.access_leaks <= policy.max_access_leaks
            and metrics.reproducibility >= policy.required_reproducibility
        )
