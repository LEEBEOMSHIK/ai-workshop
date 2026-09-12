import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationError,
    CodexAuthorizationErrorCode,
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexCurrentAuthorization,
    CodexExecutionGate,
    CodexExecutionPayload,
    EvidenceApproval,
    EvidenceClassification,
    EvidenceRevision,
    WorkspacePolicyBinding,
)
from ai_workshop.labs.rag.policies.domain import PolicyDecision, PolicyReasonCode
from ai_workshop.platform.identity.domain import UserRole

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _payload() -> CodexExecutionPayload:
    return CodexExecutionPayload(
        stdin=b'{"question":"synthetic question"}',
        developer_instructions=b"trusted developer instructions",
        output_schema=b'{"type":"object"}',
    )


def _intent(payload: CodexExecutionPayload | None = None) -> CodexCallIntent:
    sent = payload or _payload()
    return CodexCallIntent(
        actor_id=_uuid(1),
        request_id=_uuid(2),
        approval_id=_uuid(3),
        operation=CodexCallOperation.SEARCH,
        stage=CodexCallStage.GENERATE,
        configuration_version_id=_uuid(4),
        deployment_version_id=_uuid(5),
        generation_profile_id=_uuid(6),
        runner_ref="codex-cli-verified",
        runner_configuration_sha256="c" * 64,
        provider_model_id="approved-model",
        developer_instructions_sha256=sha256(sent.developer_instructions).hexdigest(),
        output_schema_sha256=sha256(sent.output_schema).hexdigest(),
        workspace_ids=(_uuid(10), _uuid(11)),
        workspace_policy_bindings=(
            WorkspacePolicyBinding(_uuid(10), _uuid(20)),
            WorkspacePolicyBinding(_uuid(11), _uuid(21)),
        ),
        installation_policy_version_id=_uuid(30),
        generation_disclosure_version="codex-external-v1",
        evidence_revisions=(
            EvidenceRevision(_uuid(40), "a" * 64, 1),
            EvidenceRevision(_uuid(41), "b" * 64, 1),
        ),
    )


def _snapshot(
    *,
    intent: CodexCallIntent | None = None,
    payload: CodexExecutionPayload | None = None,
) -> CodexCurrentAuthorization:
    sent = payload or _payload()
    bound = intent or _intent(sent)
    snapshots = tuple(
        (binding.workspace_id, binding.policy_version_id)
        for binding in bound.workspace_policy_bindings
    )
    return CodexCurrentAuthorization(
        actor_id=bound.actor_id,
        actor_role=UserRole.OWNER,
        actor_active=True,
        environment=DeploymentEnvironment.DEVELOPMENT,
        current_intent=bound,
        approved_by=bound.actor_id,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=1),
        revoked=False,
        consented=True,
        policy=PolicyDecision(
            allowed=True,
            reason_code=None,
            installation_policy_version_id=bound.installation_policy_version_id,
            workspace_policy_version_ids=tuple(
                binding.policy_version_id for binding in bound.workspace_policy_bindings
            ),
            workspace_policy_snapshots=snapshots,
        ),
        allowed_workspace_ids=bound.workspace_ids,
        evidence_approvals=tuple(
            EvidenceApproval(
                revision.revision_id,
                revision.content_sha256,
                (EvidenceClassification.PUBLIC if index == 0 else EvidenceClassification.SYNTHETIC),
                revision.approval_generation,
            )
            for index, revision in enumerate(bound.evidence_revisions)
        ),
        approved_payload_sha256=sent.digest(),
    )


