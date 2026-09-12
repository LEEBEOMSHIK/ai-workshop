"""Owned lifecycle proofs with explicit fake ports; no processes, files or DB."""

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationError,
    CodexAuthorizationErrorCode,
    CodexCallOperation,
    CodexCallStage,
    EvidenceClassification,
    EvidenceRevision,
)
from ai_workshop.labs.rag.generation.codex_request import CodexRequestContext
from ai_workshop.labs.rag.generation.codex_runner_registry import CodexRunnerRegistry
from ai_workshop.labs.rag.generation.codex_slots import CodexExecutionLease
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from tests.unit.labs.rag.deployments.test_domain import codex_deployment
from tests.unit.labs.rag.generation.test_codex_authorization import NOW, _intent, _snapshot
from tests.unit.labs.rag.generation.test_codex_command import _runner
from tests.unit.labs.rag.generation.test_codex_prompt import (
    make_generation_request,
    make_profile,
)


def request_fixture():
    deployment = codex_deployment(runner_ref="codex-cli-verified", timeout_seconds=20.0)
    profile = make_profile(
        model_id=deployment.model_definition_id,
        runtime_model=deployment.provider_model_id,
        deployment=deployment,
        prompt_ref="rag-codex-answer-v3",
        timeout_seconds=25.0,
        max_output_tokens=512,
    )
    context = CodexRequestContext(
        actor_id=UUID(int=1),
        request_id=UUID(int=2),
        operation=CodexCallOperation.SEARCH,
        configuration_version_id=UUID(int=4),
        workspace_ids=(UUID(int=10), UUID(int=11)),
        input_classification=EvidenceClassification.SYNTHETIC,
        consented=True,
        disclosure_version="external-generation-v1",
    )
    return context, make_generation_request(profile=profile)


class FakeRegistry(CodexRunnerRegistry):
    def __init__(self):
        self.runner = _runner(Path("C:/synthetic-fixture"))

    def resolve(self, reference):
        assert reference == self.runner.reference
        return self.runner


class FakeSource:
    def __init__(self, log, profile):
        self.log = log
        self.profile = profile
        self.issued = []
        self.lock_task = None
        self.locked = False
        self.deny = False
        self.exit_error = None
        self.exit_started = asyncio.Event()
        self.allow_exit = asyncio.Event()
        self.allow_exit.set()

    async def issue_request(self, context, *, stage, payload, evidence_revision_ids, ttl):
        assert timedelta(0) < ttl <= timedelta(hours=1)
        self.log.append("issue")
        if self.deny:
            raise CodexAuthorizationError(CodexAuthorizationErrorCode.POLICY_DENIED)
        intent = replace(
            _intent(payload),
            actor_id=context.actor_id,
            request_id=context.request_id,
            approval_id=uuid4(),
            stage=stage,
            operation=context.operation,
            configuration_version_id=context.configuration_version_id,
            deployment_version_id=self.profile.deployment.id,
            generation_profile_id=self.profile.profile_id,
            runner_configuration_sha256="b" * 64,
            runner_ref=self.profile.deployment.runner_ref,
            provider_model_id=self.profile.runtime_model,
            generation_disclosure_version=context.disclosure_version,
            evidence_revisions=tuple(
                EvidenceRevision(value, "a" * 64, 1) for value in evidence_revision_ids
            ),
        )
        self.issued.append((intent, payload, evidence_revision_ids))
        return intent

    @asynccontextmanager
    async def locked_snapshot(self, intent):
        self.lock_task = asyncio.current_task()
        self.locked = True
        self.log.append("gate-enter")
        try:
            payload = next(p for i, p, _ in self.issued if i == intent)
            yield _snapshot(intent=intent, payload=payload)
        finally:
            self.exit_started.set()
            await self.allow_exit.wait()
            self.locked = False
            self.log.append("gate-exit")
            if self.exit_error is not None:
                raise self.exit_error

    async def consume(self, approval_id, request_id, stage):
        assert asyncio.current_task() is self.lock_task
        assert self.locked
        self.log.append("consume")
        return True


