from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)
from ai_workshop.labs.rag.models.repository import ModelRegistryRepository
from ai_workshop.labs.rag.models.service import (
    RagModelRegistryService,
    get_rag_model_registry_service,
)
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole


class MemoryRegistryRepository(ModelRegistryRepository):
    def __init__(self) -> None:
        self.models: list[ModelDefinition] = []
        self.profiles: list[Profile] = []
        self.deployments: dict[UUID, ModelDeploymentVersion] = {}

    async def model_version_exists(self, kind: ModelKind, name: str, version: int) -> bool:
        return any(
            (item.kind, item.name, item.version) == (kind, name, version)
            for item in self.models
        )

    async def add_model(self, model: ModelDefinition) -> ModelDefinition:
        self.models.append(model)
        return model

    async def list_models(self) -> list[ModelDefinition]:
        return list(self.models)

    async def find_models(self, model_ids: tuple[UUID, ...]) -> list[ModelDefinition]:
        return [item for item in self.models if item.id in model_ids]

    async def find_deployment_version(
        self, deployment_version_id: UUID
    ) -> ModelDeploymentVersion | None:
        return self.deployments.get(deployment_version_id)

    async def profile_version_exists(
        self, kind: ProfileKind, name: str, version: int
    ) -> bool:
        return any(
            (item.kind, item.name, item.version) == (kind, name, version)
            for item in self.profiles
        )

    async def add_profile(self, profile: Profile) -> Profile:
        self.profiles.append(profile)
        return profile

    async def list_profiles(self, kind: ProfileKind | None = None) -> list[Profile]:
        return [item for item in self.profiles if kind is None or item.kind is kind]

    async def find_profile(self, profile_id: UUID) -> Profile | None:
        return next((item for item in self.profiles if item.id == profile_id), None)

    async def set_default(self, profile: Profile) -> Profile:
        self.profiles = [
            Profile(
                item.id,
                item.kind,
                item.name,
                item.version,
                item.config,
                item.bindings,
                item.evaluation_state,
                item.id == profile.id,
                item.deployment_version_id,
            )
            if item.kind is profile.kind
            else item
            for item in self.profiles
        ]
        return next(item for item in self.profiles if item.id == profile.id)


def owner() -> User:
    return User(
        id=uuid4(),
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def member() -> User:
    return User(
        id=uuid4(),
        display_name="Member",
        email="member@example.com",
        normalized_email="member@example.com",
        password_hash="hash",
        role=UserRole.MEMBER,
    )


def test_model_and_profile_versions_are_registered_and_listed() -> None:
    repository = MemoryRegistryRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_model_registry_service] = lambda: RagModelRegistryService(
        repository
    )

    with TestClient(app) as client:
        model_response = client.post(
            "/api/v1/admin/rag/models",
            json={
                "kind": "embedding",
                "name": "embedding-baseline",
                "version": 1,
                "config": {"dimension": 768, "token_env": "EMBEDDING_TOKEN"},
            },
        )
        model_id = model_response.json()["id"]
        profile_response = client.post(
            "/api/v1/admin/rag/profiles/indexing",
            json={
                "name": "indexing-baseline",
                "version": 1,
                "config": {"chunker": {"name": "structure", "version": 1}},
                "bindings": [{"role": "embedding", "model_id": model_id}],
                "evaluation_state": "draft",
            },
        )
        models = client.get("/api/v1/rag/models")
        profiles = client.get("/api/v1/rag/profiles/indexing")

    assert model_response.status_code == 201
    assert profile_response.status_code == 201
    assert models.json()[0]["config"] == {
        "dimension": 768,
        "token_env": "EMBEDDING_TOKEN",
    }
    assert profiles.json()[0]["bindings"] == [
        {"role": "embedding", "model_id": model_id}
    ]
    assert profiles.json()[0]["is_default"] is False


def test_unpassed_profile_cannot_be_promoted_to_default() -> None:
    repository = MemoryRegistryRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_model_registry_service] = lambda: RagModelRegistryService(
        repository
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/rag/profiles/retrieval",
            json={
                "name": "bm25-baseline",
                "version": 1,
                "config": {"bm25": {"analyzer": "standard"}},
                "bindings": [],
                "evaluation_state": "draft",
            },
        )
        promoted = client.post(
            f"/api/v1/admin/rag/profiles/{created.json()['id']}/default"
        )

    assert created.status_code == 201
    assert promoted.status_code == 409
    assert promoted.json()["error"]["code"] == "profile_not_evaluated"


