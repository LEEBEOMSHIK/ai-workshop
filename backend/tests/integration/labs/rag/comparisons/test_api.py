from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.comparisons.api import get_service
from ai_workshop.labs.rag.comparisons.schemas import MAX_IMPORT_BYTES
from ai_workshop.labs.rag.comparisons.service import ComparisonService
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.comparisons.support import payload
from tests.unit.labs.rag.comparisons.test_service import ACTOR, MemoryStore

PATH = "/api/v1/admin/rag/comparisons"
HEADERS = {"Origin": "http://testserver", "X-Comparison-Request": "1"}


def actor(role: UserRole = UserRole.OWNER) -> User:
    return User(
        id=ACTOR,
        email="owner@example.test",
        normalized_email="owner@example.test",
        display_name="Synthetic owner",
        password_hash="unused",
        role=role,
    )


class Session:
    async def commit(self) -> None:
        pass


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    store = MemoryStore()
    app.dependency_overrides[get_service] = lambda: ComparisonService(store, store)
    app.dependency_overrides[get_session] = lambda: Session()
    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        secret_key="synthetic-comparison-test-key-only",
        publishing_allowed_admin_origins=["http://testserver"],
    )
    with TestClient(app) as instance:
        yield instance


def test_import_list_detail_and_duplicate_preserve_the_record(client: TestClient) -> None:
    response = client.post(PATH, headers=HEADERS, json=payload())
    assert response.status_code == 200
    detail = response.json()
    assert detail["record_kind"] == "imported_comparison"
    assert detail["report"]["requests"][0]["answer"] == payload()["requests"][0]["answer"]
    assert response.headers["cache-control"] == "no-store"
    duplicate = client.post(PATH, headers=HEADERS, json=payload())
    assert duplicate.json()["id"] == detail["id"]
    assert len(client.get(PATH).json()["items"]) == 1
    assert client.get(f"{PATH}/{detail['id']}").json() == detail


def test_mutation_marker_and_origin_are_required(client: TestClient) -> None:
    for headers in (
        {},
        {"Origin": "http://evil.test", "X-Comparison-Request": "1"},
        {"Origin": "http://testserver"},
    ):
        response = client.post(PATH, headers=headers, json=payload())
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
    assert client.get(PATH).json()["items"] == []


def test_errors_do_not_echo_import_body_and_are_uncacheable(client: TestClient) -> None:
    data = payload()
    data["api_key"] = "synthetic-secret-never-echo"
    response = client.post(PATH, headers=HEADERS, json=data)
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"
    response = client.get(f"{PATH}/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_oversized_invalid_json_is_rejected_before_parsing(client: TestClient) -> None:
    response = client.post(
        PATH,
        headers={**HEADERS, "Content-Type": "application/json"},
        content=b"x" * (MAX_IMPORT_BYTES + 1),
    )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"


def test_non_owner_and_missing_auth_cannot_read_or_import(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: actor(UserRole.MEMBER)
    assert client.get(PATH).status_code == 403
    assert client.post(PATH, headers=HEADERS, json=payload()).status_code == 403

    def unauthenticated() -> User:
        raise AppError("authentication_required", "Sign in.", 401)

    client.app.dependency_overrides[get_current_user] = unauthenticated
    assert client.get(PATH).status_code == 401
    assert client.post(PATH, headers=HEADERS, json=payload()).status_code == 401
