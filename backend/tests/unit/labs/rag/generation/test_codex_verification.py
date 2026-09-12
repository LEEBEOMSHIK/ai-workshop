"""Synthetic verification, disclosure and exact saved-configuration contracts."""

import asyncio
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import ExternalTransferApprovalConfirmation
from ai_workshop.labs.rag.configurations.schemas import ExternalTransferApprovalInput
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.deployments.repository import DeploymentCatalogEntry
from ai_workshop.labs.rag.deployments.schemas import DeploymentOptionResponse
from ai_workshop.labs.rag.generation.codex_events import CodexEventResult, CodexTokenUsage
from ai_workshop.labs.rag.generation.codex_execution import CodexRequestExecutor
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest, generation_disclosure
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind, ProfileValidationError
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.configurations.test_configuration import (
    MemoryConfigurationRepository,
    RecordingIngestionJobs,
    _deployment,
    _generation_profile,
    _installation_policy,
    _technical_profiles,
    _workspace_policy,
)
from tests.unit.labs.rag.deployments.test_domain import codex_deployment
from tests.unit.labs.rag.generation.test_codex_execution import (
    NOW,
    FakeRegistry,
    request_fixture,
    setup_executor,
)


def test_codex_disclosure_crosses_transport_domain_and_option_without_relabeling_http():
    deployment = codex_deployment()
    disclosure = generation_disclosure(deployment)
    assert disclosure.version == "codex-external-generation-v1"
    assert "OpenAI" in disclosure.text and "Codex" in disclosure.text
    confirmation = ExternalTransferApprovalInput(
        confirmed=True,
        disclosure_version=disclosure.version,
    ).to_domain()
    assert confirmation.disclosure_version == "codex-external-generation-v1"
    option = DeploymentOptionResponse.from_entry(DeploymentCatalogEntry(deployment, "Synthetic", 1))
    assert option.approval.disclosure_version == disclosure.version
    http = _deployment(location=ExecutionLocation.EXTERNAL, provider=ProviderKind.OPENAI_RESPONSES)
    assert generation_disclosure(http).version == "external-generation-v1"


@pytest.mark.parametrize("codex", [True, False])
@pytest.mark.parametrize("submitted", ["external-generation-v1", "codex-external-generation-v1"])
async def test_save_compares_exact_provider_disclosure_before_persisting(codex, submitted):
    indexing, retrieval = _technical_profiles()
    workspace_id = uuid4()
    deployment = (
        codex_deployment()
        if codex
        else _deployment(
            location=ExecutionLocation.EXTERNAL,
            provider=ProviderKind.OPENAI_RESPONSES,
        )
    )
    generation = _generation_profile(deployment.id)
    repository = MemoryConfigurationRepository(
        profiles=(indexing, retrieval, generation),
        accessible_workspace_ids=(workspace_id,),
        deployments=(deployment,),
        installation_policy=replace(
            _installation_policy(), approved_providers=frozenset({deployment.provider})
        ),
        workspace_policies=(
            replace(
                _workspace_policy(workspace_id), approved_providers=frozenset({deployment.provider})
            ),
        ),
    )
    service = RagConfigurationService(repository, RecordingIngestionJobs(repository.events))
    arguments = dict(
        owner_id=uuid4(),
        name="Synthetic exact disclosure",
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=generation.id,
        answer_mode="generative",
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
        workspace_ids=(workspace_id,),
        external_transfer_approval=ExternalTransferApprovalConfirmation(
            confirmed=True,
            disclosure_version=submitted,
        ),
    )
    correct = submitted == ("codex-external-generation-v1" if codex else "external-generation-v1")
    if correct:
        result = await service.create(**arguments)
        assert repository.approvals[0].configuration_version_id == result.configuration.version_id
        assert repository.approvals[0].disclosure_version == submitted
        assert not result.configuration.is_default
    else:
        with pytest.raises(AppError, match="disclosure"):
            await service.create(**arguments)
        assert not repository.saved and not repository.approvals


def test_provider_independent_llm_identity_does_not_fabricate_local_runtime():
    model = ModelDefinition.create(
        kind=ModelKind.LLM,
        name="Synthetic selected model",
        version=1,
        config={"model_identifier": "synthetic-model-v1"},
    )
    assert dict(model.config) == {"model_identifier": "synthetic-model-v1"}


@pytest.mark.parametrize(
    "config",
    [
        {"model_identifier": ""},
        {"model_identifier": " "},
        {"model_identifier": True},
        {"model_identifier": "valid", "provider": "openai_compatible"},
    ],
)
def test_invalid_or_mixed_provider_independent_identity_is_rejected(config):
    with pytest.raises(ProfileValidationError):
        ModelDefinition.create(kind=ModelKind.LLM, name="Synthetic", version=1, config=config)