class InMemoryAuthorizationSource:
    """Test-only model of a lock plus a durable, non-rollback reservation."""

    def __init__(
        self,
        snapshot: CodexCurrentAuthorization | None,
        *,
        lookup_error: Exception | None = None,
        consume_error: Exception | None = None,
        exit_error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.lookup_error = lookup_error
        self.consume_error = consume_error
        self.exit_error = exit_error
        self.in_context = False
        self._lock = asyncio.Lock()
        self._consumed: set[tuple[UUID, UUID, CodexCallStage]] = set()

    @asynccontextmanager
    async def locked_snapshot(
        self, intent: CodexCallIntent
    ) -> AsyncIterator[CodexCurrentAuthorization | None]:
        del intent
        if self.lookup_error is not None:
            raise self.lookup_error
        async with self._lock:
            self.in_context = True
            try:
                yield self.snapshot
            finally:
                self.in_context = False
                if self.exit_error is not None:
                    raise self.exit_error

    async def consume(self, approval_id: UUID, request_id: UUID, stage: CodexCallStage) -> bool:
        if self.consume_error is not None:
            raise self.consume_error
        key = (approval_id, request_id, stage)
        if key in self._consumed:
            return False
        self._consumed.add(key)
        return True


def _gate(source: InMemoryAuthorizationSource | None) -> CodexExecutionGate:
    return CodexExecutionGate(source=source, clock=lambda: NOW)


async def _fail_if_called(payload: CodexExecutionPayload) -> None:
    del payload
    pytest.fail("denied authorization invoked the operation")


async def test_success_passes_the_same_payload_inside_the_source_context() -> None:
    payload = _payload()
    intent = _intent(payload)
    source = InMemoryAuthorizationSource(_snapshot(intent=intent, payload=payload))

    async def operation(received: CodexExecutionPayload) -> str:
        assert source.in_context
        assert received is payload
        return "result"

    assert await _gate(source).run(intent, payload, operation) == "result"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"actor_id": None}, CodexAuthorizationErrorCode.UNAUTHENTICATED),
        ({"actor_id": _uuid(99)}, CodexAuthorizationErrorCode.ACTOR_NOT_AUTHORIZED),
        ({"approved_by": _uuid(99)}, CodexAuthorizationErrorCode.ACTOR_NOT_AUTHORIZED),
        ({"actor_role": UserRole.MEMBER}, CodexAuthorizationErrorCode.ACTOR_NOT_AUTHORIZED),
        ({"actor_active": False}, CodexAuthorizationErrorCode.ACTOR_NOT_AUTHORIZED),
        (
            {"environment": DeploymentEnvironment.PRODUCTION},
            CodexAuthorizationErrorCode.ENVIRONMENT_NOT_ALLOWED,
        ),
    ],
)
async def test_denied_actor_never_invokes_operation(
    change: dict[str, object], code: CodexAuthorizationErrorCode
) -> None:
    payload = _payload()
    intent = _intent(payload)
    snapshot = replace(_snapshot(intent=intent, payload=payload), **change)

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(snapshot)).run(intent, payload, _fail_if_called)

    assert raised.value.code is code


@pytest.mark.parametrize("source", [None, InMemoryAuthorizationSource(None)])
async def test_missing_authorization_source_fails_closed(
    source: InMemoryAuthorizationSource | None,
) -> None:
    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(source).run(_intent(), _payload(), _fail_if_called)
    assert raised.value.code is CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE


@pytest.mark.parametrize("failure_at", ["lookup", "consume"])
async def test_source_exception_is_sanitized_and_operation_is_not_run(
    failure_at: str,
) -> None:
    raw = RuntimeError("private question and secret value")
    source = InMemoryAuthorizationSource(
        _snapshot(),
        lookup_error=raw if failure_at == "lookup" else None,
        consume_error=raw if failure_at == "consume" else None,
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(source).run(_intent(), _payload(), _fail_if_called)

    assert raised.value.code is CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE
    assert str(raised.value) == "source_unavailable"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"consented": False}, CodexAuthorizationErrorCode.CONSENT_REQUIRED),
        ({"revoked": True}, CodexAuthorizationErrorCode.APPROVAL_REVOKED),
        ({"expires_at": NOW}, CodexAuthorizationErrorCode.APPROVAL_EXPIRED),
        (
            {"issued_at": NOW + timedelta(microseconds=1)},
            CodexAuthorizationErrorCode.APPROVAL_EXPIRED,
        ),
        (
            {"issued_at": NOW.replace(tzinfo=None)},
            CodexAuthorizationErrorCode.APPROVAL_EXPIRED,
        ),
    ],
)
async def test_invalid_current_approval_never_invokes_operation(
    change: dict[str, object], code: CodexAuthorizationErrorCode
) -> None:
    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(replace(_snapshot(), **change))).run(
            _intent(), _payload(), _fail_if_called
        )
    assert raised.value.code is code


