"""Trusted prompt rederivation must cover numeric profiles before policy approval."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
from ai_workshop.labs.rag.generation import codex_approval_repository as repository
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallOperation,
    CodexCallStage,
    EvidenceClassification,
)
from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.codex_request import CodexRequestContext
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget
from tests.unit.labs.rag.deployments.test_domain import codex_deployment
from tests.unit.labs.rag.generation.numeric_proof_fixtures import numeric_profile


class ReachedPolicyCheck(Exception):
    pass


@pytest.mark.parametrize("stage", [CodexCallStage.GENERATE, CodexCallStage.CONTEXTUALIZE])
async def test_schema3_authorization_rederives_trusted_prompt_before_policy(monkeypatch, stage):
    actor, request_id, config_id, workspace = (uuid4() for _ in range(4))
    context = CodexRequestContext(
        actor,
        request_id,
        CodexCallOperation.CONNECTION_CHECK,
        config_id,
        (workspace,),
        EvidenceClassification.SYNTHETIC,
        True,
        "codex-external-generation-v1",
    )
    profile = replace(numeric_profile(), evidence_budget=EvidenceBudget(2, 4, 1000))
    deployment = codex_deployment()
    generation = SimpleNamespace(deployment_version_id=deployment.id)
    configuration = SimpleNamespace(
        generation_profile_id=profile.profile_id,
        workspace_ids=(workspace,),
        version_id=config_id,
    )

    class Configurations:
        def __init__(self, session):
            pass

        async def find_version_visible(self, version_id, actor_id):
            assert (version_id, actor_id) == (config_id, actor)
            return configuration

        async def find_profile(self, profile_id):
            assert profile_id == profile.profile_id
            return generation

        async def get_deployment_version(self, deployment_id):
            assert deployment_id == deployment.id
            return deployment

        async def get_model_definition(self, model_id):
            return object()

    class Policies:
        def __init__(self, session):
            pass

        async def lock_external_execution_policy(self):
            pass

        async def latest_installation_policy(self):
            raise ReachedPolicyCheck

    async def owner(self, session, actor_id):
        assert actor_id == actor

    async def workspaces(self, session, actor_id, configured_ids, *, selected_ids):
        assert configured_ids == selected_ids == (workspace,)
        return {}

    captured = []

    def prompt(request):
        envelope = build_codex_prompt(request)
        captured.append((request, envelope))
        return envelope

    monkeypatch.setattr(repository, "SqlAlchemyRagConfigurationRepository", Configurations)
    monkeypatch.setattr(repository, "SqlAlchemyDataPolicyRepository", Policies)
    monkeypatch.setattr(repository, "resolve_generation_profile", lambda *args: profile)
    monkeypatch.setattr(repository, "build_codex_prompt", prompt)
    monkeypatch.setattr(repository.SqlAlchemyCodexAuthorizationSource, "_owner", owner)
    monkeypatch.setattr(repository.SqlAlchemyCodexAuthorizationSource, "_workspaces", workspaces)
    source = object.__new__(repository.SqlAlchemyCodexAuthorizationSource)
    source._environment = DeploymentEnvironment.DEVELOPMENT
    source._registry = SimpleNamespace(
        resolve=lambda ref: SimpleNamespace(configuration_sha256="a" * 64)
    )
    with pytest.raises(ReachedPolicyCheck):
        await source._derive(object(), context, stage=stage, approval_id=uuid4(), revisions=())
    assert len(captured) == 1
    request, envelope = captured[0]
    if stage is CodexCallStage.GENERATE:
        assert request.evidence == ()
        assert request.numeric_catalogue.request_id == request_id
        assert request.numeric_catalogue.configuration_version_id == config_id
        assert request.numeric_catalogue.generation_profile_id == profile.profile_id
        assert request.numeric_catalogue.tokens == ()
        assert envelope.schema_ref == "codex-grounded-wire-v2"
    else:
        assert envelope.schema_ref == "contextualization-v1"
