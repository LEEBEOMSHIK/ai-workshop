"""Administrator transport tests use fake services, never CLI or databases."""

from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_workshop.config import Settings, get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import UserRole
from tests.unit.labs.rag.deployments.test_health_api import user


class FakeAdminServices:
    def __init__(self):
        self.calls = []
        self.verification = self
        self.evidence = self

    async def status(self, **arguments):
        self.calls.append(("status", arguments))
        return SimpleNamespace(
            ready=False,
            safe_error_code="codex_verification_required",
            requested_provider_model_id="synthetic-model",
            observed_provider_model_id=None,
            model_identity_status="unknown",
            checked_at=None,
        )

    async def verify(self, **arguments):
        self.calls.append(("verify", arguments))
        return await self.status(**arguments)

    async def list_evidence(self, **arguments):
        self.calls.append(("list", arguments))
        return ()

    async def approve(self, **arguments):
        self.calls.append(("approve", arguments))

    async def revoke(self, **arguments):
        self.calls.append(("revoke", arguments))


def api_fixture(role=UserRole.OWNER):
    name = "ai_workshop.labs.rag.generation.codex_admin_api"
    assert find_spec(name) is not None, "Codex administrator transport is missing"
    module = import_module(name)
    app = create_app()
    services = FakeAdminServices()
    app.dependency_overrides[get_current_user] = lambda: user(role)
    app.dependency_overrides[get_settings] = lambda: Settings(
        secret_key="x" * 32, codex_allowed_admin_origins=("https://codex.example",), _env_file=None
    )
    app.dependency_overrides[module.get_codex_services] = lambda: services
    return app, services, module


HEADERS = {"origin": "https://codex.example", "x-codex-request": "1"}


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_evidence_mutation_requires_generation_and_idempotency_key(method):
    app, services, _ = api_fixture()
    body = {"classification": "synthetic", "content_sha256": "a" * 64} if method == "POST" else {}
    with TestClient(app) as client:
        response = client.request(
            method,
            f"/api/v1/admin/rag/codex-evidence/{uuid4()}/approval",
            json=body,
            headers=HEADERS,
        )
    assert response.status_code == 422
    assert services.calls == []


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_generation", True),
        ("expected_generation", -1),
        ("expected_generation", "1"),
        ("actor_id", str(uuid4())),
        ("provider", "external"),
    ],
)
def test_evidence_mutation_rejects_coercion_and_client_authority(method, field, value):
    app, services, _ = api_fixture()
    body = {"expected_generation": 1, "request_id": str(uuid4())}
    if method == "POST":
        body.update(classification="public", content_sha256="a" * 64)
    body[field] = value
    with TestClient(app) as client:
        response = client.request(
            method,
            f"/api/v1/admin/rag/codex-evidence/{uuid4()}/approval",
            json=body,
            headers=HEADERS,
        )
    assert response.status_code == 422 and services.calls == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "POST",
            "configuration-versions/{}/codex-verify",
            {"consented": True, "disclosure_version": "codex-external-generation-v1"},
        ),
        (
            "POST",
            "codex-evidence/{}/approval",
            {"classification": "synthetic", "content_sha256": "a" * 64},
        ),
        ("DELETE", "codex-evidence/{}/approval", {}),
    ],
)
@pytest.mark.parametrize(
    "guard", ["missing_origin", "wrong_origin", "missing_header", "wrong_header", "media"]
)
def test_all_codex_mutations_require_exact_origin_header_and_json(method, path, body, guard):
    app, services, _ = api_fixture()
    headers = dict(HEADERS)
    if guard == "missing_origin":
        headers.pop("origin")
    elif guard == "wrong_origin":
        headers["origin"] = "https://attacker.example"
    elif guard == "missing_header":
        headers.pop("x-codex-request")
    elif guard == "wrong_header":
        headers["x-codex-request"] = "0"
    else:
        headers["content-type"] = "text/plain"
    with TestClient(app) as client:
        response = client.request(
            method, "/api/v1/admin/rag/" + path.format(uuid4()), json=body, headers=headers
        )
    assert response.status_code in (403, 415)
    assert services.calls == []


def test_passive_status_uses_actual_actor_exact_config_and_never_verifies():
    app, services, _ = api_fixture()
    config_id = uuid4()
    with TestClient(app) as client:
        response = client.get(f"/api/v1/admin/rag/configuration-versions/{config_id}/codex-status")
    assert response.status_code == 200 and response.json()["model_identity_status"] == "unknown"
    assert services.calls == [
        ("status", {"actor_id": user(UserRole.OWNER).id, "configuration_version_id": config_id})
    ]


