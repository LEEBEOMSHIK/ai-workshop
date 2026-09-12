from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.service import AuthService, get_auth_service
from tests.integration.labs.rag.evaluation.test_evaluation_api import (
    FakeEvaluationService,
    member,
    owner,
)
from tests.unit.labs.rag.evaluation.test_authoring import context_and_request


class Service:
    def __init__(self):
        self.context, self.request = context_and_request()
        self.context = replace(self.context, actor_id=owner().id)
        self.calls = []
        self.result = FakeEvaluationService().run

    async def documents(self, actor, request):
        from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringDocumentsResponse

        self.calls.append((actor, request))
        return AuthoringDocumentsResponse(documents=(), next_cursor=None)

    async def preview(self, actor, request):
        self.calls.append((actor, request))
        return self.context.preview()

    async def run(self, actor, request):
        self.calls.append((actor, request))
        return self.result


def client_and_payload(endpoint, actor="owner"):
    from ai_workshop.labs.rag.evaluation.authoring_api import get_authoring_service

    service = Service()
    app = create_app()
    app.dependency_overrides[get_authoring_service] = lambda: service
    if actor != "anonymous":
        app.dependency_overrides[get_current_user] = owner if actor == "owner" else member
    else:
        app.dependency_overrides[get_auth_service] = lambda: AuthService(
            object(), object(), object()
        )
    payload = service.context.scope.model_dump(mode="json")
    if endpoint == "documents":
        payload.pop("asset_version_ids")
    if endpoint == "runs":
        payload = service.request.model_dump(mode="json")
    return TestClient(app), service, payload


@pytest.mark.parametrize("endpoint", ["documents", "preview", "runs"])
def test_owner_authoring_routes_forward_actual_actor_and_exact_typed_request(endpoint):
    client, service, payload = client_and_payload(endpoint)
    response = client.post(f"/api/v1/rag/evaluation-authoring/{endpoint}", json=payload)
    assert response.status_code == (202 if endpoint == "runs" else 200)
    assert service.calls[0][0] == owner().id
    if endpoint != "runs":
        assert response.headers["Cache-Control"] == "no-store"
    else:
        assert response.json()["id"] == str(service.result.id)


@pytest.mark.parametrize("endpoint", ["documents", "preview", "runs"])
@pytest.mark.parametrize("actor,status", [("member", 403), ("anonymous", 401)])
def test_authoring_owner_gate_precedes_service(endpoint, actor, status):
    client, service, payload = client_and_payload(endpoint, actor)
    response = client.post(f"/api/v1/rag/evaluation-authoring/{endpoint}", json=payload)
    assert response.status_code == status
    assert not service.calls


@pytest.mark.parametrize("endpoint", ["documents", "preview", "runs"])
def test_authoring_rejects_caller_universe_or_private_snapshot_fields(endpoint):
    client, service, payload = client_and_payload(endpoint)
    payload["authorized_source_ids"] = []
    response = client.post(f"/api/v1/rag/evaluation-authoring/{endpoint}", json=payload)
    assert response.status_code == 422
    assert not service.calls
