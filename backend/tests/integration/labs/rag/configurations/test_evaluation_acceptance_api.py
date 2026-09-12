from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import EvaluationAcceptanceResult
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.service import AuthService, get_auth_service
from ai_workshop.shared.errors import AppError
from tests.integration.labs.rag.configurations.test_configuration_api import (
    ACTOR_ID,
    FakeConfigurationService,
    _client,
    _configuration,
    member,
)


class AcceptanceService(FakeConfigurationService):
    def __init__(self, *, fail=False):
        super().__init__([_configuration()])
        self.run_id, self.policy_id = uuid4(), uuid4()
        self.calls = []
        self.fail = fail

    async def accept_evaluation(self, configuration_id, version_id, evaluation_run_id, actor_id):
        self.calls.append((configuration_id, version_id, evaluation_run_id, actor_id))
        assert self.calls[-1] == (
            self.configurations[0].id,
            self.configurations[0].version_id,
            self.run_id,
            ACTOR_ID,
        )
        if self.fail:
            raise AppError(
                "evaluation_policy_required", "The selected evaluation must qualify.", 409
            )
        return EvaluationAcceptanceResult(
            replace(self.configurations[0], evaluation_state=EvaluationState.PASSED),
            self.run_id,
            self.policy_id,
        )


def route(service):
    config = service.configurations[0]
    return (
        f"/api/v1/rag/configurations/{config.id}/versions/{config.version_id}/evaluation-acceptance"
    )


def test_owner_acceptance_returns_exact_evidence_with_passive_readiness():
    service = AcceptanceService()
    response = _client(service).post(
        route(service), json={"evaluation_run_id": str(service.run_id)}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evaluation_run_id"] == str(service.run_id)
    assert data["evaluation_policy_version_id"] == str(service.policy_id)
    assert data["configuration"]["version_id"] == str(service.configurations[0].version_id)
    assert data["configuration"]["evaluation_state"] == "passed"
    assert data["configuration"]["is_default"] is False
    assert data["configuration"]["service_ready"] is False
    assert data["configuration"]["answer_ready"] is False


@pytest.mark.parametrize("actor", ["member", "anonymous"])
def test_acceptance_is_owner_only(actor):
    service = AcceptanceService()
    client = _client(service)
    if actor == "member":
        client.app.dependency_overrides[get_current_user] = member
    else:
        client.app.dependency_overrides.pop(get_current_user)
        client.app.dependency_overrides[get_auth_service] = lambda: AuthService(
            object(), object(), object()
        )
    response = client.post(route(service), json={"evaluation_run_id": str(service.run_id)})
    assert response.status_code == (403 if actor == "member" else 401)
    assert service.calls == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"evaluation_run_id": "invalid"}, {"is_default": True}, {"evaluation_state": "passed"}],
)
def test_acceptance_rejects_missing_invalid_or_extra_fields(payload):
    service = AcceptanceService()
    if "evaluation_run_id" not in payload and payload:
        payload = {"evaluation_run_id": str(service.run_id), **payload}
    response = _client(service).post(route(service), json=payload)
    assert response.status_code == 422
    assert service.calls == []


def test_acceptance_conflict_keeps_safe_error_contract():
    service = AcceptanceService(fail=True)
    response = _client(service).post(
        route(service), json={"evaluation_run_id": str(service.run_id)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "evaluation_policy_required"