class MemoryProofs:
    def __init__(self):
        self.attempts = []

    async def append_attempt(self, attempt):
        self.attempts.append(attempt)

    async def latest_attempt(self, configuration_version_id):
        return next(
            (
                item
                for item in reversed(self.attempts)
                if item.configuration_version_id == configuration_version_id
            ),
            None,
        )


class FakeProofLookup:
    def __init__(self, module, context, request):
        self.actor_id = context.actor_id
        self.values = {
            context.configuration_version_id: module.CodexVerificationConfiguration(
                configuration_version_id=context.configuration_version_id,
                workspace_ids=context.workspace_ids,
                profile=request.profile,
                profile_sha256="a" * 64,
            )
        }
        self.calls = []

    async def load(self, *, actor_id, configuration_version_id):
        self.calls.append((actor_id, configuration_version_id))
        return self.values.get(configuration_version_id) if actor_id == self.actor_id else None


class FakeVerificationExecutor:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def execute(self, context, *, request):
        self.calls.append((context, request))
        content = (
            '{"resolved_query":"synthetic connection question"}'
            if isinstance(request, ContextualizationRequest)
            else '{"schema_version":2,"status":"insufficient_evidence","claims":[]}'
        )
        return CodexWorkspaceResult(
            failure="synthetic-safe-failure" if self.fail else None,
            stream=CodexStreamResult(
                events=CodexEventResult(
                    content, "synthetic-thread", CodexTokenUsage(10, 0, 5, None, 0)
                ),
                active_processes_after_cleanup=0,
            ),
            process_termination_verified=True,
        )


def verification_fixture():
    name = "ai_workshop.labs.rag.generation.codex_verification"
    assert find_spec(name) is not None, "saved exact-configuration proof service is missing"
    module = import_module(name)
    context, request = request_fixture()
    context = replace(context, disclosure_version="codex-external-generation-v1")
    proofs = MemoryProofs()
    lookup = FakeProofLookup(module, context, request)
    registry = FakeRegistry()
    executor = FakeVerificationExecutor()
    service = module.CodexVerificationService(
        lookup=lookup,
        proofs=proofs,
        registry=registry,
        executor=executor,
        environment="test",
        clock=lambda: NOW,
    )
    return SimpleNamespace(
        module=module,
        context=context,
        request=request,
        proofs=proofs,
        lookup=lookup,
        registry=registry,
        executor=executor,
        service=service,
    )


async def _verify(fixture):
    return await fixture.service.verify(
        actor_id=fixture.context.actor_id,
        configuration_version_id=fixture.context.configuration_version_id,
        consented=True,
        disclosure_version="codex-external-generation-v1",
    )


async def test_only_two_explicit_synthetic_stages_create_exact_passive_proof():
    f = verification_fixture()
    assert not (
        await f.service.status(
            actor_id=f.context.actor_id, configuration_version_id=f.context.configuration_version_id
        )
    ).ready
    assert not f.executor.calls
    status = await _verify(f)
    assert status.ready and status.observed_provider_model_id is None
    assert status.model_identity_status == "unknown"
    assert len(f.executor.calls) == 2
    for context, request in f.executor.calls:
        assert context.operation.value == "connection_check"
        assert context.input_classification.value == "synthetic" and context.consented is True
        assert not getattr(request, "evidence", ())
    assert (await f.service.health(context=f.context, profile=f.request.profile)).ready
    assert len(f.executor.calls) == 2
    assert len(f.proofs.attempts) == 1 and f.proofs.attempts[0].usage_present


async def test_two_configurations_sharing_profile_never_share_proof():
    f = verification_fixture()
    other = uuid4()
    f.lookup.values[other] = replace(
        f.lookup.values[f.context.configuration_version_id], configuration_version_id=other
    )
    await _verify(f)
    assert not (
        await f.service.status(actor_id=f.context.actor_id, configuration_version_id=other)
    ).ready
    assert not (
        await f.service.health(
            context=replace(f.context, configuration_version_id=other), profile=f.request.profile
        )
    ).ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("configuration_sha256", "c" * 64),
        ("executable_sha256", "d" * 64),
        ("expected_cli_version", "1.2.3"),
    ],
)
async def test_changed_cli_or_registry_invalidates_existing_proof_without_launch(field, value):
    f = verification_fixture()
    await _verify(f)
    f.registry.runner = replace(f.registry.runner, **{field: value})
    assert not (await f.service.health(context=f.context, profile=f.request.profile)).ready
    assert len(f.executor.calls) == 2


