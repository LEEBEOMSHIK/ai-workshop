from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.publishing.package import PublicPersona, StudyContent, StudySnapshot
from ai_workshop.platform.publishing.service import PublishingService
from ai_workshop.public_app import create_public_app
from ai_workshop.publishing_composition import get_publishing_service
from ai_workshop.shared.errors import AppError
from tests.unit.platform.publishing.test_service import (
    MemoryPublishingRepository,
    MutableDelivery,
    service_for,
)

MUTATION_HEADERS = {
    "Origin": "http://localhost:5173",
    "X-Publishing-Request": "1",
}


def user(user_id: UUID, role: UserRole = UserRole.OWNER) -> User:
    return User(
        id=user_id,
        display_name="Publishing user",
        email="publishing@example.test",
        normalized_email="publishing@example.test",
        password_hash="fixture-hash",
        role=role,
    )


def content(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "slug": "example-study",
        "title": "Example study",
        "summary": "Public summary.",
        "topic_keys": ["rag"],
        "body": "Public body.",
        "verification": "Fixture verification.",
        "limitations": "Synthetic only.",
        "persona": None,
    }
    values.update(changes)
    return values


def configured_settings() -> Settings:
    return Settings(
        secret_key="x" * 32,
        publishing_approved_public_personas=(
            PublicPersona(slug="reviewer", label="Approved reviewer"),
        ),
        _env_file=None,
    )


def client_for(service: PublishingService, actor: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_publishing_service] = lambda: service
    app.dependency_overrides[get_settings] = configured_settings
    return TestClient(app)


class ExplodingListRepository(MemoryPublishingRepository):
    async def list(self, *, offset: int, limit: int):
        del offset, limit
        raise RuntimeError("private-admin-repository-marker")


class StaticPublicReader:
    def __init__(self, snapshot: StudySnapshot) -> None:
        self.snapshot = snapshot

    def get(self, slug: str) -> StudySnapshot:
        assert slug == self.snapshot.content.slug
        return self.snapshot

    def list_published(self, topic_key: str | None = None) -> tuple[StudySnapshot, ...]:
        del topic_key
        return (self.snapshot,)


def test_anonymous_and_member_cannot_resolve_publishing_service() -> None:
    service_calls = 0

    def service_override() -> PublishingService:
        nonlocal service_calls
        service_calls += 1
        return service_for(MemoryPublishingRepository(), MutableDelivery())

    app = create_app()
    app.dependency_overrides[get_publishing_service] = service_override
    async def anonymous_user() -> User:
        raise AppError("not_authenticated", "Authentication is required.", 401)

    app.dependency_overrides[get_current_user] = anonymous_user
    with TestClient(app) as client:
        anonymous = client.get("/api/v1/admin/publishing/studies")

    app.dependency_overrides[get_current_user] = lambda: user(
        uuid4(), UserRole.MEMBER
    )
    with TestClient(app) as client:
        member = client.get("/api/v1/admin/publishing/studies")

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "not_authenticated"
    assert member.status_code == 403
    assert member.json()["error"]["code"] == "owner_required"
    assert service_calls == 0
    assert anonymous.headers["cache-control"] == "no-store"
    assert member.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["offset=-1", "limit=101"])
def test_list_pagination_is_bounded_before_repository_io(query: str) -> None:
    repository = MemoryPublishingRepository()
    with client_for(service_for(repository, MutableDelivery()), user(uuid4())) as client:
        response = client.get(f"/api/v1/admin/publishing/studies?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {
        "publishing_invalid_input",
        "validation_error",
    }
    assert repository.studies == {}


def test_admin_unexpected_repository_error_is_safe_and_no_store() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(uuid4())
    app.dependency_overrides[get_publishing_service] = lambda: service_for(
        ExplodingListRepository(),
        MutableDelivery(),
    )
    app.dependency_overrides[get_settings] = configured_settings

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/admin/publishing/studies")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert response.headers["cache-control"] == "no-store"
    assert "private-admin-repository-marker" not in response.text


@pytest.mark.parametrize(
    ("headers", "send_json", "expected_status"),
    [
        ({"X-Publishing-Request": "1"}, True, 403),
        ({"Origin": "null", "X-Publishing-Request": "1"}, True, 403),
        ({"Origin": "https://hostile.example", "X-Publishing-Request": "1"}, True, 403),
        ({"Origin": "http://localhost:5173"}, True, 403),
        (MUTATION_HEADERS, False, 415),
    ],
)
def test_mutations_require_exact_csrf_and_json_contract(
    headers: dict[str, str],
    send_json: bool,
    expected_status: int,
) -> None:
    repository = MemoryPublishingRepository()
    with client_for(service_for(repository, MutableDelivery()), user(uuid4())) as client:
        if send_json:
            response = client.post(
                "/api/v1/admin/publishing/studies",
                headers=headers,
                json={"content": content()},
            )
        else:
            response = client.post(
                "/api/v1/admin/publishing/studies",
                headers={**headers, "Content-Type": "text/plain"},
                content="not-json",
            )

    assert response.status_code == expected_status
    assert repository.create_calls == 0
    assert response.headers["cache-control"] == "no-store"


