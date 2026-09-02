import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_workshop.labs.rag.evaluation.api import get_evaluation_service
from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
)
from ai_workshop.labs.rag.evaluation.service import (
    EvaluationCandidateView,
    EvaluationRunView,
)
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("10000000-0000-0000-0000-000000000002")
REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
FIXTURE = REPOSITORY_ROOT / "sample-data/public/rag/evaluation/search-v1.json"


def owner() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Owner",
        email="owner@example.test",
        normalized_email="owner@example.test",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def member() -> User:
    return User(
        id=MEMBER_ID,
        display_name="Member",
        email="member@example.test",
        normalized_email="member@example.test",
        password_hash="hash",
        role=UserRole.MEMBER,
    )


def metrics() -> EvaluationMetrics:
    return EvaluationMetrics(
        recall_at_k=1 / 3,
        mrr=2 / 3,
        ndcg=0.75,
        supported_precision=1.0,
        false_grounding_rate=0.0,
        highlight_iou=0.875,
        p50_latency_ms=12.3456789,
        p95_latency_ms=98.7654321,
        access_leaks=0,
        reproducibility=1.0,
    )


class FakeEvaluationService:
    def __init__(self, *, actor_id: UUID = ACTOR_ID) -> None:
        self.actor_id = actor_id
        self.dataset_id = uuid4()
        self.policy = EvaluationPolicy.create(
            owner_id=ACTOR_ID,
            dataset_snapshot_id=self.dataset_id,
            version=1,
            metric_definition_version=1,
            retrieval_k=3,
            recall_at_k=0.1,
            mrr=0.1,
            ndcg=0.1,
            supported_precision=0.1,
            max_false_grounding_rate=0.9,
            min_highlight_iou=0.1,
            max_p50_latency_ms=1000,
            max_p95_latency_ms=2000,
            max_access_leaks=0,
            required_reproducibility=1.0,
        )
        self.candidate = EvaluationCandidateView(
            id=uuid4(),
            configuration_version_id=uuid4(),
            ordinal=0,
            status=CandidateStatus.COMPLETED,
            failure=None,
            metrics=metrics(),
            case_results=(),
        )
        self.run = EvaluationRunView(
            id=uuid4(),
            owner_id=ACTOR_ID,
            dataset_snapshot_id=self.dataset_id,
            evaluation_policy_version_id=self.policy.id,
            status=EvaluationRunStatus.COMPLETED,
            fixture_sha256="1" * 64,
            document_snapshot_sha256="2" * 64,
            query_set_sha256="3" * 64,
            execution_snapshot_sha256="4" * 64,
            runtime_environment={"python": "3.13"},
            worker_runtime_environment={"execution_role": "celery-worker"},
            metric_definition_version=1,
            retrieval_k=3,
            repetition_count=2,
            failure=None,
            candidates=(self.candidate,),
        )
        self.created_policy: dict[str, object] | None = None
        self.started: dict[str, object] | None = None

    async def create_policy(self, **values: object) -> EvaluationPolicy:
        assert values["actor_id"] == self.actor_id
        self.created_policy = values
        return self.policy

    async def start_run(self, **values: object) -> EvaluationRunView:
        assert values["actor_id"] == self.actor_id
        self.started = values
        return self.run

    async def detail(self, run_id: UUID, actor_id: UUID) -> EvaluationRunView:
        assert actor_id == self.actor_id
        assert run_id == self.run.id
        return self.run

    async def list(self, actor_id: UUID, limit: int) -> tuple[EvaluationRunView, ...]:
        assert actor_id == self.actor_id
        assert limit == 20
        return (self.run,)


def _client(service: FakeEvaluationService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_evaluation_service] = lambda: service
    return TestClient(app)