async def test_latest_failed_attempt_invalidates_prior_success():
    f = verification_fixture()
    await _verify(f)
    f.executor.fail = True
    failed = await _verify(f)
    assert not failed.ready
    assert not (await f.service.health(context=f.context, profile=f.request.profile)).ready
    assert len(f.proofs.attempts) == 2 and not f.proofs.attempts[-1].success


@pytest.mark.parametrize(
    "consented,disclosure",
    [
        (False, "codex-external-generation-v1"),
        (1, "codex-external-generation-v1"),
        (True, "external-generation-v1"),
    ],
)
async def test_verification_rejects_missing_exact_consent_before_launch(consented, disclosure):
    f = verification_fixture()
    with pytest.raises(AppError):
        await f.service.verify(
            actor_id=f.context.actor_id,
            configuration_version_id=f.context.configuration_version_id,
            consented=consented,
            disclosure_version=disclosure,
        )
    assert not f.executor.calls and not f.proofs.attempts


class FakeStageAudit:
    def __init__(self):
        self.records = []
        self.error = None
        self.started = asyncio.Event()
        self.allowed = asyncio.Event()
        self.allowed.set()

    async def append_stage(self, record):
        self.started.set()
        await self.allowed.wait()
        if self.error is not None:
            raise self.error
        self.records.append(record)


def audited_executor_fixture():
    _, context, request, registry, source, slots, workspace, log = setup_executor()
    audit = FakeStageAudit()
    executor = CodexRequestExecutor(
        registry=registry,
        source=source,
        slots=slots,
        workspace=workspace,
        clock=lambda: NOW,
        audit=audit,
    )
    return executor, context, request, source, slots, workspace, audit


async def test_stage_audit_contains_signatures_and_safe_metadata_never_prompt_body():
    executor, context, request, source, slots, workspace, audit = audited_executor_fixture()
    workspace.result = CodexWorkspaceResult(
        stream=CodexStreamResult(
            events=CodexEventResult(
                '{"schema_version":2,"status":"insufficient_evidence","claims":[]}',
                "synthetic",
                CodexTokenUsage(10, 0, 5, None, 0),
            ),
            active_processes_after_cleanup=0,
        ),
        process_termination_verified=True,
    )
    await executor.execute(context, request=request)
    record = audit.records[0]
    assert record.actor_id == context.actor_id and record.request_id == context.request_id
    assert record.configuration_version_id == context.configuration_version_id
    assert record.prompt.task_ref == "rag-codex-answer-v3"
    assert record.payload_sha256 == source.issued[0][1].digest()
    assert record.outcome == "completed" and record.usage.input_tokens == 10
    assert record.configuration_sha256 == "b" * 64
    assert request.question not in repr(record) and request.evidence[0].text not in repr(record)
    assert slots.completions == [True]


@pytest.mark.parametrize("termination", [False, True])
async def test_audit_failure_fails_request_without_releasing_unknown_process_lease(termination):
    executor, context, request, _, slots, workspace, audit = audited_executor_fixture()
    workspace.result = CodexWorkspaceResult(process_termination_verified=termination)
    audit.error = RuntimeError("synthetic private DB audit canary")
    with pytest.raises(GenerationProviderError) as caught:
        await executor.execute(context, request=request)
    assert slots.completions == [termination]
    assert caught.value.__context__ is None and "canary" not in repr(caught.value)


async def test_missing_audit_is_rejected_before_slot_authorization_or_launch():
    executor, context, request, source, slots, workspace, _ = audited_executor_fixture()
    executor._audit = None
    with pytest.raises(GenerationProviderError, match="^codex_audit_required$"):
        await executor.execute(context, request=request)
    assert not source.issued and not slots.leases and not workspace.calls


@pytest.mark.parametrize("failure", ["schema", "model", "invalid_usage"])
async def test_failed_stage_preserves_only_valid_completed_event_metadata(failure):
    executor, context, request, _, _, workspace, audit = audited_executor_fixture()
    usage = CodexTokenUsage(20, 5, 7, None, 0)
    if failure == "invalid_usage":
        usage = replace(usage, input_tokens=True)
    workspace.result = CodexWorkspaceResult(
        stream=CodexStreamResult(
            events=CodexEventResult(
                "not a valid final schema",
                "synthetic",
                usage,
                observed_model="different-model" if failure == "model" else None,
            ),
            active_processes_after_cleanup=0,
        ),
        process_termination_verified=True,
    )
    await executor.execute(context, request=request)
    record = audit.records[0]
    assert record.outcome == "failed"
    assert record.usage == (None if failure == "invalid_usage" else usage)
    assert record.observed_provider_model_id == ("different-model" if failure == "model" else None)
    if failure == "model":
        assert record.safe_error_code == "codex_stage_model_mismatch"
    elif failure == "schema":
        assert record.safe_error_code == "codex_stage_schema_invalid"


