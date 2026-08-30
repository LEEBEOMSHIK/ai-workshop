from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_workshop.labs.rag.configurations.api import (
    get_rag_configuration_dispatcher,
    get_rag_configuration_service,
)
from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.service import ConfigurationSaveResult
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_ACTOR_ID = UUID("10000000-0000-0000-0000-000000000002")


def owner() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Owner",
        email="owner@example.test",
        normalized_email="owner@example.test",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def _configuration(
    *,
    owner_id: UUID | None = ACTOR_ID,
    name: str = "내 구성",
    is_system: bool = False,
) -> SavedRagConfiguration:
    configuration_id = uuid4()
    version = 1
    policy = AnswerPolicyVersion.create(
        configuration_id=configuration_id,
        version=version,
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )
    indexing_profile_id = uuid4()
    return SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=owner_id,
        name=name,
        version=version,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=None,
        answer_policy_version=policy,
        workspace_ids=() if is_system else (uuid4(),),
        evaluation_state=EvaluationState.PENDING,
        is_system=is_system,
        is_default=False,
    )


class FakeConfigurationService:
    def __init__(self, configurations: list[SavedRagConfiguration]) -> None:
        self.configurations = configurations
        self.created: dict[str, object] | None = None

    async def list(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        assert actor_id == ACTOR_ID
        return self.configurations

    async def create(self, **values: object) -> ConfigurationSaveResult:
        assert values["owner_id"] == ACTOR_ID
        self.created = values
        configuration = self.configurations[-1]
        return ConfigurationSaveResult(configuration, (uuid4(), uuid4()))

    async def detail(
        self, configuration_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration:
        assert actor_id == ACTOR_ID
        for configuration in self.configurations:
            if configuration.id == configuration_id:
                return configuration
        raise AppError("not_found", "The requested resource was not found.", 404)

    async def promote_default(
        self, configuration_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration:
        await self.detail(configuration_id, actor_id)
        raise AppError(
            "evaluation_policy_required",
            "An applicable versioned Evaluation Policy and passing result are required.",
            409,
        )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def ensure_indexed(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


def _client(
    service: FakeConfigurationService,
    dispatcher: RecordingDispatcher,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_configuration_service] = lambda: service
    app.dependency_overrides[get_rag_configuration_dispatcher] = lambda: dispatcher
    return TestClient(app)


def test_list_exposes_only_the_supplied_system_baseline_and_actor_configurations() -> None:
    baseline = _configuration(owner_id=None, name="BM25 기준선", is_system=True)
    own = _configuration()
    service = FakeConfigurationService([baseline, own])

    with _client(service, RecordingDispatcher()) as client:
        response = client.get("/api/v1/rag/configurations")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload] == ["BM25 기준선", "내 구성"]
    assert payload[0]["evaluation_state"] == "pending"
    assert payload[0]["is_default"] is False
    assert payload[0]["experimental"] is True
    assert payload[0]["generation_profile_id"] is None


def test_create_accepts_extractive_policy_and_dispatches_only_persisted_job_ids() -> None:
    workspace_id = uuid4()
    indexing_profile_id = uuid4()
    retrieval_profile_id = uuid4()
    saved = _configuration()
    service = FakeConfigurationService([saved])
    dispatcher = RecordingDispatcher()

    with _client(service, dispatcher) as client:
        response = client.post(
            "/api/v1/rag/configurations",
            json={
                "name": "내 구성",
                "indexing_profile_id": str(indexing_profile_id),
                "retrieval_profile_id": str(retrieval_profile_id),
                "generation_profile_id": None,
                "answer_policy": {
                    "min_semantic_score": 0.8,
                    "min_keyword_coverage": 0.7,
                    "require_complete_provenance": True,
                    "conflict_mode": "separate_sources",
                },
                "workspace_ids": [str(workspace_id)],
            },
        )

    assert response.status_code == 201
    assert response.json()["id"] == str(saved.id)
    assert service.created == {
        "owner_id": ACTOR_ID,
        "name": "내 구성",
        "indexing_profile_id": indexing_profile_id,
        "retrieval_profile_id": retrieval_profile_id,
        "generation_profile_id": None,
        "min_semantic_score": 0.8,
        "min_keyword_coverage": 0.7,
        "require_complete_provenance": True,
        "conflict_mode": "separate_sources",
        "workspace_ids": (workspace_id,),
    }
    assert len(dispatcher.job_ids) == 2


def test_detail_and_default_are_nondisclosing_or_fail_closed() -> None:
    saved = _configuration()
    service = FakeConfigurationService([saved])

    with _client(service, RecordingDispatcher()) as client:
        detail = client.get(f"/api/v1/rag/configurations/{saved.id}")
        missing = client.get(f"/api/v1/rag/configurations/{uuid4()}")
        promotion = client.post(f"/api/v1/rag/configurations/{saved.id}/default")

    assert detail.status_code == 200
    assert detail.json()["version_id"] == str(saved.version_id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert promotion.status_code == 409
    assert promotion.json()["error"]["code"] == "evaluation_policy_required"
