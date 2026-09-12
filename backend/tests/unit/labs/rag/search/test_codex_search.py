"""Real search and Codex runtime; only provider work and storage ports are synthetic."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import DeploymentCapability
from ai_workshop.labs.rag.generation.codex_events import CodexEventResult, CodexTokenUsage
from ai_workshop.labs.rag.generation.codex_runtime import CodexExecRuntime
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest, GenerationStatus
from ai_workshop.labs.rag.generation.execution import (
    ProviderExecutionMetadata,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.test_codex_execution import request_fixture
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    WORKSPACE_ID,
    _approval,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import (
    ActiveScopeResolver,
    OneSourceResolver,
    OneSourceRetriever,
)

ATTESTATION = {
    "classification": "synthetic",
    "consented": True,
    "disclosure_version": "codex-external-generation-v1",
}


class SyntheticExecutor:
    def __init__(self):
        self.calls = []
        self.observed = None

    async def execute(self, context, *, request):
        self.calls.append((context, request))
        content = (
            {"resolved_query": "synthetic fact"}
            if isinstance(request, ContextualizationRequest)
            else {
                "schema_version": 2,
                "status": "answered",
                "claims": [
                    {
                        "text": "synthetic fact",
                        "evidence_ids": [str(request.evidence[0].evidence_id)],
                    }
                ],
            }
        )
        return CodexWorkspaceResult(
            stream=CodexStreamResult(
                events=CodexEventResult(
                    json.dumps(content),
                    "synthetic-thread",
                    CodexTokenUsage(20, 0, 7, None, 0),
                    observed_model=self.observed,
                ),
                active_processes_after_cleanup=0,
            ),
            process_termination_verified=True,
        )


class SyntheticReadiness:
    async def health(self, *, context, profile):
        return ProviderHealthResult(
            True,
            None,
            ProviderExecutionMetadata(
                profile.deployment.provider,
                profile.runtime_model,
                profile.deployment.id,
                None,
                None,
                0,
            ),
        )


class RecordingFactory:
    def __init__(self):
        self.contexts = []
        self.executor = SyntheticExecutor()

    def create(self, *, context, profile):
        self.contexts.append(context)
        return CodexExecRuntime(context, profile, self.executor, SyntheticReadiness())


class ForbiddenPreboundRuntime:
    async def health(self):
        pytest.fail("Codex must not use the prebound runtime shortcut")


def fixture():
    _, provider_request = request_fixture()
    profile = replace(
        provider_request.profile,
        deployment=replace(
            provider_request.profile.deployment,
            capabilities=frozenset(
                {DeploymentCapability.STRUCTURED_OUTPUT, DeploymentCapability.CONTEXTUALIZATION}
            ),
        ),
    )
    approval = replace(
        _approval(),
        deployment_version_id=profile.deployment.id,
        disclosure_version=ATTESTATION["disclosure_version"],
    )
    configuration = replace(
        _configuration(approval=approval),
        generation_profile=profile,
        generation_runtime=ForbiddenPreboundRuntime(),
    )
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        tuple(item.policy_version_id for item in approval.workspace_policies),
        workspace_policy_snapshots=tuple(
            (item.workspace_id, item.policy_version_id) for item in approval.workspace_policies
        ),
    )
    service, _, _, audit = _service(configuration=configuration, decision=decision)
    service.scope_resolver = ActiveScopeResolver()
    service.sparse_retriever = OneSourceRetriever()
    service.source_resolver = OneSourceResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-signing-key-at-least-32-bytes")
    return service, configuration, audit


def query(approval=ATTESTATION, **changes):
    return SearchRequest(
        query="synthetic fact",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
        codex_input_approval=approval,
        **changes,
    )


async def test_codex_never_uses_prebound_runtime_without_request_factory():
    service, _, _ = fixture()
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=ACTOR_ID, request=query())
    assert caught.value.code == "codex_runtime_unavailable"


async def test_codex_snapshot_uses_actual_stage_observation_not_passive_proof():
    service, configuration, _ = fixture()
    factory = RecordingFactory()
    factory.executor.observed = configuration.generation_profile.runtime_model
    service.codex_runtime_factory = factory
    result = await service.search(actor_id=ACTOR_ID, request=query())
    assert result.generation.execution.observed_provider_model_id == factory.executor.observed
    assert result.generation.execution.model_identity_status == "verified"


async def test_request_factory_and_audit_keep_public_correlation_separate_from_authority():
    from ai_workshop.labs.rag.generation.codex_composition import CodexRequestRuntimeFactory
    from ai_workshop.labs.rag.generation.codex_execution import CodexRequestExecutor
    from tests.unit.labs.rag.generation.test_codex_execution import NOW, setup_executor

    previous, context, request, _, source, slots, workspace, _ = setup_executor()
    correlation = uuid4()
    executor = CodexRequestExecutor(
        registry=previous._registry,
        source=source,
        slots=slots,
        workspace=workspace,
        clock=lambda: NOW,
        audit=previous._audit,
        correlation_id=correlation,
    )
    factory = CodexRequestRuntimeFactory(executor=executor, readiness=SyntheticReadiness())
    first = factory.create(context=context, profile=request.profile)
    second = factory.create(context=replace(context, request_id=uuid4()), profile=request.profile)
    assert first is not second and first.context != second.context
    await executor.execute(context, request=request)
    record = previous._audit.records[0]
    assert record.correlation_id == correlation and record.request_id == context.request_id
    assert record.request_id != record.correlation_id
    assert slots.leases[0].request_id == context.request_id
    assert source.issued[0][0].request_id == context.request_id


@pytest.mark.parametrize("model", [SearchRequest, pytest.param("domain", id="domain")])
@pytest.mark.parametrize(
    "invalid",
    [
        {**ATTESTATION, "consented": "true"},
        {**ATTESTATION, "consented": 1},
        {**ATTESTATION, "classification": "private"},
        {**ATTESTATION, "extra": "synthetic"},
    ],
)
def test_closed_strict_input_attestation(model, invalid):
    from pydantic import ValidationError

    from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest

    values = {
        "query": "synthetic",
        "workspace_ids": [WORKSPACE_ID],
        "codex_input_approval": invalid,
    }
    if model == "domain":
        model = DomainSearchRequest
        values["connection_version_id"] = uuid4()
    else:
        values["configuration_id"] = CONFIGURATION_ID
    with pytest.raises(ValidationError):
        model(**values)


def test_domain_accepts_exact_attestation_and_dependency_binds_actual_actor():
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.domains.api import get_domain_service
    from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest
    from ai_workshop.platform.identity.domain import UserRole
    from tests.integration.labs.rag.domains.test_api import _user

    request = DomainSearchRequest(
        query="synthetic",
        connection_version_id=uuid4(),
        workspace_ids=[WORKSPACE_ID],
        codex_input_approval=ATTESTATION,
    )
    assert request.codex_input_approval.consented is True
    user = _user(UserRole.MEMBER)
    service = get_domain_service(
        session=None,
        settings=Settings(
            _env_file=None,
            secret_key="synthetic-secret-at-least-thirty-two-characters",
            codex_runner_refs={},
        ),
        user=user,
    )
    assert service.configurations.service.generation_readiness.actor_id == user.id


@pytest.mark.parametrize(
    "code",
    [
        "codex_audit_required",
        "codex_capacity_exhausted",
        "codex_authorization_policy_denied",
        "codex_workspace_cleanup_failed",
        "provider_timeout",
    ],
)
async def test_typed_runtime_failures_keep_safe_code_through_search(code):
    from ai_workshop.labs.rag.generation.execution import GenerationProviderError

    service, _, _ = fixture()
    factory = RecordingFactory()

    async def fail(*args, **kwargs):
        raise GenerationProviderError(code, retryable=False)

    factory.executor.execute = fail
    service.codex_runtime_factory = factory
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=ACTOR_ID, request=query())
    assert caught.value.code == code


async def test_untrusted_factory_error_does_not_escape_search_error_boundary():
    service, _, _ = fixture()

    class BrokenFactory:
        def create(self, **values):
            raise RuntimeError("synthetic-untrusted-error-marker")

    service.codex_runtime_factory = BrokenFactory()
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=ACTOR_ID, request=query())
    assert caught.value.code == "codex_runtime_unavailable"
    assert "synthetic-untrusted" not in str(caught.value)


@pytest.mark.parametrize("domain", [False, True])
@pytest.mark.parametrize(
    "case,expected",
    [
        ("valid", 409),
        ("missing_origin", 403),
        ("wrong_origin", 403),
        ("missing_header", 403),
        ("wrong_header", 403),
        ("wrong_media", 422),
        ("no_attestation", 409),
    ],
)
def test_search_endpoints_guard_only_explicit_codex_mutations(domain, case, expected):
    from fastapi.testclient import TestClient

    from ai_workshop.config import Settings, get_settings
    from ai_workshop.labs.rag.domains.api import get_domain_search_executor
    from ai_workshop.labs.rag.search.api import get_search_service
    from ai_workshop.main import create_app
    from ai_workshop.platform.identity.api import get_current_user
    from ai_workshop.platform.identity.domain import UserRole
    from tests.integration.labs.rag.domains.test_api import _user

    class Stop:
        calls = 0

        async def search(self, **values):
            self.calls += 1
            raise AppError("synthetic_stop", "Synthetic stop.", 409)

        execute = search

    stop = Stop()
    settings = Settings(
        _env_file=None,
        secret_key="synthetic-secret-at-least-thirty-two-characters",
        codex_runner_refs={},
        codex_allowed_admin_origins=("http://localhost:3000",),
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.OWNER)
    app.dependency_overrides[get_search_service] = lambda: stop
    app.dependency_overrides[get_domain_search_executor] = lambda: stop
    headers = {
        "origin": "http://localhost:3000",
        "x-codex-request": "1",
        "content-type": "application/json",
    }
    payload = {
        "query": "synthetic fact",
        "workspace_ids": [str(WORKSPACE_ID)],
        "codex_input_approval": ATTESTATION,
    }
    payload["connection_version_id" if domain else "configuration_id"] = str(CONFIGURATION_ID)
    if case == "missing_origin":
        headers.pop("origin")
    if case == "wrong_origin":
        headers["origin"] = "https://unapproved.example"
    if case == "missing_header":
        headers.pop("x-codex-request")
    if case == "wrong_header":
        headers["x-codex-request"] = "true"
    if case == "wrong_media":
        headers["content-type"] = "text/plain"
    if case == "no_attestation":
        payload.pop("codex_input_approval")
        headers.pop("origin")
        headers.pop("x-codex-request")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/rag/domains/synthetic/search" if domain else "/api/v1/rag/search",
            content=json.dumps(payload),
            headers=headers,
        )
    assert response.status_code == expected
    assert stop.calls == (1 if expected == 409 else 0)


@pytest.mark.parametrize(
    "approval",
    [
        None,
        {**ATTESTATION, "consented": False},
        {**ATTESTATION, "disclosure_version": "external-generation-v1"},
    ],
)
async def test_each_codex_question_requires_exact_input_consent_before_factory(approval):
    service, _, _ = fixture()
    factory = RecordingFactory()
    service.codex_runtime_factory = factory
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=ACTOR_ID, request=query(approval))
    assert caught.value.code == "codex_input_approval_required"
    assert not factory.contexts and not factory.executor.calls


async def test_codex_unknown_identity_answers_with_citation_and_signed_followup_new_request_id():
    service, configuration, audit = fixture()
    factory = RecordingFactory()
    service.codex_runtime_factory = factory
    first = await service.search(actor_id=ACTOR_ID, request=query())
    assert first.generation.status is GenerationStatus.ANSWERED
    assert first.generation.text == "synthetic fact"
    assert first.generation.citations and first.generation.validation_token
    assert first.generation.execution.model_identity_status == "unknown"
    second = await service.search(
        actor_id=ACTOR_ID,
        request=query(
            history=[
                {"role": "user", "content": "synthetic fact"},
                {
                    "role": "assistant",
                    "content": first.generation.text,
                    "turn_id": first.generation.turn_id,
                    "validation_token": first.generation.validation_token,
                },
            ]
        ),
    )
    assert second.generation.status is GenerationStatus.ANSWERED
    assert len(factory.executor.calls) == 3
    first_context, next_context = factory.contexts
    assert first_context.actor_id == next_context.actor_id == ACTOR_ID
    assert first_context.configuration_version_id == configuration.configuration_version_id
    assert first_context.workspace_ids == (WORKSPACE_ID,)
    assert first_context.request_id != next_context.request_id
    assert factory.executor.calls[1][0] == factory.executor.calls[2][0] == next_context
    assert len(audit.audits) == 2
