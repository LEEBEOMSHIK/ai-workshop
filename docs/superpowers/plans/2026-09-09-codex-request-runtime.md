# Codex request-bound runtime implementation plan

> Agentic workers: use superpowers:subagent-driven-development and test-driven-development. Independent review follows each task.

**Goal:** Execute a request-scoped Codex generation through real current authorization and bounded durable capacity.
**Architecture:** Existing strict wire/workspace/Windows Job adapters stay intact. PostgreSQL derives exact current intents and reserves per-runner capacity. An async coordinator holds authorization locks until its owned synchronous worker completes.
**Tech Stack:** Existing Python, SQLAlchemy/PostgreSQL, asyncio/threading, pytest. No dependency added.
**Spec:** `docs/superpowers/specs/2026-09-07-personal-codex-exec-rag-design.md` §4/6/7.

## Global constraints

- Main-only existing dirty checkout; no worktree, staging, commit/push. Preserve unrelated changes.
- No real CLI/network/model calls by implementer. No user DB or environment changes. DB tests must use guarded disposable integration database helper.
- Owner/development/public-or-synthetic/explicit consent only. No client-supplied actor/intent/hash/path authority.
- Original provider behavior unchanged. Requested model never becomes observed identity. Codex-only None exception is approved.
- No raw input/draft/event/reasoning/auth/path persistence. Body-free digests and safe state only.
- Main alone integrates and marks WORKBOARD. No worker-spawned subagents.
- Application API/UI activation follows this plan's reviewed substrate; do not claim whole RAG readiness here.

## Task 1: Current intent issuance and durable process capacity

Files under `backend/src/ai_workshop/labs/rag/generation/`:
modify `codex_authorization.py`, `codex_approval_codec.py`, `codex_approval_repository.py`, `codex_workspace.py`;
create `codex_request.py`, `codex_slots.py`, `codex_slot_models.py`, `codex_slot_repository.py`.
Register new model in `backend/src/ai_workshop/shared/model_registry.py` and `backend/alembic/env.py` only as required by existing pattern.
Create `backend/alembic/versions/0028_codex_execution_slots.py` (down_revision 0027).
Tests: existing unit `test_codex_authorization.py`, `test_codex_approval_codec.py`, `test_codex_command.py`,
`test_codex_workspace.py`; integration `test_codex_approval_storage.py`; new unit `test_codex_request.py`,
integration `test_codex_execution_slots.py`. Fixture constructor edits confined to tests mentioning CodexCallIntent.

Interfaces:
```python
# required last field: existing construction sites must explicitly supply it
CodexCallIntent.runner_configuration_sha256: str

@dataclass(frozen=True, slots=True)
class CodexRequestContext:
    actor_id: UUID
    request_id: UUID
    operation: CodexCallOperation
    configuration_version_id: UUID
    workspace_ids: tuple[UUID, ...]
    input_classification: EvidenceClassification
    consented: bool
    disclosure_version: str

# source constructor gains trusted runner registry injection; absent registry fails closed
async def issue_request(self, context: CodexRequestContext, *, stage: CodexCallStage,
    payload: CodexExecutionPayload, evidence_revision_ids: tuple[UUID, ...],
    ttl: timedelta) -> CodexCallIntent: ...

@dataclass(frozen=True, slots=True)
class CodexExecutionLease:
    id: UUID
    request_id: UUID
    runner_ref: str
    configuration_sha256: str

class CodexExecutionSlots(Protocol):
    async def acquire(self, *, runner_ref: str, configuration_sha256: str,
        max_concurrent: int, request_id: UUID) -> CodexExecutionLease | None: ...
    async def complete(self, lease: CodexExecutionLease, *,
        process_termination_verified: bool) -> None: ...

# safe independent process evidence; defaultFalse for unknown/legacy fake results
CodexWorkspaceResult.process_termination_verified: bool = False
# workspace.run adds optional max_output_tokens; exact int positive, only narrows registry budget
```