@pytest.mark.parametrize(
    "route",
    [
        "/api/v1/admin/rag/profiles/{profile_id}/default",
        "/api/v1/rag/profiles/{profile_id}/default",
    ],
)
def test_both_profile_apis_reject_legacy_default_promotion(route: str) -> None:
    repository = MemoryRegistryRepository()
    current_default = Profile(
        id=uuid4(),
        kind=ProfileKind.GENERATION,
        name="deployment-bound-default",
        version=2,
        config={},
        bindings=(),
        evaluation_state=EvaluationState.PASSED,
        is_default=True,
        deployment_version_id=uuid4(),
    )
    legacy = Profile(
        id=uuid4(),
        kind=ProfileKind.GENERATION,
        name="legacy-model-bound",
        version=1,
        config={},
        bindings=(ProfileModelBinding(ModelKind.LLM, uuid4()),),
        evaluation_state=EvaluationState.PASSED,
        is_default=False,
    )
    repository.profiles = [current_default, legacy]
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_model_registry_service] = lambda: (
        RagModelRegistryService(repository)
    )

    with TestClient(app) as client:
        response = client.post(route.format(profile_id=legacy.id))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "legacy_profile_read_only"
    assert repository.profiles == [current_default, legacy]


def test_yaml_profile_is_validated_and_registered_through_the_api() -> None:
    repository = MemoryRegistryRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_model_registry_service] = lambda: RagModelRegistryService(
        repository
    )

    with TestClient(app) as client:
        model = client.post(
            "/api/v1/admin/rag/models",
            json={
                "kind": "llm",
                "name": "answer-model",
                "version": 1,
                "config": {
                    "provider": "openai_compatible",
                    "runtime_model": "synthetic/exact-model",
                    "data_policy": "local_only",
                },
            },
        ).json()
        deployment = ModelDeploymentVersion.create(
            deployment_id=uuid4(),
            version=1,
            display_name="Synthetic local deployment",
            description="Synthetic",
            model_definition_id=UUID(model["id"]),
            provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
            location=ExecutionLocation.LOCAL,
            allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
            provider_model_id="synthetic/exact-model",
            endpoint_ref="local-generation",
            secret_ref=None,
            capabilities=(DeploymentCapability.STRUCTURED_OUTPUT,),
            external_transfer=False,
            transmitted_data_categories=(),
            data_processing_notice_ref=None,
            timeout_seconds=30,
            max_retries=1,
            retry_backoff_seconds=0.5,
            healthcheck_enabled=True,
            development_only=False,
            created_by=owner().id,
        )
        repository.deployments[deployment.id] = deployment
        response = client.post(
            "/api/v1/admin/rag/profiles/generation/yaml",
            json={
                "content": f"""
kind: generation
name: local-generation
version: 1
evaluation_state: draft
config:
  prompt_ref: grounded-answer-v1
  context_prompt_ref: contextualize-v1
  citation_mode: required
  context_policy:
    max_history_turns: 6
    max_history_tokens: 1024
  generation:
    timeout_seconds: 30
    max_output_tokens: 512
    temperature: 0.1
    response_schema_version: 1
bindings: []
deployment_version_id: {deployment.id}
"""
            },
        )

    assert response.status_code == 201
    assert response.json()["kind"] == "generation"
    assert response.json()["bindings"] == []
    assert response.json()["deployment_version_id"] == str(deployment.id)
    assert response.json()["legacy"] is False


def test_member_can_read_registry_but_cannot_mutate_admin_or_legacy_api() -> None:
    repository = MemoryRegistryRepository()
    app = create_app()
    app.dependency_overrides[get_current_user] = member
    app.dependency_overrides[get_rag_model_registry_service] = lambda: RagModelRegistryService(
        repository
    )
    request = {
        "kind": "embedding",
        "name": "member-denied",
        "version": 1,
        "config": {"dimension": 768},
    }

    with TestClient(app) as client:
        models = client.get("/api/v1/rag/models")
        admin_denied = client.post("/api/v1/admin/rag/models", json=request)
        legacy_denied = client.post("/api/v1/rag/models", json=request)

    assert models.status_code == 200
    assert models.json() == []
    assert admin_denied.status_code == 403
    assert admin_denied.json()["error"]["code"] == "owner_required"
    assert legacy_denied.status_code == 403
    assert legacy_denied.json()["error"]["code"] == "owner_required"


def test_legacy_registry_commands_are_marked_deprecated() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/api/v1/rag/models"]["post"]["deprecated"] is True
    assert (
        schema["paths"]["/api/v1/rag/profiles/{kind}"]["post"]["deprecated"]
        is True
    )
    assert (
        schema["paths"]["/api/v1/rag/profiles/{kind}/yaml"]["post"]["deprecated"]
        is True
    )
    assert (
        schema["paths"]["/api/v1/rag/profiles/{profile_id}/default"]["post"]
        ["deprecated"]
        is True
    )
