from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_workshop.config import LearningLimits
from ai_workshop.learning_composition import get_learning_service
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.learning.domain import LearningRecord
from ai_workshop.platform.learning.references import (
    ReferenceResolver,
    ReferenceView,
)
from ai_workshop.platform.learning.repository import LearningRepository
from ai_workshop.platform.learning.schemas import LearningDraft, ReferenceKey
from ai_workshop.platform.learning.service import LearningCursorCodec, LearningService
from tests.unit.platform.learning.test_service import (
    MemoryLearningRepository,
    MutableReferenceResolver,
)


def user(user_id: UUID) -> User:
    return User(
        id=user_id,
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def learning_service(
    repository: LearningRepository,
    resolver: ReferenceResolver | None = None,
) -> LearningService:
    return LearningService(
        repository,
        resolver or MutableReferenceResolver(),
        LearningLimits(),
        LearningCursorCodec("cursor-secret-" * 4, max_length=4096),
    )


def test_anonymous_request_is_401_before_learning_service_resolution() -> None:
    service_calls = 0

    def service_override() -> LearningService:
        nonlocal service_calls
        service_calls += 1
        return learning_service(MemoryLearningRepository())

    app = create_app()
    app.dependency_overrides[get_learning_service] = service_override

    with TestClient(app) as client:
        response = client.get("/api/v1/learning/records")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert service_calls == 0


def test_learning_create_detail_list_and_topics_contract() -> None:
    actor_id = uuid4()
    repository = MemoryLearningRepository()
    service = learning_service(repository)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: service

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/learning/records",
            json={
                "title": "Chunking notes",
                "body": "Keep structural boundaries.",
                "kind": "note",
                "topic_keys": ["rag"],
                "domain_labels": ["research"],
                "references": [],
            },
        )
        record_id = created.json()["id"]
        detail = client.get(f"/api/v1/learning/records/{record_id}")
        listed = client.get("/api/v1/learning/records?topic_key=rag&archived=false")
        topics = client.get("/api/v1/learning/topics")

    assert created.status_code == 201
    assert detail.status_code == 200
    assert detail.json() == created.json()
    assert created.json() == {
        "id": record_id,
        "revision": 1,
        "created_at": created.json()["created_at"],
        "updated_at": created.json()["updated_at"],
        "archived_at": None,
        "draft": {
            "title": "Chunking notes",
            "body": "Keep structural boundaries.",
            "kind": "note",
            "topic_keys": ["rag"],
            "domain_labels": ["research"],
            "experiment": None,
            "references": [],
        },
        "reference_views": [],
        "dataset_reference_view": None,
        "unavailable_reference_count": 0,
    }
    assert listed.status_code == 200
    assert listed.json() == {
        "items": [
            {
                "id": record_id,
                "title": "Chunking notes",
                "kind": "note",
                "topic_keys": ["rag"],
                "revision": 1,
                "created_at": created.json()["created_at"],
                "updated_at": created.json()["updated_at"],
                "archived_at": None,
            }
        ],
        "next_cursor": None,
    }
    assert {(item["key"], item["label"]) for item in topics.json()} == {
        ("rag", "RAG"),
        ("fine-tuning", "Fine-tuning"),
    }


def test_owner_id_in_request_is_rejected_and_never_reaches_service() -> None:
    actor_id = uuid4()
    repository = MemoryLearningRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(repository)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/learning/records",
            json={
                "title": "Title",
                "body": "Body",
                "kind": "note",
                "owner_id": str(uuid4()),
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert repository.create_calls == 0


def test_owner_id_in_update_draft_is_rejected_without_changing_record() -> None:
    actor_id = uuid4()
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Original", body="Original body", kind="note"),
    )
    repository = MemoryLearningRepository(record)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(repository)

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/learning/records/{record.id}",
            json={
                "expected_revision": 1,
                "draft": {
                    "title": "Changed",
                    "body": "Changed body",
                    "kind": "note",
                    "owner_id": str(uuid4()),
                },
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert repository.records[record.id].revision == 1
    assert repository.records[record.id].draft.title == "Original"


def test_other_owner_current_history_and_mutations_share_safe_404() -> None:
    owner_id = uuid4()
    actor_id = uuid4()
    private_target = "private-target-123"
    record = LearningRecord.create(
        owner_id=owner_id,
        draft=LearningDraft(
            title="Private title",
            body="Private body",
            kind="note",
            references=(ReferenceKey(kind="service", target=private_target),),
        ),
    )
    repository = MemoryLearningRepository(record)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(repository)
    draft = {"title": "New", "body": "New body", "kind": "note"}

    with TestClient(app) as client:
        responses = (
            client.get(f"/api/v1/learning/records/{record.id}"),
            client.get(f"/api/v1/learning/records/{record.id}/revisions/1"),
            client.put(
                f"/api/v1/learning/records/{record.id}",
                json={"expected_revision": 1, "draft": draft},
            ),
            client.post(
                f"/api/v1/learning/records/{record.id}/archive",
                json={"expected_revision": 1},
            ),
            client.post(
                f"/api/v1/learning/records/{record.id}/restore",
                json={"expected_revision": 1},
            ),
        )

    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert "Private title" not in response.text
        assert "Private body" not in response.text
        assert private_target not in response.text


def test_revoked_reference_response_does_not_disclose_stored_key_or_old_label() -> None:
    actor_id = uuid4()
    private_target = "private-target-123"
    old_label = "Old private label"
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(
            title="Visible title",
            body="Visible body",
            kind="note",
            references=(ReferenceKey(kind="service", target=private_target),),
        ),
    )

    class RevokedResolver(ReferenceResolver):
        async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
            del actor_id, key
            return ReferenceView.unavailable()

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(
        MemoryLearningRepository(record), RevokedResolver()
    )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/learning/records/{record.id}")

    assert response.status_code == 200
    assert response.json()["draft"]["references"] == []
    assert response.json()["reference_views"] == [
        {"status": "unavailable", "label": None, "href": None, "key": None}
    ]
    assert response.json()["unavailable_reference_count"] == 1
    assert private_target not in response.text
    assert old_label not in response.text