@pytest.mark.parametrize(
    "path",
    ["configuration-versions/{}/codex-status", "codex-evidence?workspace_id={}", "codex-runners"],
)
def test_passive_endpoints_remain_owner_only(path):
    app, services, _ = api_fixture(UserRole.MEMBER)
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rag/" + path.format(uuid4()))
    assert response.status_code == 403 and not services.calls


@pytest.mark.parametrize(
    "body",
    [
        {"classification": "private", "consented": True, "disclosure_version": "version"},
        {"classification": "public", "consented": 1, "disclosure_version": "version"},
        {
            "classification": "public",
            "consented": True,
            "disclosure_version": "version",
            "extra": True,
        },
    ],
)
def test_input_attestation_is_closed_and_strict(body):
    _, _, module = api_fixture()
    with pytest.raises(ValidationError):
        module.CodexInputApprovalRequest.model_validate(body)


async def test_generation_readiness_requires_actual_actor_and_exact_saved_profile_binding():
    from ai_workshop.labs.rag.generation.readiness import SqlAlchemyGenerationReadiness
    from tests.unit.labs.rag.deployments.test_domain import codex_deployment

    actor_id, config_id, profile_id = uuid4(), uuid4(), uuid4()
    deployment = codex_deployment()
    calls = []

    class Profiles:
        async def find_profile(self, identifier):
            return SimpleNamespace(bindings=(), deployment_version_id=deployment.id)

        async def find_version_visible(self, identifier, actor):
            assert actor == actor_id
            return (
                SimpleNamespace(generation_profile_id=profile_id)
                if identifier == config_id
                else None
            )

    class Deployments:
        async def get_version(self, identifier):
            return deployment

    class Proof:
        async def status(self, **arguments):
            calls.append(arguments)
            return SimpleNamespace(ready=True)

    settings = Settings(secret_key="x" * 32, _env_file=None)
    service = SqlAlchemyGenerationReadiness(
        object(), settings, actor_id=actor_id, verification=Proof()
    )
    service.profiles, service.deployments = Profiles(), Deployments()
    assert not await service.is_ready(profile_id)
    assert not await service.is_ready(profile_id, configuration_version_id=uuid4())
    assert not await service.is_ready(uuid4(), configuration_version_id=config_id)
    assert calls == []
    assert await service.is_ready(profile_id, configuration_version_id=config_id)
    assert calls == [{"actor_id": actor_id, "configuration_version_id": config_id}]
    service.actor_id = None
    assert not await service.is_ready(profile_id, configuration_version_id=config_id)
    assert len(calls) == 1


def test_configuration_dependency_propagates_authenticated_actor_not_configuration_owner():
    from inspect import signature
    from typing import get_type_hints

    from ai_workshop.labs.rag.configurations.api import get_rag_configuration_service

    parameters = signature(get_rag_configuration_service).parameters
    assert "user" in parameters
    metadata = get_type_hints(get_rag_configuration_service, include_extras=True)[
        "user"
    ].__metadata__
    assert metadata[0].dependency is get_current_user
    actor = user(UserRole.MEMBER)
    service = get_rag_configuration_service(
        object(), Settings(secret_key="x" * 32, _env_file=None), actor
    )
    assert service.generation_readiness.actor_id == actor.id


async def test_codex_registration_uses_typed_preflight_but_never_health_or_secrets():
    from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
    from ai_workshop.labs.rag.deployments.service import DeploymentRegistryService
    from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind
    from tests.unit.labs.rag.generation.test_codex_execution import FakeRegistry, request_fixture

    _, generation = request_fixture()
    deployment = generation.profile.deployment
    model = ModelDefinition.create(
        kind=ModelKind.LLM,
        name="Synthetic",
        version=1,
        config={"model_identifier": deployment.provider_model_id},
    )
    calls = []

    class Repository:
        async def get_model_definition(self, identifier):
            calls.append("model")
            return model

        async def create_identity(self, *args, **kwargs):
            calls.append("identity")

        async def add_version(self, value):
            calls.append("version")

    request = DeploymentVersionCreate.model_validate(
        {name: getattr(deployment, name) for name in DeploymentVersionCreate.model_fields}
    )
    service = DeploymentRegistryService(
        Repository(),
        endpoint_refs={},
        secret_refs={},
        codex_registry=FakeRegistry(),
        environment="test",
    )
    entry = await service.create_identity(request, actor_id=user(UserRole.OWNER).id)
    assert calls == ["model", "identity", "version"]
    assert entry.deployment.endpoint_ref is None and entry.deployment.secret_ref is None
    assert entry.deployment.healthcheck_enabled is False