async def test_non_utc_clock_fails_closed_before_operation() -> None:
    gate = CodexExecutionGate(
        source=InMemoryAuthorizationSource(_snapshot()),
        clock=lambda: NOW.astimezone(timezone(timedelta(hours=9))),
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await gate.run(_intent(), _payload(), _fail_if_called)
    assert raised.value.code is CodexAuthorizationErrorCode.APPROVAL_EXPIRED


async def test_current_policy_denial_wins_over_matching_version_ids() -> None:
    current = _snapshot()
    denied = replace(
        current.policy,
        allowed=False,
        reason_code=PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(replace(current, policy=denied))).run(
            _intent(), _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.POLICY_DENIED


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": _uuid(102)},
        {"approval_id": _uuid(103)},
        {"operation": CodexCallOperation.EVALUATION},
        {"stage": CodexCallStage.CONTEXTUALIZE},
        {"configuration_version_id": _uuid(104)},
        {"deployment_version_id": _uuid(105)},
        {"generation_profile_id": _uuid(106)},
        {"runner_ref": "other-runner"},
        {"provider_model_id": "other-approved-model"},
        {"developer_instructions_sha256": "c" * 64},
        {"output_schema_sha256": "d" * 64},
        {"installation_policy_version_id": _uuid(130)},
        {"generation_disclosure_version": "codex-external-v2"},
        {
            "workspace_policy_bindings": (
                WorkspacePolicyBinding(_uuid(10), _uuid(120)),
                WorkspacePolicyBinding(_uuid(11), _uuid(21)),
            )
        },
        {
            "evidence_revisions": (
                EvidenceRevision(_uuid(140), "a" * 64, 1),
                EvidenceRevision(_uuid(41), "b" * 64, 1),
            )
        },
    ],
)
async def test_changed_exact_binding_never_invokes_operation(
    change: dict[str, object],
) -> None:
    requested = _intent()
    snapshot = replace(_snapshot(), current_intent=replace(requested, **change))

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(snapshot)).run(
            requested, _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.INTENT_MISMATCH


@pytest.mark.parametrize(
    "payload",
    [
        replace(_payload(), stdin=b'{"question":"synthetic questioO"}'),
        replace(_payload(), developer_instructions=b"changed developer instructions"),
        replace(_payload(), output_schema=b'{"type":"array"}'),
    ],
)
async def test_any_transmitted_payload_change_is_denied(
    payload: CodexExecutionPayload,
) -> None:
    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(_snapshot())).run(
            _intent(), payload, _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.PAYLOAD_MISMATCH


def test_payload_digest_uses_unambiguous_length_framing_and_repr_hides_bytes() -> None:
    first = CodexExecutionPayload(b"a", b"bc", b"")
    second = CodexExecutionPayload(b"ab", b"c", b"")

    assert first.digest() == "74f2dff90c16bd75e74ea8ab93e0f683754b4ae5a7e2b6c960734cf5c656341a"
    assert first.digest() != second.digest()
    assert "bc" not in repr(first)


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_workspace_ids": (_uuid(10),)},
        {"allowed_workspace_ids": (_uuid(10), _uuid(10))},
        {"allowed_workspace_ids": (_uuid(10), _uuid(11), _uuid(99))},
    ],
)
async def test_current_scope_must_equal_the_whole_selected_scope(
    change: dict[str, object],
) -> None:
    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(replace(_snapshot(), **change))).run(
            _intent(), _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.SCOPE_MISMATCH


async def test_duplicate_selected_scope_is_invalid_even_when_snapshot_echoes_it() -> None:
    intent = replace(_intent(), workspace_ids=(_uuid(10), _uuid(10)))
    snapshot = replace(
        _snapshot(), current_intent=intent, allowed_workspace_ids=intent.workspace_ids
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(snapshot)).run(intent, _payload(), _fail_if_called)
    assert raised.value.code is CodexAuthorizationErrorCode.INVALID_INTENT


async def test_duplicate_workspace_policy_binding_is_invalid() -> None:
    intent = replace(
        _intent(),
        workspace_policy_bindings=(
            WorkspacePolicyBinding(_uuid(10), _uuid(20)),
            WorkspacePolicyBinding(_uuid(10), _uuid(21)),
        ),
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(replace(_snapshot(), current_intent=intent))).run(
            intent, _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.INVALID_INTENT


async def test_current_policy_version_mapping_must_match_the_intent() -> None:
    current = _snapshot()
    changed_policy = replace(
        current.policy,
        workspace_policy_version_ids=(_uuid(120), _uuid(21)),
        workspace_policy_snapshots=((_uuid(10), _uuid(120)), (_uuid(11), _uuid(21))),
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(replace(current, policy=changed_policy))).run(
            _intent(), _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.SCOPE_MISMATCH


@pytest.mark.parametrize(
    "approvals",
    [
        (EvidenceApproval(_uuid(40), "a" * 64, EvidenceClassification.PRIVATE, 1),),
        (
            EvidenceApproval(_uuid(40), "a" * 64, EvidenceClassification.PUBLIC, 1),
            EvidenceApproval(_uuid(40), "a" * 64, EvidenceClassification.PUBLIC, 1),
        ),
        (
            EvidenceApproval(_uuid(40), "c" * 64, EvidenceClassification.PUBLIC, 1),
            EvidenceApproval(_uuid(41), "b" * 64, EvidenceClassification.PUBLIC, 1),
        ),
        (
            EvidenceApproval(_uuid(40), "a" * 64, EvidenceClassification.PUBLIC, 3),
            EvidenceApproval(_uuid(41), "b" * 64, EvidenceClassification.PUBLIC, 1),
        ),
    ],
)
async def test_evidence_requires_unique_exact_public_or_synthetic_approval(
    approvals: tuple[EvidenceApproval, ...],
) -> None:
    snapshot = replace(_snapshot(), evidence_approvals=approvals)

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(InMemoryAuthorizationSource(snapshot)).run(
            _intent(), _payload(), _fail_if_called
        )
    assert raised.value.code is CodexAuthorizationErrorCode.EVIDENCE_NOT_APPROVED


async def _return(value: bool) -> bool:
    return value


async def test_connection_check_allows_empty_evidence_but_requires_payload_approval() -> None:
    payload = _payload()
    intent = replace(
        _intent(payload),
        operation=CodexCallOperation.CONNECTION_CHECK,
        evidence_revisions=(),
    )
    snapshot = replace(_snapshot(intent=intent, payload=payload), evidence_approvals=())

    assert await _gate(InMemoryAuthorizationSource(snapshot)).run(
        intent, payload, lambda received: _return(received is payload)
    )


async def test_contextualize_allows_empty_evidence_but_requires_payload_approval() -> None:
    payload = _payload()
    intent = replace(
        _intent(payload),
        stage=CodexCallStage.CONTEXTUALIZE,
        evidence_revisions=(),
    )
    snapshot = replace(_snapshot(intent=intent, payload=payload), evidence_approvals=())

    assert await _gate(InMemoryAuthorizationSource(snapshot)).run(
        intent, payload, lambda received: _return(received is payload)
    )


async def test_sequential_replay_invokes_operation_only_once() -> None:
    source = InMemoryAuthorizationSource(_snapshot())
    calls = 0

    async def operation(payload: CodexExecutionPayload) -> str:
        nonlocal calls
        del payload
        calls += 1
        return "ok"

    assert await _gate(source).run(_intent(), _payload(), operation) == "ok"
    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(source).run(_intent(), _payload(), operation)

    assert raised.value.code is CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED
    assert calls == 1


async def test_concurrent_use_invokes_operation_only_once() -> None:
    source = InMemoryAuthorizationSource(_snapshot())
    calls = 0

    async def operation(payload: CodexExecutionPayload) -> str:
        nonlocal calls
        del payload
        calls += 1
        return "ok"

    results = await asyncio.gather(
        _gate(source).run(_intent(), _payload(), operation),
        _gate(source).run(_intent(), _payload(), operation),
        return_exceptions=True,
    )

    assert calls == 1
    assert results.count("ok") == 1
    failures = [result for result in results if isinstance(result, CodexAuthorizationError)]
    assert len(failures) == 1
    assert failures[0].code is CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED


async def test_operation_failure_is_sanitized_and_keeps_approval_consumed() -> None:
    source = InMemoryAuthorizationSource(_snapshot())

    async def failing(payload: CodexExecutionPayload) -> None:
        del payload
        raise RuntimeError("private response and secret value")

    with pytest.raises(CodexAuthorizationError) as failed:
        await _gate(source).run(_intent(), _payload(), failing)

    assert failed.value.code is CodexAuthorizationErrorCode.OPERATION_FAILED
    assert str(failed.value) == "operation_failed"
    assert failed.value.__cause__ is None
    assert failed.value.__context__ is None
    with pytest.raises(CodexAuthorizationError) as replayed:
        await _gate(source).run(_intent(), _payload(), _fail_if_called)
    assert replayed.value.code is CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED


async def test_operation_cancellation_propagates_and_keeps_approval_consumed() -> None:
    source = InMemoryAuthorizationSource(_snapshot())
    started = asyncio.Event()

    async def blocked(payload: CodexExecutionPayload) -> None:
        del payload
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(_gate(source).run(_intent(), _payload(), blocked))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(CodexAuthorizationError) as replayed:
        await _gate(source).run(_intent(), _payload(), _fail_if_called)
    assert replayed.value.code is CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED


async def test_expiry_during_consume_prevents_operation_and_still_consumes() -> None:
    current_time = [NOW]

    class ExpiringSource(InMemoryAuthorizationSource):
        async def consume(self, approval_id: UUID, request_id: UUID, stage: CodexCallStage) -> bool:
            consumed = await super().consume(approval_id, request_id, stage)
            current_time[0] = NOW + timedelta(minutes=1)
            return consumed

    source = ExpiringSource(_snapshot())
    gate = CodexExecutionGate(source=source, clock=lambda: current_time[0])

    with pytest.raises(CodexAuthorizationError) as expired:
        await gate.run(_intent(), _payload(), _fail_if_called)
    assert expired.value.code is CodexAuthorizationErrorCode.APPROVAL_EXPIRED

    current_time[0] = NOW
    with pytest.raises(CodexAuthorizationError) as replayed:
        await gate.run(_intent(), _payload(), _fail_if_called)
    assert replayed.value.code is CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED


def _chained_authorization_error() -> CodexAuthorizationError:
    try:
        raise RuntimeError("private source details")
    except RuntimeError as raw:
        try:
            raise CodexAuthorizationError(CodexAuthorizationErrorCode.POLICY_DENIED) from raw
        except CodexAuthorizationError as error:
            return error


@pytest.mark.parametrize("failure_at", ["lookup", "consume", "exit"])
async def test_typed_source_error_preserves_code_without_raw_chain(
    failure_at: str,
) -> None:
    chained = _chained_authorization_error()
    source = InMemoryAuthorizationSource(
        _snapshot(),
        lookup_error=chained if failure_at == "lookup" else None,
        consume_error=chained if failure_at == "consume" else None,
        exit_error=chained if failure_at == "exit" else None,
    )

    with pytest.raises(CodexAuthorizationError) as raised:
        await _gate(source).run(_intent(), _payload(), lambda payload: _return(True))

    assert raised.value.code is CodexAuthorizationErrorCode.POLICY_DENIED
    assert str(raised.value) == "policy_denied"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