class FakeSlots:
    def __init__(self, log):
        self.log = log
        self.full = False
        self.leases = []
        self.completions = []
        self.finalize_started = asyncio.Event()
        self.allow_finalize = asyncio.Event()
        self.allow_finalize.set()
        self.finalize_error = None

    async def acquire(self, *, runner_ref, configuration_sha256, max_concurrent, request_id):
        self.log.append("acquire")
        assert max_concurrent == 1
        if self.full:
            return None
        lease = CodexExecutionLease(uuid4(), request_id, runner_ref, configuration_sha256)
        self.leases.append(lease)
        return lease

    async def complete(self, lease, *, process_termination_verified):
        assert lease in self.leases
        self.finalize_started.set()
        await self.allow_finalize.wait()
        self.completions.append(process_termination_verified)
        self.log.append("finalize")
        if self.finalize_error is not None:
            raise self.finalize_error


class FakeWorkspace:
    def __init__(self, log, source):
        self.log = log
        self.source = source
        self.calls = []
        self.result = CodexWorkspaceResult(process_termination_verified=True)
        self.error = None
        self.started = asyncio.Event()
        self.allow_cleanup = threading.Event()
        self.allow_cleanup.set()
        self.loop = asyncio.get_running_loop()

    def run(self, **kwargs):
        assert self.source.locked
        self.calls.append(kwargs)
        self.log.append("worker")
        self.loop.call_soon_threadsafe(self.started.set)
        assert self.allow_cleanup.wait(timeout=5), "synthetic worker cleanup barrier timed out"
        if self.error is not None:
            raise self.error
        self.log.append("worker-done")
        return self.result


class MemoryStageAudit:
    def __init__(self):
        self.records = []

    async def append_stage(self, record):
        self.records.append(record)


def setup_executor():
    name = "ai_workshop.labs.rag.generation.codex_execution"
    assert find_spec(name) is not None, "request coordinator is missing"
    context, request = request_fixture()
    log = []
    registry = FakeRegistry()
    source = FakeSource(log, request.profile)
    slots = FakeSlots(log)
    workspace = FakeWorkspace(log, source)
    executor = import_module(name).CodexRequestExecutor(
        registry=registry,
        source=source,
        slots=slots,
        workspace=workspace,
        clock=lambda: NOW,
        audit=MemoryStageAudit(),
    )
    return executor, context, request, registry, source, slots, workspace, log


async def test_owned_order_and_exact_payload_fingerprint_and_limits():
    executor, context, request, registry, source, slots, workspace, log = setup_executor()
    result = await executor.execute(context, request=request)
    assert result is workspace.result
    assert log == [
        "acquire",
        "issue",
        "gate-enter",
        "consume",
        "worker",
        "worker-done",
        "gate-exit",
        "finalize",
    ]
    call = workspace.calls[0]
    assert call["payload"] is source.issued[0][1]
    assert call["expected_configuration_sha256"] == "b" * 64
    assert call["intent"] is source.issued[0][0]
    assert call["timeout_seconds"] == 20.0 and call["max_output_tokens"] == 512
    assert source.issued[0][2] == (request.evidence[0].asset_version_id,)
    assert slots.completions == [True]


@pytest.mark.parametrize("failure", ["full", "denied"])
async def test_capacity_or_authorization_denial_never_launches(failure):
    executor, context, request, _, source, slots, workspace, log = setup_executor()
    slots.full = failure == "full"
    source.deny = failure == "denied"
    with pytest.raises(GenerationProviderError):
        await executor.execute(context, request=request)
    assert not workspace.calls
    assert "consume" not in log
    assert slots.completions == ([] if failure == "full" else [True])


async def test_each_stage_issues_distinct_approval_and_context_has_no_evidence():
    executor, context, request, _, source, _, _, _ = setup_executor()
    contextual = ContextualizationRequest(request.question, request.history, request.profile)
    await executor.execute(context, request=contextual)
    await executor.execute(context, request=request)
    assert [i.stage for i, _, _ in source.issued] == [
        CodexCallStage.CONTEXTUALIZE,
        CodexCallStage.GENERATE,
    ]
    assert source.issued[0][0].approval_id != source.issued[1][0].approval_id
    assert source.issued[0][2] == ()