async def test_repeated_cancellation_waits_for_required_audit_before_lease_finalization():
    executor, context, request, _, slots, workspace, audit = audited_executor_fixture()
    audit.allowed.clear()
    task = asyncio.create_task(executor.execute(context, request=request))
    try:
        await asyncio.wait_for(audit.started.wait(), 2)
        task.cancel()
        assert await asyncio.wait_for(
            asyncio.to_thread(workspace.calls[0]["cancellation"].wait, 2), 3
        )
        task.cancel()
        turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(turn.set)
        await turn.wait()
        assert not task.done() and not slots.completions
    finally:
        audit.allowed.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert len(audit.records) == 1 and slots.completions == [True]


async def test_repeated_cancel_during_proof_commit_waits_and_invalidates_success():
    f = verification_fixture()
    await _verify(f)
    started, allowed = asyncio.Event(), asyncio.Event()
    original = f.proofs.append_attempt

    async def append(attempt):
        started.set()
        await allowed.wait()
        await original(attempt)

    f.proofs.append_attempt = append
    f.executor.fail = True
    task = asyncio.create_task(_verify(f))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        allowed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(f.proofs.attempts) == 2 and not f.proofs.attempts[-1].success


@pytest.mark.parametrize(
    "change",
    [
        {"safe_error_code": "private synthetic traceback"},
        {"checked_at": NOW.replace(tzinfo=None)},
        {"success": 1},
        {"requested_provider_model_id": "x" * 181},
    ],
)
async def test_proof_metadata_rejects_raw_errors_unbounded_or_ambiguous_values(change):
    f = verification_fixture()
    await _verify(f)
    with pytest.raises(ValueError, match="metadata_invalid"):
        replace(f.proofs.attempts[0], **change)


@pytest.mark.parametrize(
    "content",
    [
        '{"resolved_query":"valid","resolved_query":"duplicate"}',
        '{"resolved_query":NaN}',
        '{"resolved_query":Infinity}',
    ],
)
def test_context_schema_rejects_nonstandard_json_or_duplicates(content):
    f = verification_fixture()
    with pytest.raises((ValueError, GenerationProviderError)):
        f.module.strict_context_query(content)


async def test_production_and_wrong_actor_cannot_obtain_or_create_proof():
    f = verification_fixture()
    for actor in (uuid4(), f.context.actor_id):
        if actor == f.context.actor_id:
            f.service._environment = "production"
        with pytest.raises(AppError):
            await f.service.status(
                actor_id=actor, configuration_version_id=f.context.configuration_version_id
            )
    assert not f.proofs.attempts and not f.executor.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_sha256", "f" * 64),
        ("prompt_ref", "rag-codex-answer-v2"),
        ("context_prompt_ref", "unsupported"),
        ("response_schema_version", 3),
        ("runtime_model", "different-model"),
    ],
)
async def test_profile_model_or_prompt_contract_change_invalidates_proof(field, value):
    f = verification_fixture()
    await _verify(f)
    current = f.lookup.values[f.context.configuration_version_id]
    if field == "profile_sha256":
        current = replace(current, profile_sha256=value)
    elif field == "runtime_model":
        current = replace(
            current,
            profile=replace(
                current.profile,
                runtime_model=value,
                deployment=replace(current.profile.deployment, provider_model_id=value),
            ),
        )
    else:
        current = replace(current, profile=replace(current.profile, **{field: value}))
    f.lookup.values[f.context.configuration_version_id] = current
    assert not (
        await f.service.status(
            actor_id=f.context.actor_id, configuration_version_id=f.context.configuration_version_id
        )
    ).ready
    assert len(f.executor.calls) == 2


@pytest.mark.parametrize("failure", ["missing_usage", "mismatch", "schema", "process", "cleanup"])
async def test_invalid_stream_never_creates_ready_proof(failure):
    f = verification_fixture()
    execute = f.executor.execute

    async def invalid(context, *, request):
        result = await execute(context, request=request)
        if failure == "cleanup":
            return replace(result, cleanup_verified=False)
        if failure == "process":
            return replace(
                result, stream=replace(result.stream, active_processes_after_cleanup=False)
            )
        event = result.stream.events
        if failure == "missing_usage":
            event = replace(event, usage=None)
        elif failure == "mismatch":
            event = replace(event, observed_model="different-model")
        else:
            event = replace(event, final_text='{"unexpected":"synthetic"}')
        return replace(result, stream=replace(result.stream, events=event))

    f.executor.execute = invalid
    result = await _verify(f)
    assert not result.ready and not f.proofs.attempts[-1].success
    if failure == "mismatch":
        assert result.model_identity_status == "mismatch"
        assert result.observed_provider_model_id == "different-model"
