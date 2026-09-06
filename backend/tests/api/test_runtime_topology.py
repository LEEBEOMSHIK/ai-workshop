from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from ai_workshop.main import create_app
from ai_workshop.platform.identity import api as identity_api
from ai_workshop.platform.identity.domain import User, UserRole


def make_user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        display_name=role.value.title(),
        email=f"{role.value}@example.com",
        normalized_email=f"{role.value}@example.com",
        password_hash="hash",
        role=role,
    )


def walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def client_for(user: User) -> TestClient:
    application = create_app()
    application.dependency_overrides[identity_api.get_current_user] = lambda: user
    return TestClient(application)


def test_owner_reads_allowlisted_runtime_topology() -> None:
    with client_for(make_user(UserRole.OWNER)) as client:
        response = client.get("/api/v1/admin/system/runtime-topology")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "topology_version",
        "environment_kind",
        "nodes",
        "storages",
        "compatibility",
    }
    assert set(payload["nodes"][0]) == {
        "id",
        "display_name",
        "kind",
        "runtime_target",
        "process_role",
        "dependencies",
        "storages",
        "capabilities",
        "activation",
        "healthcheck_declared",
        "observation",
    }
    assert set(payload["compatibility"][0]) == {
        "id",
        "display_name",
        "device",
        "runtime_target",
        "verification_state",
        "verification_note",
    }
    assert not {
        "container_id",
        "database_url",
        "endpoint",
        "environment",
        "host_path",
        "password",
        "port",
        "secret",
    }.intersection(walk_keys(payload))


def test_member_cannot_read_runtime_topology() -> None:
    member = make_user(UserRole("member"))

    with client_for(member) as client:
        response = client.get("/api/v1/admin/system/runtime-topology")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "owner_required"