@pytest.mark.parametrize("phase", ["worker", "gate-exit", "finalize"])
async def test_repeated_cancellation_joins_entire_owned_lifecycle(phase):
    executor, context, request, _, source, slots, workspace, log = setup_executor()
    if phase == "worker":
        workspace.allow_cleanup.clear()
        barrier = workspace.started
    elif phase == "gate-exit":
        source.allow_exit.clear()
        barrier = source.exit_started
    else:
        slots.allow_finalize.clear()
        barrier = slots.finalize_started
    task = asyncio.create_task(executor.execute(context, request=request))
    try:
        await asyncio.wait_for(barrier.wait(), 2)
        task.cancel()
        assert await asyncio.wait_for(
            asyncio.to_thread(workspace.calls[0]["cancellation"].wait, 2), 3
        )
        task.cancel()
        turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(turn.set)
        await turn.wait()
        assert not task.done()
        assert not slots.completions
        if phase == "worker":
            assert source.locked and "gate-exit" not in log
    finally:
        workspace.allow_cleanup.set()
        source.allow_exit.set()
        slots.allow_finalize.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert log.index("worker-done") < log.index("gate-exit") < log.index("finalize")
    assert slots.completions == [True]


@pytest.mark.parametrize(
    "result,error,termination",
    [
        (
            CodexWorkspaceResult(
                cleanup_verified=False,
                failure="codex_workspace_cleanup_failed",
                process_termination_verified=True,
            ),
            None,
            True,
        ),
        (
            CodexWorkspaceResult(cleanup_verified=False, failure="codex_workspace_cleanup_failed"),
            None,
            False,
        ),
        (None, RuntimeError("synthetic private path canary"), False),
    ],
)
async def test_worker_failure_preserves_independent_termination_evidence(
    result, error, termination
):
    executor, context, request, _, _, slots, workspace, _ = setup_executor()
    workspace.result, workspace.error = result, error
    if error is not None:
        with pytest.raises(GenerationProviderError) as raised:
            await executor.execute(context, request=request)
        assert "canary" not in repr(raised.value)
        assert raised.value.__context__ is None and raised.value.__cause__ is None
    else:
        assert await executor.execute(context, request=request) is result
    assert slots.completions == [termination]


@pytest.mark.parametrize("phase", ["gate-exit", "finalize"])
async def test_error_after_successful_worker_cleanup_still_fails_without_retry(phase):
    executor, context, request, _, source, slots, workspace, _ = setup_executor()
    error = RuntimeError("synthetic private persistence canary")
    if phase == "gate-exit":
        source.exit_error = error
    else:
        slots.finalize_error = error
    with pytest.raises(GenerationProviderError) as raised:
        await executor.execute(context, request=request)
    assert len(workspace.calls) == 1 and len(source.issued) == 1
    assert slots.completions == [True]
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert "canary" not in repr(raised.value)


async def test_runner_can_only_narrow_profile_and_deployment_budgets():
    executor, context, request, registry, _, _, workspace, _ = setup_executor()
    registry.runner = replace(
        registry.runner,
        process_limits=replace(registry.runner.process_limits, timeout_seconds=3.0),
        event_limits=replace(registry.runner.event_limits, max_output_tokens=20),
    )
    await executor.execute(context, request=request)
    assert workspace.calls[0]["timeout_seconds"] == 3.0
    assert workspace.calls[0]["max_output_tokens"] == 20


async def test_registry_fingerprint_drift_after_acquisition_never_launches():
    executor, context, request, registry, source, slots, workspace, log = setup_executor()
    registry.runner = replace(registry.runner, configuration_sha256="d" * 64)
    with pytest.raises(GenerationProviderError, match="^codex_binding_mismatch$"):
        await executor.execute(context, request=request)
    assert source.issued and not workspace.calls and "consume" not in log
    assert slots.completions == [True]


async def test_evidence_revision_ids_are_unique_and_derived_from_request():
    executor, context, request, _, source, _, _, _ = setup_executor()
    request = replace(
        request,
        evidence=(
            replace(request.evidence[0], asset_version_id=UUID(int=20)),
            replace(request.evidence[0], evidence_id=uuid4(), asset_version_id=UUID(int=20)),
            replace(request.evidence[0], evidence_id=uuid4(), asset_version_id=UUID(int=10)),
        ),
    )
    await executor.execute(context, request=request)
    assert source.issued[0][2] == (UUID(int=10), UUID(int=20))