def test_owner_crud_preview_personas_and_publish_contract() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    service = service_for(
        repository,
        delivery,
        personas=(PublicPersona(slug="reviewer", label="Approved reviewer"),),
    )
    with client_for(service, user(uuid4())) as client:
        created = client.post(
            "/api/v1/admin/publishing/studies",
            headers=MUTATION_HEADERS,
            json={
                "content": content(
                    persona={"slug": "reviewer", "label": "Approved reviewer"}
                )
            },
        )
        listed = client.get("/api/v1/admin/publishing/studies")
        detail = client.get("/api/v1/admin/publishing/studies/example-study")
        preview = client.get(
            "/api/v1/admin/publishing/studies/example-study/preview"
        )
        personas = client.get("/api/v1/admin/publishing/personas")
        published = client.post(
            "/api/v1/admin/publishing/studies/example-study/publish",
            headers=MUTATION_HEADERS,
            json={
                "expected_revision": 1,
                "expected_digest": preview.json()["digest"],
                "request_id": "publish-one",
            },
        )

    expected_initial = {
        "snapshot": created.json()["snapshot"],
        "digest": created.json()["digest"],
        "sequence": 0,
        "approved_digest": None,
        "desired_action": None,
        "applied_sequence": 0,
        "applied_action": None,
        "applied_revision": None,
        "delivery_pending": False,
        "pending_command": None,
        "last_request_id": None,
        "delivery_error_code": None,
    }
    assert created.status_code == 201
    assert created.json() == expected_initial
    assert listed.json() == {"items": [expected_initial]}
    assert detail.json() == expected_initial
    assert preview.json() == {
        "snapshot": expected_initial["snapshot"],
        "digest": expected_initial["digest"],
    }
    assert personas.json() == {
        "items": [{"slug": "reviewer", "label": "Approved reviewer"}]
    }
    assert published.status_code == 200
    assert published.json()["desired_action"] == "publish"
    assert published.json()["applied_action"] == "publish"
    assert published.json()["delivery_pending"] is False
    assert published.json()["pending_command"] is None
    assert published.json()["last_request_id"] == "publish-one"
    for response in (created, listed, detail, preview, personas, published):
        assert response.headers["cache-control"] == "no-store"


def test_stale_update_and_private_fields_are_rejected_without_mutation() -> None:
    repository = MemoryPublishingRepository()
    service = service_for(repository, MutableDelivery())
    with client_for(service, user(uuid4())) as client:
        created = client.post(
            "/api/v1/admin/publishing/studies",
            headers=MUTATION_HEADERS,
            json={"content": content()},
        )
        stale = client.put(
            "/api/v1/admin/publishing/studies/example-study",
            headers=MUTATION_HEADERS,
            json={"expected_revision": 99, "content": content(title="Changed")},
        )
        leaked = client.put(
            "/api/v1/admin/publishing/studies/example-study",
            headers=MUTATION_HEADERS,
            json={
                "expected_revision": 1,
                "content": content(source_path="C:/private/marker.md"),
            },
        )

    assert created.status_code == 201
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "publishing_revision_conflict"
    assert leaked.status_code == 422
    assert leaked.json()["error"]["code"] == "validation_error"
    assert "C:/private/marker.md" not in leaked.text
    assert repository.studies["example-study"].snapshot.revision == 1


def test_delivery_failure_returns_safe_pending_state() -> None:
    repository = MemoryPublishingRepository()
    delivery = MutableDelivery()
    delivery.error = AppError(
        "publishing_store_unavailable",
        "The public study store is unavailable.",
        503,
    )
    service = service_for(repository, delivery)
    with client_for(service, user(uuid4())) as client:
        created = client.post(
            "/api/v1/admin/publishing/studies",
            headers=MUTATION_HEADERS,
            json={"content": content()},
        )
        response = client.post(
            "/api/v1/admin/publishing/studies/example-study/publish",
            headers=MUTATION_HEADERS,
            json={
                "expected_revision": 1,
                "expected_digest": created.json()["digest"],
                "request_id": "pending-request",
            },
        )

    assert response.status_code == 200
    assert response.json()["delivery_pending"] is True
    assert response.json()["applied_action"] is None
    assert response.json()["delivery_error_code"] == "publishing_store_unavailable"
    assert response.json()["pending_command"] == {
        "action": "publish",
        "expected_revision": 1,
        "expected_digest": created.json()["digest"],
        "request_id": "pending-request",
    }


def test_public_study_response_excludes_pending_command_metadata() -> None:
    snapshot = StudySnapshot(
        revision=1,
        content=StudyContent.model_validate(content()),
    )
    app = create_public_app(reader=StaticPublicReader(snapshot))  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/api/public/studies/example-study")

    assert response.status_code == 200
    assert response.json() == snapshot.model_dump(mode="json")
    for private_field in (
        "pending_command",
        "request_id",
        "expected_digest",
        "expected_revision",
    ):
        assert private_field not in response.text