def test_historical_revoked_dataset_reference_hides_all_target_metadata() -> None:
    actor_id = uuid4()
    private_target = str(uuid4())
    private_title = "Revoked dataset title"
    private_body = "Revoked dataset body"
    private_href = "/private/datasets/revoked"
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(
            title="Visible experiment",
            body="Visible record body",
            kind="experiment",
            experiment={
                "dataset_snapshot": {
                    "kind": "rag.evaluation",
                    "target": private_target,
                }
            },
        ),
    )

    class RevokedDatasetResolver(ReferenceResolver):
        async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
            del actor_id, key
            return ReferenceView.unavailable()

    repository = MemoryLearningRepository(record)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(
        repository, RevokedDatasetResolver()
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/learning/records/{record.id}/revisions/1"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["experiment"]["dataset_snapshot"] is None
    assert payload["dataset_reference_view"] == {
        "status": "unavailable",
        "label": None,
        "href": None,
        "key": None,
    }
    assert payload["unavailable_reference_count"] == 1
    for forbidden in (private_target, private_title, private_body, private_href):
        assert forbidden not in response.text


def test_stale_revision_and_page_limit_use_safe_error_contracts() -> None:
    actor_id = uuid4()
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Title", body="Body", kind="note"),
    )
    repository = MemoryLearningRepository(record)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(repository)

    with TestClient(app) as client:
        stale = client.put(
            f"/api/v1/learning/records/{record.id}",
            json={
                "expected_revision": 99,
                "draft": {"title": "New", "body": "New body", "kind": "note"},
            },
        )
        excessive_page = client.get("/api/v1/learning/records?limit=101")

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "learning_revision_conflict"
    assert stale.json()["error"]["correlation_id"] != ""
    assert excessive_page.status_code == 422
    assert excessive_page.json()["error"]["code"] == "learning_invalid_input"


def test_stale_archive_restore_and_archived_update_keep_revisions_unchanged() -> None:
    actor_id = uuid4()
    active = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Active", body="Active body", kind="note"),
    )
    archived = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Archived", body="Archived body", kind="note"),
    ).archive(expected_revision=1)
    repository = MemoryLearningRepository(active, archived)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: learning_service(repository)

    with TestClient(app) as client:
        stale_archive = client.post(
            f"/api/v1/learning/records/{active.id}/archive",
            json={"expected_revision": 99},
        )
        stale_restore = client.post(
            f"/api/v1/learning/records/{archived.id}/restore",
            json={"expected_revision": 1},
        )
        archived_update = client.put(
            f"/api/v1/learning/records/{archived.id}",
            json={
                "expected_revision": 2,
                "draft": {"title": "Changed", "body": "Changed", "kind": "note"},
            },
        )

    assert stale_archive.status_code == 409
    assert stale_archive.json()["error"]["code"] == "learning_revision_conflict"
    assert stale_restore.status_code == 409
    assert stale_restore.json()["error"]["code"] == "learning_revision_conflict"
    assert archived_update.status_code == 409
    assert archived_update.json()["error"]["code"] == "learning_record_archived"
    assert repository.records[active.id].revision == 1
    assert repository.records[active.id].archived_at is None
    assert repository.records[archived.id].revision == 2
    assert repository.records[archived.id].archived_at is not None
    assert repository.records[archived.id].draft.title == "Archived"


def test_list_uses_runtime_default_and_accepts_only_configured_boundaries() -> None:
    actor_id = uuid4()
    repository = MemoryLearningRepository()
    service = LearningService(
        repository,
        MutableReferenceResolver(),
        LearningLimits(page_default=2, page_max=2),
        LearningCursorCodec("cursor-secret-" * 4, max_length=4096),
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(actor_id)
    app.dependency_overrides[get_learning_service] = lambda: service

    with TestClient(app) as client:
        runtime_default = client.get("/api/v1/learning/records")
        lower_boundary = client.get("/api/v1/learning/records?limit=1")
        upper_boundary = client.get("/api/v1/learning/records?limit=2")
        excessive = client.get("/api/v1/learning/records?limit=3")

    assert runtime_default.status_code == 200
    assert lower_boundary.status_code == 200
    assert upper_boundary.status_code == 200
    assert repository.list_limits == [2, 1, 2]
    assert excessive.status_code == 422
    assert excessive.json()["error"]["code"] == "learning_invalid_input"