- [ ] Add RED tests: missing/malformed fingerprint, codec v1 rejection, changed current registry fingerprint prevents issue/gate, current issuance derives DB policy/profile/asset hashes and does not bless caller payload hashes, missing consent/private input/mixed unauthorized evidence reject.
```python
legacy = encode_intent(valid_intent)
legacy['version'] = 1
with pytest.raises(ValueError):
    decode_intent(legacy)
assert encode_intent(valid_intent)['version'] == 2
```
- [ ] Implement required fingerprint and strict codec v2. Refactor trusted binding derivation shared by `_current`/`issue_request`; caller's request IDs/scope/stage are request binding, not a substitute for current owner/policy/config/profile/registry/revision loads. `issue_request` calls existing issue_call with actual payload.digest; `_current` independently rechecks prior approval. Bound prompt/schema must match actual supplied payload. No fake approval/UUID values in production.
- [ ] Add RED isolated SQL tests for simultaneous acquisitions from distinct repository/engine instances at capacity1, completed release, fingerprint mismatch while unresolved, unknown cleanup persistence across fresh instances, exact owned lease comparison, malformed limits/digests, migration upgrade/downgrade.
```python
first = await slots_a.acquire(**request)
assert first is not None
assert await slots_b.acquire(**request) is None
await slots_a.complete(first, process_termination_verified=False)
assert await slots_b.acquire(**request) is None
await slots_a.complete(first, process_termination_verified=True)
assert await slots_b.acquire(**request) is not None
```
- [ ] Implement named per-runner transaction lock and durable reservation insert/commit. Count unresolved rows by stable runner_ref (not fingerprint); reject mixed fingerprint/capacity snapshots while unresolved. Exact owned lease delete only after termination True; no automatic age reclaim, no raw exception leakage. Add max_concurrent snapshot column for consistent comparison. Model constraints named; migration creates only new table/index, rollback only this table.
- [ ] Add RED workspace tests for early no-launch True; successful/failed stream with exact cleanupTrue+activeint0 True; invoked exception/unknown stream False; file cleanup failure preserves known process termination but still fails result. Narrow output budget using dataclasses.replace of event_limits, never mutate registry/config digest. Reject bool/nonpositive/widening arguments before launch; max_output_tokens None retains existing behavior.
- [ ] Implement and run scoped pytest/mypy/Ruff; self-review, report and freeze. Tests use synthetic data only. Record isolated SQL test invocation and actual DB/no-DB evidence separately.

## Task 2: Request coordinator and GenerationRuntimePort adapter

Files: create `generation/codex_execution.py`, `generation/codex_runtime.py`; tests
`backend/tests/unit/labs/rag/generation/test_codex_execution.py`, `test_codex_runtime.py`.
Existing runtime resolver/search/API not modified in this task. Uses Task1 interfaces verbatim.

Interfaces:
```python
class CodexPassiveReadiness(Protocol):
    async def health(self, *, context: CodexRequestContext,
        profile: GenerationProfile) -> ProviderHealthResult: ...

class CodexRequestExecutor:
    # injected: registry, source (issue_request + gate source), slots, workspace, UTC clock
    async def execute(self, context: CodexRequestContext, *,
        request: ContextualizationRequest | GenerationRequest) -> CodexWorkspaceResult: ...
class CodexExecRuntime:
    # immutable context/profile, executor and CodexPassiveReadiness constructor
    async def health(self) -> ProviderHealthResult: ...
    async def contextualize(self, request: ContextualizationRequest) -> ProviderContextualizationResult: ...
    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult: ...
```

- [ ] RED coordinator tests prove acquire→issue_request→gate (consume)→worker→finalize ordering, no launch on denial/full slots, exact fingerprint/payload bytes forwarded, per-stage distinct approvals, narrowed profile/deployment/runner limits, failure/cancel/repeatedcancel joins worker before source lock exit/lease release. Fake sync worker uses threading.Event barriers, not sleeps.
```python
task = asyncio.create_task(executor.execute(context, request=request))
await worker_started.wait()
task.cancel()
assert not lease_released.is_set()
allow_cleanup.set()
with pytest.raises(asyncio.CancelledError):
    await task
assert lease_released.is_set()
```
- [ ] Implement fixed prompt builder, trusted source, slots and gate injection; build payload once. Acquire capacity before issue/consume. Gate and consume must stay in the SAME owned async task (source task-scoped reservation contract); run only workspace synchronously in owned thread. Shield the whole owned operation including gate exit and lease finalization while handling repeated caller cancellation; set exact cancellation event then wait. This also prevents cancellation during DB finalization from releasing policy locks before the worker ends. Release known no-launch or proven terminated leases only; uncertainty/errors retain. Errors after successful cleanup still fail request, never retry.
- [ ] RED runtime tests for passive health0launch, missing readiness, requested/observedNone, observed mismatch rejection; valid answered/insufficient/context results; malformed schema/usage/cleanup fail. Immutable context rejects request profile/deployment mismatch. Evidence revision IDs derived from request evidence without accepting arbitrary source hashes.
- [ ] Implement adapter against unchanged generic port. Strict new wire parser and contextual parser only. Execution metadata uses configured requested identity, token usage and measured monotonic latency. Map safe failure codes without raw exception chains. Passive readiness source owns stored exact verification; no hardcoded readyTrue.
- [ ] Runtime generate/contextualize each require passive health before execute, so callers cannot bypass readiness by skipping health. Connection verification uses coordinator directly with CONNECTION_CHECK and the same issue/gate, not a runtime-ready override. Only context SEARCH/CONNECTION_CHECK are currently used; future evaluation must supply explicit owner context.
- [ ] Run scoped tests/mypy/Ruff and report/freeze for independent review.

## Subsequent integrated activation

After the above interfaces freeze, execute a separate plan for search/admin API composition, per-question
attestation and Codex disclosure, exact synthetic verification persistence/passive readiness, stage audit,
frontend settings/conversation controls and current domain setup. Actual DB migration/setup and live tests
remain main-owned precise operations. This is continuous work toward user testing, not a request to resume.