async def test_codex_deployment_health_without_exact_configuration_stays_passive():
    from ai_workshop.labs.rag.deployments.service import DeploymentHealthService
    from tests.unit.labs.rag.deployments.test_domain import codex_deployment
    from tests.unit.labs.rag.deployments.test_health_service import MemoryRepository

    deployment = codex_deployment()
    repository = MemoryRepository(deployment)
    service = DeploymentHealthService(repository, object(), object())
    result = await service.check(deployment.id, actor_id=user(UserRole.OWNER).id)
    assert result.status == "pending"
    assert result.safe_error_code == "codex_configuration_verification_required"
    assert result.observed_provider_model_id is None
    assert not repository.health_checks


def test_explicit_verify_and_evidence_mutations_preserve_exact_payload_and_actor():
    app, services, _ = api_fixture()
    config_id, revision_id = uuid4(), uuid4()
    approval_request, revocation_request = uuid4(), uuid4()
    with TestClient(app) as client:
        verify = client.post(
            f"/api/v1/admin/rag/configuration-versions/{config_id}/codex-verify",
            json={"consented": True, "disclosure_version": "codex-external-generation-v1"},
            headers=HEADERS,
        )
        approve = client.post(
            f"/api/v1/admin/rag/codex-evidence/{revision_id}/approval",
            json={
                "classification": "public",
                "content_sha256": "c" * 64,
                "expected_generation": 0,
                "request_id": str(approval_request),
            },
            headers=HEADERS,
        )
        revoke = client.request(
            "DELETE",
            f"/api/v1/admin/rag/codex-evidence/{revision_id}/approval",
            json={"expected_generation": 1, "request_id": str(revocation_request)},
            headers=HEADERS,
        )
    assert (verify.status_code, approve.status_code, revoke.status_code) == (200, 204, 204)
    assert services.calls[0] == (
        "verify",
        {
            "actor_id": user(UserRole.OWNER).id,
            "configuration_version_id": config_id,
            "consented": True,
            "disclosure_version": "codex-external-generation-v1",
        },
    )
    assert services.calls[2][0] == "approve"
    assert services.calls[2][1]["content_sha256"] == "c" * 64
    assert services.calls[2][1]["revision_id"] == revision_id
    assert services.calls[2][1]["expected_generation"] == 0
    assert services.calls[2][1]["request_id"] == approval_request
    assert services.calls[3] == (
        "revoke",
        {
            "actor_id": user(UserRole.OWNER).id,
            "revision_id": revision_id,
            "expected_generation": 1,
            "request_id": revocation_request,
        },
    )


def test_safe_runner_metadata_contains_prompts_limits_and_no_host_or_auth_paths(
    monkeypatch, tmp_path
):
    from ai_workshop.labs.rag.generation.codex_runner_registry import CodexRunnerSettings
    from tests.unit.labs.rag.generation.test_codex_execution import FakeRegistry

    app, services, module = api_fixture()
    settings = Settings(
        secret_key="x" * 32,
        _env_file=None,
        codex_runner_refs={
            "codex-cli-verified": CodexRunnerSettings(
                executable=tmp_path / "synthetic.exe",
                request_root=tmp_path / "requests",
                executable_sha256="a" * 64,
                expected_cli_version="1.2.3",
            )
        },
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(module, "codex_registry", lambda settings: FakeRegistry())
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rag/codex-runners")
    assert response.status_code == 200 and not services.calls
    item = response.json()[0]
    assert item["local_preflight_passed"] and item["limits"]["max_concurrent"] == 1
    assert item["prompt_options"][0]["answer_ref"] == "rag-codex-answer-v3"
    assert item["prompt_options"][0]["control_text"]
    assert str(tmp_path) not in response.text and "executable" not in response.text


@pytest.mark.parametrize("path", ["deployments", "deployments/{}/versions"])
def test_codex_registration_requires_mutation_guard_before_registry_write(path):
    from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
    from ai_workshop.labs.rag.deployments.service import get_deployment_registry_service
    from tests.unit.labs.rag.generation.test_codex_execution import request_fixture

    app, _, _ = api_fixture()
    _, request = request_fixture()
    deployment = request.profile.deployment
    body = DeploymentVersionCreate.model_validate(
        {name: getattr(deployment, name) for name in DeploymentVersionCreate.model_fields}
    ).model_dump(mode="json")
    app.dependency_overrides[get_deployment_registry_service] = lambda: object()
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/rag/" + path.format(uuid4()), json=body)
    assert response.status_code == 403


def test_verification_storage_failure_is_safe_and_never_reports_ready():
    app, services, _ = api_fixture()

    async def unavailable(**arguments):
        raise RuntimeError("synthetic private diagnostic canary")

    services.status = unavailable
    with TestClient(app) as client:
        response = client.get(f"/api/v1/admin/rag/configuration-versions/{uuid4()}/codex-status")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "codex_verification_unavailable"
    assert "canary" not in response.text