def _member_client(service: FakeEvaluationService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = member
    app.dependency_overrides[get_evaluation_service] = lambda: service
    return TestClient(app)


def test_policy_api_requires_complete_exact_security_thresholds() -> None:
    service = FakeEvaluationService()
    with _client(service) as client:
        invalid = client.post(
            "/api/v1/rag/evaluation-policies",
            json={
                "dataset_snapshot_id": str(service.dataset_id),
                "metric_definition_version": 1,
                "retrieval_k": 3,
                "min_recall_at_k": 0.1,
                "min_mrr": 0.1,
                "min_ndcg": 0.1,
                "min_supported_precision": 0.1,
                "max_false_grounding_rate": 0.9,
                "min_highlight_iou": 0.1,
                "max_p50_latency_ms": 1000,
                "max_p95_latency_ms": 2000,
                "max_access_leaks": 1,
                "required_reproducibility": 1.0,
            },
        )
        valid = client.post(
            "/api/v1/rag/evaluation-policies",
            json={
                "dataset_snapshot_id": str(service.dataset_id),
                "metric_definition_version": 1,
                "retrieval_k": 3,
                "min_recall_at_k": 0.1,
                "min_mrr": 0.1,
                "min_ndcg": 0.1,
                "min_supported_precision": 0.1,
                "max_false_grounding_rate": 0.9,
                "min_highlight_iou": 0.1,
                "max_p50_latency_ms": 1000,
                "max_p95_latency_ms": 2000,
                "max_access_leaks": 0,
                "required_reproducibility": 1.0,
            },
        )

    assert invalid.status_code == 422
    assert valid.status_code == 201
    assert valid.json()["id"] == str(service.policy.id)


def test_run_create_detail_and_list_keep_candidate_identity_and_round_only_response() -> None:
    service = FakeEvaluationService()
    fixture = json.loads(FIXTURE.read_text("utf-8"))
    with _client(service) as client:
        created = client.post(
            "/api/v1/rag/evaluation-runs",
            json={
                "dataset_fixture": fixture,
                "evaluation_policy_version_id": str(service.policy.id),
                "configuration_version_ids": [
                    str(service.candidate.configuration_version_id)
                ],
                "metric_definition_version": 1,
                "retrieval_k": 3,
                "repetition_count": 2,
            },
        )
        detail = client.get(f"/api/v1/rag/evaluation-runs/{service.run.id}")
        listed = client.get("/api/v1/rag/evaluation-runs")

    assert created.status_code == 202
    assert detail.status_code == 200
    assert listed.status_code == 200
    payload = detail.json()
    assert payload["candidates"][0]["ordinal"] == 0
    assert payload["candidates"][0]["configuration_version_id"] == str(
        service.candidate.configuration_version_id
    )
    assert payload["candidates"][0]["metrics"]["recall_at_k"] == 0.333333
    assert payload["candidates"][0]["metrics"]["p50_latency_ms"] == 12.345679
    assert payload["metric_definition_version"] == 1
    assert payload["retrieval_k"] == 3
    assert payload["execution_snapshot_sha256"] == "4" * 64
    assert payload["worker_runtime_environment"]["execution_role"] == "celery-worker"
    assert service.candidate.metrics is not None
    assert service.candidate.metrics.recall_at_k == 1 / 3
    assert len(listed.json()) == 1


def test_member_cannot_create_evaluation_policy_or_start_run() -> None:
    service = FakeEvaluationService(actor_id=MEMBER_ID)
    fixture = json.loads(FIXTURE.read_text("utf-8"))

    with _member_client(service) as client:
        policy = client.post(
            "/api/v1/rag/evaluation-policies",
            json={
                "dataset_snapshot_id": str(service.dataset_id),
                "metric_definition_version": 1,
                "retrieval_k": 3,
                "min_recall_at_k": 0.1,
                "min_mrr": 0.1,
                "min_ndcg": 0.1,
                "min_supported_precision": 0.1,
                "max_false_grounding_rate": 0.9,
                "min_highlight_iou": 0.1,
                "max_p50_latency_ms": 1000,
                "max_p95_latency_ms": 2000,
                "max_access_leaks": 0,
                "required_reproducibility": 1.0,
            },
        )
        run = client.post(
            "/api/v1/rag/evaluation-runs",
            json={
                "dataset_fixture": fixture,
                "evaluation_policy_version_id": str(service.policy.id),
                "configuration_version_ids": [
                    str(service.candidate.configuration_version_id)
                ],
                "metric_definition_version": 1,
                "retrieval_k": 3,
                "repetition_count": 2,
            },
        )

    assert policy.status_code == 403
    assert policy.json()["error"]["code"] == "owner_required"
    assert run.status_code == 403
    assert run.json()["error"]["code"] == "owner_required"
