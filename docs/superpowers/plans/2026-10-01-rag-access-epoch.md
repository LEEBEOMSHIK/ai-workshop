# RAG Server Access Epoch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Status: user approved plan and Native inline implementation on2026-10-02; partially implemented. 2026-10-08 retrospective review recovered linked terminal receipts for the identified original controls; old DPAPI journal absence is not a mandatory restart or an impossible-history prerequisite. The bounded internal history reader/gate and complete secured controller remain implementation work. Preserve the historical [Oct02 implementation and blocker evidence](../../worklogs/2026-10-02-rag-access-epoch-implementation.md) as that date's observation. No live action is authorized by this document.

**Goal:** End the frozen legacy alias invocation's ability to apply late writes by replacing its accepting Elasticsearch JVM with a protected access epoch, then persist exact v2 termination evidence.
**Architecture:** Keep generic TLS/client/secret-launch adapters under infrastructure and RAG ownership/proof/state under Labs/RAG. A fixed Windows controller reserves every external action durably before execution, retires the original and bootstrap JVMs, and verifies one final secured server on the original volume. Recovery closes the operation and writes its receipt atomically; release and fresh DB-truth parity remain separate.
**Tech Stack:** Existing official Windows Python 3.13.15/backend `.venv`, SQLAlchemy/PostgreSQL 17, Alembic, Elasticsearch client 9.5.x/server 9.5.2, Windows CurrentUser DPAPI, fixed Docker/Compose adapters; no dependency or model upgrade.
**Spec:** `docs/superpowers/specs/2026-10-01-rag-access-epoch-design.md`; `docs/decisions/0033-rag-access-epoch.md`.

## Global Constraints

- User approved design and planning only. Prepare code/tests offline after plan approval; actual migration, CA/key/password generation, process shutdown, container removal/recreation and gate changes require a later concrete approval.
- Preserve original DB/account/documents/assets/SHA/index UUIDs/counts/settings/provenance/configurations/queue and IDE/Codex/frontend. No new application environment, DB/account, reindex, queue purge, volume copy/init/delete, image upgrade, new Compose project, prune or `down -v`.
- Existing operation stays `legacy_unknown/open`, claim `frozen/revision1`, receipt0 until an approved live operation. Baseline current unrelated modified/untracked first-question/alias files and preserve them; only root stages/commits/pushes or closes WORKBOARD.
- Before code, recheck migration inventory: `0062_rag_access_epoch` follows `0061_alias_recovery` (0062 currently free); do not edit0061 or assign a conflicting revision.
- Unknown executor/action/security state keeps frozen; no TTL/silence takeover, guessed inspect completion, generic secret broker, insecure HTTP/certificate fallback, or auth-off rollback after retirement/floor commitment.
- No secrets, Authorization, private keys, secret command/environment/response bytes or their hashes in logs/proofs/events/test fixtures/Git. Synthetic secrets exist only in transient fake objects. Public certificate/nonsecret manifest hashes and key IDs are permitted.
- Unit tests use fake clocks/processes/Docker/ES/DPAPI and no model/network. Original DB verification is opt-in after separately approved migration and is outer-rollback only; do not equate SAVEPOINT evidence with committed concurrency or physical lost-commit proof.

## Review Focus

- 2026-10-08 추가 발견: 단일 ISSUE_ROLE_KEY 순서만으로 세 역할 발급과 lost-ACK 폐기·교체를 기록할 수 없다. 상위 순서를 유지하는 역할별 append-only child reservation/settlement와 후속 migration을 먼저 구현·독립 검토한다. 기존0062 수정·실제 발급 선행 실행은 금지한다.

- Lost stop acknowledgement followed by missing old ID must not fabricate its stop time; Task4 barrier/readback tests require durable stop evidence before retirement.
- Old Compose up and daemon-delegated work may outlive a client process; Task4 rejects unresolved delegation even when TCP/process listings are empty.
- Hidden historical security keys may have submitted work to bootstrap JVM; Task4 always settles and retires bootstrap JVM before final admission.
- Parent shell/config reload/stale queue payload must not gain fresh capability; Tasks3/5 prove immutable startup client and new reserve/dispatch CAS.
- Restored DB/config can lower recorded floor; Tasks2/3 require monotonic DB floor plus protected local floor anchor and reject mismatched/unknown startup state.

## File and interface conventions

All paths below are exact repository-relative file paths; generic infrastructure adapters contain no Labs/RAG imports.
Run pytest from **backend cwd**, using the existing official `.venv` Python; repository-root cwd would accidentally load the original `.env` into existing unit fixtures. Define these session-local helpers in that cwd; they clear inherited AI_WORKSHOP settings only inside a fresh test Python child, never the parent shell, and forward exact pytest arguments. The original helper enables only the explicitly approved original rollback opt-in. No test command is executed during planning. RED/GREEN use the same command and inspect its exit code.

```powershell
$epochPytestCode = "import os,runpy,sys; [os.environ.pop(k) for k in list(os.environ) if k.upper().startswith('AI_WORKSHOP_')]; sys.argv=['pytest',*sys.argv[1:]]; runpy.run_module('pytest',run_name='__main__')"
function Invoke-EpochPytest { & .\.venv\Scripts\python.exe -c $epochPytestCode @args }
$originalEpochPytestCode = $epochPytestCode.Replace("sys.argv=['pytest'", "os.environ['AI_WORKSHOP_VERIFY_ORIGINAL_ACCESS_EPOCH']='1'; sys.argv=['pytest'")
function Invoke-OriginalEpochPytest { & .\.venv\Scripts\python.exe -c $originalEpochPytestCode @args }
```
Shared synthetic `backend/tests/unit/labs/rag/indexing/access_epoch_fixtures.py` defines `EpochCase` with `claim`, UTC-controlled `now`, `v1`, exact-valid `v2`, typed `prepared/verified`, `secured_identity` and `permissions`. Its `repo`, `launcher`, `controller`, and `service` are the actual production classes under test; only external session/commit (`db`), clock, OS/DPAPI/process/Docker/ES/queue ports (`control/runtime`) are fakes. Later-task objects are composed only in their owning tests. `case()` returns fresh IDs/manifests, no actual secrets/documents. Commit-response loss is injected at the fake DB port; persisted states are read through the actual repository or fake DB records. Never implement desired behavior in a fake SUT.
Only root integrates task deltas; each task's final checkpoint is a fresh review and root-only scoped commit decision. No subagent Git writes.

### Task 1: Exact v2 proof, immutable manifest types and preserved v1 union

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/access_epoch_types.py`, `backend/tests/unit/labs/rag/indexing/access_epoch_fixtures.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_types.py`; modify `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_types.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_repository.py` proof decoder/receipt union; test existing `backend/tests/unit/labs/rag/indexing/test_alias_recovery.py`.
**Consumes:** `FrozenAliasClaim`, `AliasOperationSnapshot`, unchanged `TerminationProof.facts()/validate(claim)` and `digest(dict[str, object]) -> str`.
**Produces:** frozen `LocalAccessEpochTerminationProof` with `validate(claim: FrozenAliasClaim, epoch: VerifiedAccessEpoch, *, now: datetime) -> None`, `facts() -> dict[str, object]`, `sha256: str`; `type AliasTerminationProof = TerminationProof | LocalAccessEpochTerminationProof`; `decode_termination_proof(facts: dict[str, object]) -> AliasTerminationProof` for trusted persisted facts only.
`AccessEpochBinding` carries exact claim/store/cluster/epoch/execution/positive ordinal; `VerifiedAccessEpoch` carries binding, previous floor, exact proof facts and immutable named manifests. `PreparedAccessEpoch` carries binding and original deployment identity; `AccessEpochFloor` carries cluster/store/ordinal/epoch/final container/stable node/route/auth/config digests.
`CutoverActionKind` is fixed enum `STOP_REGISTERED_APPS, STOP_OLD, RETIRE_OLD, PREPARE_TLS, START_BOOTSTRAP, BOOTSTRAP_ADMIN, REVOKE_HISTORICAL, ISSUE_ROLE_KEY, STOP_BOOTSTRAP, RETIRE_BOOTSTRAP, START_SECURED, START_REGISTERED_APPS, VERIFY_ACCESS`; `ActionOutcome = pending|settled|unknown`. `ReservedCutoverAction` and `ControlSettlement` carry execution/action IDs, ordinal, expected identity, executor generation, nonsecret manifest and outcome.

- [ ] **Step 1: Write failing strict decoding/validation tests**, using this core plus parameterized omitted/extra field, bool-as-int, 2.0/string version, invalid UUID/digest/identifier, naive/non-UTC times, future verification, swapped identity, equal retirement/start and manifest/claim/floor mismatch cases.
```python
def test_v2_exact_union_and_causal_boundary():
    c = case()
    assert decode_termination_proof(c.v1.facts()) == c.v1
    assert decode_termination_proof(c.v2.facts()) == c.v2
    c.v2.validate(c.claim, c.verified, now=c.now)
    with pytest.raises(AliasRecoveryError, match="proof_invalid"):
        decode_termination_proof(c.v2.facts() | {"client_inventory_sha256": "a" * 64})
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_access_epoch_types.py -q` → missing v2 API/failed exact validation; existing v1 baseline remains usable.
- [ ] **Step 3: Implement exact schema** below; strict JSON primitive types before parsing, no coercion of schema/kind/numbers/UUID text/UTC text and no fake v1 fields. Preserve valid v1 facts/digest semantics and reserved `{}` receipt.
  UUID text: `request_id, operation_id, actor_id, access_epoch_id, execution_id`; positive integer excluding bool: `gate_revision, minimum_access_epoch`; integer exactly2: `schema_version`; kind exactly `local_single_node_access_epoch`.
  Validated identifiers: `store_id` uses existing store grammar; `cluster_uuid, stable_node_id, old_ephemeral_id, new_ephemeral_id` use existing identifier grammar.
  Lowercase64hex: `snapshot_sha256, old_container_id, new_container_id, daemon_identity_sha256, original_volume_identity_sha256, protected_mount_sha256, protected_image_sha256, old_config_sha256, new_config_sha256, old_deployment_sha256, new_deployment_sha256, route_policy_sha256, tls_public_ca_sha256, auth_policy_sha256, credential_deployment_sha256, deployment_history_sha256, control_settlement_sha256`.
  UTC text: `old_jvm_start_at, old_server_stopped_at, old_container_retired_at, new_server_started_at, new_jvm_start_at, access_verified_at, verified_at`.
  Require old/new container and ephemeral IDs differ; stable node/cluster/physical volume/image remain identical; `old_jvm_start ≤ old_stop ≤ retirement < final_secured_start ≤ new_jvm_start ≤ access_verified ≤ verified ≤ now`. Equal stop/retirement needs independently ordered settled action IDs. Epoch ordinal equals proof minimum and exceeds previous floor.
- [ ] **Step 4: GREEN:** same command plus `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_alias_recovery.py -q` → all pass; v1 bytes/facts and reserved meanings unchanged.
- [ ] **Step 5: Review checkpoint:** typed union/exact-schema review; root decides scoped commit `feat: define strict RAG access epoch proof`.

### Task 2: Durable epoch, external action reservation, monotonic floor and atomic receipt

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/access_epoch_models.py`, `backend/src/ai_workshop/labs/rag/indexing/access_epoch_repository.py`, `backend/alembic/versions/0062_rag_access_epoch.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_repository.py`, `backend/tests/integration/labs/rag/indexing/test_original_access_epoch.py`; modify `backend/src/ai_workshop/labs/rag/indexing/alias_models.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_repository.py`, `backend/alembic/env.py` model registration; update existing original0061 integration fixture to accept explicitly approved0062.
**Consumes:** Task1 types, existing `_owner`, exact gate/snapshot checks and0061 release/deferred integrity semantics.
**Produces:** `AccessEpochRepositoryPort.acquire(claim: FrozenAliasClaim, original: OriginalDeploymentIdentity) -> PreparedAccessEpoch`; `reserve_action(epoch: PreparedAccessEpoch, kind: CutoverActionKind, expected: ControlExpectedIdentity) -> ReservedCutoverAction`; `settle_action(action: ReservedCutoverAction, result: ControlSettlement) -> None`; `readback(claim: FrozenAliasClaim) -> AccessEpochReadback`; `mark_verified(epoch: PreparedAccessEpoch, evidence: VerifiedAccessEpoch) -> AccessEpochFloor`; `close_access_epoch(claim: FrozenAliasClaim, proof: LocalAccessEpochTerminationProof) -> AliasRecoveryReceipt`; `floor(binding: IndexBinding) -> AccessEpochFloor | None` (all async).
`AccessEpochReadback` includes exact epoch/execution/phase/actions/floor/receipt; `OriginalDeploymentIdentity` and `ControlExpectedIdentity` are immutable Task1 types containing only allowlisted expected daemon/container/image/volume/network/config/process-generation identities.

- [ ] **Step 1: Write failing repository tests** for exact replay, competing actor/request/operation, two recover entrants, unknown action, revoked owner and confirmed-close winner; create rollback-only SQL tests with malformed v2 JSON, mismatched FK/manifest, deleted/updated events, floor decrease and downgrade guard.
```python
async def test_close_v2_atomic_exact_and_lost_commit_readback():
    c = case()
    await c.repo.mark_verified(c.prepared, c.verified)
    c.db.lose_next_commit_response = True
    with pytest.raises(AliasRecoveryError, match="commit_unknown"):
        await c.repo.close_access_epoch(c.claim, c.v2)
    r = await c.repo.readback(c.claim)
    assert (r.operation_state, r.phase, r.receipt.proof) == ("closed", "receipted", c.v2)
    assert r.gate_state == "frozen" and c.control.mutations == []
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_access_epoch_repository.py -q` → missing APIs/failed atomic contract. Integration tests remain skipped without explicit original verification opt-in.
- [ ] **Step 3: Implement schema and short transactions.** Add `rag_access_epochs` (exact claim binding, immutable original/verified manifests, ordinal, phase), `rag_access_epoch_executions` (one execution/epoch, immutable generation identity), append-only `rag_access_epoch_events` (sequence/action kind/expected identity/reservation and settlement facts), `rag_access_epoch_floors` (nondecreasing current secured identity). Phase: prepared→old_stopped→old_retired→secured_started→verified→receipted.
  Name `uq_rag_access_epoch_active_cluster` partial unique on cluster where phase≠receipted; `uq_rag_access_epoch_cluster_ordinal`, `uq_rag_access_epoch_request`, `uq_rag_access_epoch_execution`, `uq_rag_access_epoch_event_sequence`; named binding FKs to operation/user and epoch/execution; `ck_rag_access_epoch_phase`, `ck_rag_access_epoch_ordinal`, `ck_rag_access_epoch_event_outcome`, `ck_rag_access_epoch_manifest_digest`, `ck_rag_access_epoch_floor` enforce typed/bound records.
  `guard_rag_access_epoch_event` denies event UPDATE/DELETE; `guard_rag_access_epoch_transition` requires prior durable settled action and exact execution; `guard_rag_access_epoch_floor` denies decreases/delete/identity substitution. Reserve action commit precedes I/O; derive pending→unknown or pending/unknown→settled by appending bound settlement events, never by updating/deleting a reservation; require exact reconciled generation evidence; no uncertain action reissue. Acquire locks owner→gate→operation→execution; then floor/epoch in the same fixed order. Never hold row locks across OS/ES/Docker I/O.
  Extend `ck_rag_alias_receipt_proof` to explicit reserved-v1/restart-v1/access-epoch-v2 branches; add nullable receipt epoch/execution FK columns with `ck_rag_alias_receipt_epoch_binding`, exact v2 JSON key/type/UUID/digest/UTC/causality guards and immutable proof-manifest equality. Canonical nonsecret JSON serializer uses sorted ASCII keys, compact separators and UTC microsecond strings; SQL digest equality must use identical canonical bytes, not JSONB display whitespace.
  Preserve0061 deferred operation/receipt integrity and gate release; add deferred `check_rag_access_epoch_receipt_integrity` so exact verified epoch/execution→receipted, immutable v2 receipt and operation closure share one commit/closed_at. `mark_verified` commits authenticated floor; closure does not release. Downgrade rejects any epoch/floor/v2 receipt; no deletion of evidence to permit it.
- [ ] **Step 4: GREEN:** same offline command → pass. Later, after separately approved0062 migration, `Invoke-OriginalEpochPytest -c pyproject.toml tests/integration/labs/rag/indexing/test_original_access_epoch.py -q -m integration` tests existing owner/profile/DB in guarded outer rollback with `SET CONSTRAINTS ALL IMMEDIATE`; COMMIT rejected.
- [ ] **Step 5: Review checkpoint:** DBA reviews actual SQL constraints and transaction order; distinguish model barriers/rollback DB tests from committed multi-connection races; root decides `feat: persist atomic RAG access epoch recovery`.

### Task 3: Startup TLS configuration, private credential store and fixed child launcher

**Files:** Create `backend/src/ai_workshop/infrastructure/search/access_credentials.py`, `backend/src/ai_workshop/infrastructure/local/credential_store_windows.py`, `backend/src/ai_workshop/infrastructure/local/service_launcher.py`, `backend/src/ai_workshop/labs/rag/indexing/access_epoch_admission.py`, `backend/tests/unit/infrastructure/search/test_access_credentials.py`, `backend/tests/unit/infrastructure/local/test_service_launcher.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_admission.py`; modify `backend/src/ai_workshop/config.py`, `backend/src/ai_workshop/infrastructure/search/elasticsearch.py`, `backend/src/ai_workshop/labs/rag/indexing/tracking_service.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_service.py`, `backend/src/ai_workshop/labs/rag/indexing/recovery.py`, `backend/src/ai_workshop/worker.py`, `backend/src/ai_workshop/main.py`, existing config/factory tests.
**Consumes:** Task2 floor readback through injected RAG admission port; generic infrastructure never imports Labs/RAG. Existing `create_elasticsearch(settings: Settings) -> AsyncElasticsearch` stays callable.
**Produces:** Settings `elasticsearch_ca_certs: Path | None`, `elasticsearch_api_key: SecretStr | None` (`repr=False`), `elasticsearch_access_epoch_id: UUID | None`, `elasticsearch_access_epoch: int | None` (strict positive), `elasticsearch_role: reader|writer|collector|None`. `CredentialEnvelope(epoch_id: UUID, ordinal: int, role: ServiceRole, key_id: str, secret: SecretStr)` never serializes secrets to audit.
`type ServiceRole = Literal["reader", "writer", "collector"]`; `type RegisteredService = Literal["api", "worker", "beat", "collector", "parity"]`. Generic frozen `SecuredStoreIdentity` carries store_id, cluster_uuid, ordinal, epoch_id, container_id, stable_node_id and route/auth/config/public-CA digests; `ChildLifetime` carries PID/creation timestamp/module/role/epoch nonsecret facts and `environment_epoch: int` (the injected ordinal only, never the environment). Infrastructure contains no RAG proof/floor type.
`WindowsCredentialStore.put(envelope: CredentialEnvelope) -> None`, `load(epoch_id: UUID, role: ServiceRole) -> CredentialEnvelope`, `read_floor_anchor() -> SecuredStoreIdentity | None`, `advance_floor_anchor(floor: SecuredStoreIdentity) -> None`; RAG adapter converts Task2 floor. `launch_registered(role: RegisteredService, epoch: SecuredStoreIdentity) -> ChildLifetime`; `AccessEpochAdmission.verify(settings: Settings) -> None` async before startup and every new writer admission, outside existing source/build lock sequences.

- [ ] **Step 1: Write failing isolation tests**, plus DPAPI/ACL denial, wrong epoch/role/module, secret stderr/error serialization, parent-env/config reload, stale floor, HTTP/wrong CA/hostname and incomplete secure settings cases.
```python
def test_launcher_only_injects_matching_fresh_child_secret(monkeypatch):
    c = case()
    before = dict(os.environ)
    child = c.launcher.launch_registered("worker", c.secured_identity)
    assert dict(os.environ) == before
    assert child.role == "writer" and child.environment_epoch == c.secured_identity.ordinal
    assert c.runtime.existing_callback.credential is None
    assert c.runtime.secret_appears_in_public_output is False
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/infrastructure/search/test_access_credentials.py tests/unit/infrastructure/local/test_service_launcher.py tests/unit/labs/rag/indexing/test_access_epoch_admission.py -q` → missing adapters/security enforcement.
- [ ] **Step 3: Implement startup snapshot and private launch.** HTTP remains compatible only when no DB/protected floor exists and no secure generation is configured; public secured Settings validate HTTPS+explicit CA+epoch identity/ordinal together but may contain no key/role: Alembic, original DB-only verification and beat must still load the public `.env`. Key/role must be either both absent or a matching pair; `create_elasticsearch` and actual ES admission require HTTPS+explicit CA+key+epoch+role together and reject absent capability. Non-ES entrypoints verify the floor through the protected launcher/DB adapter without creating an ES client. Client construction verifies certificates/hostname, forbids HTTP/auth-off/wrong identity below floor and omits raw validation inputs. Add tests that DB-only Settings/Alembic configuration/beat startup succeed with public secured settings and no key, while ES factory/alias/parity admission refuse that same Settings; an anonymous ES client must never be obtained through this exception. ES client obtains one startup key; no file auto-discovery, hot-reload, insecure retry or credential acquisition on callback.
  Store secrets only at fixed root-relative `.local-data/access-epoch/private/<epoch UUID>/<role>.dpapi`, private TLS files in same owner-controlled subtree; reject reparse/ancestor escape. CurrentUser `CryptProtectData/CryptUnprotectData` with `CRYPTPROTECT_UI_FORBIDDEN`, no `LOCAL_MACHINE`; protected owner/SYSTEM-only DACL, disabled inherited broad grants, noninteractive failure refuses. Atomic write/replace then verify owner/DACL; no raw process environment/secret serialization.
  Fixed child executable is original `backend/.venv/Scripts/python.exe`; API=`-m uvicorn ai_workshop.main:app --loop ai_workshop.shared.asyncio_policy:create_selector_event_loop --host 127.0.0.1 --port 18000`, worker/beat=`-m celery -A ai_workshop.worker:celery_app worker --pool=solo --loglevel=INFO` or `beat --loglevel=INFO --schedule .local-data/celerybeat-schedule` with original registered flags/schedule unchanged, collector=`-m ai_workshop.labs.rag.indexing.alias_recovery_cli`; parity uses a fixed new `backend/src/ai_workshop/labs/rag/indexing/access_epoch_parity_cli.py` with only existing profile UUID argument and original settings. Role→module allowlist enforced: api→reader, worker/parity→writer, collector→collector, beat→no ES key. Inject key only via `Popen(env=child_env)` with hidden window, never shell SetEnvironment/parent mutation. No role fallback; any changed ES call requires explicit role audit.
  `.env` receives only HTTPS/public CA/epoch reference in later live cutover. Private bootstrap administrator remains controller-only. After final secured identity verification, advance and read back the protected local monotonic floor anchor, then mark the DB epoch verified/floor in a short transaction; never admit/start applications between these steps. `mark_verified` requires matching nonsecret anchor evidence. Anchor-write failure leaves DB unverified; lost anchor/DB response requires exact readback; mismatches block rather than lower either floor. Test both crash windows, including anchor-new/DB-old and verified-DB/unknown-ACK. DB/config backup restoration requires exact forward reconciliation with anchor/current secured server. No claim of hostile same-user/admin isolation.
- [ ] **Step 4: GREEN:** same command plus `Invoke-EpochPytest -c pyproject.toml tests/unit/test_config.py tests/unit/infrastructure/search/test_elasticsearch_factory.py -q` → pass. Readiness verifies floor/authenticated ES identity separately from process-only `/api/v1/health`; API startup RAG composition and worker task entrypoints enforce admission without Platform→Labs dependency.
- [ ] **Step 5: Review checkpoint:** Python/security reviewers inspect child-only injection/client lifetime/error handling and Windows native fakes; root decides `feat: launch secured Elasticsearch clients by access epoch`.

### Task 4: Fixed serial controller, isolated bootstrap and complete route/preservation verification

**Files:** Create `backend/src/ai_workshop/labs/rag/indexing/access_epoch_local.py`, `backend/src/ai_workshop/labs/rag/indexing/access_epoch_native.py`, `backend/src/ai_workshop/labs/rag/indexing/access_epoch_observations.py`, `backend/src/ai_workshop/infrastructure/local/cutover_control_windows.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_local.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_native.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_observations.py`; modify `infrastructure/compose/compose.yaml`; create `infrastructure/compose/compose.access-epoch-bootstrap.yaml`, `infrastructure/elasticsearch/elasticsearch-secured.yml`; update `backend/src/ai_workshop/platform/runtime_topology/runtime-topology-v1.yaml` and `backend/tests/unit/platform/runtime_topology/test_compose_contract.py` if safe topology contract changes. Keep existing large `alias_recovery_local_native.py` v1 behavior intact.
**Consumes:** Tasks1–3 types/repository/private store; immutable original identity from fixed live adapter; no caller-selected target/project/command/path.
**Produces:** `CutoverControlPort.acquire(execution_id: UUID) -> ControlOwnership`; `execute(action: ReservedCutoverAction) -> ControlSettlement`; `reconcile(action: ReservedCutoverAction) -> ControlSettlement`; `OriginalAccessEpochBackend.preflight(snapshot: AliasOperationSnapshot) -> OriginalDeploymentIdentity`; `observe_secured(epoch: PreparedAccessEpoch) -> VerifiedAccessEpoch`; `LocalAccessEpochController.advance(claim: FrozenAliasClaim) -> AccessEpochReadback`; `LocalAccessEpochCollector.collect_verified_end(claim: FrozenAliasClaim) -> LocalAccessEpochTerminationProof`; `revalidate(claim: FrozenAliasClaim, proof: LocalAccessEpochTerminationProof) -> None` (all async).
`ControlOwnership` carries exact execution/executor generation/control-port identity and no elapsed-time lease; Task1 `ControlExpectedIdentity` carries exact targeted container/process/daemon identity plus prior settled action sequence. `PreparedAccessEpoch` phase/projection changes only from Task2 event records.

2026-10-08 bounded implementation update: `AccessEpochReadback.executor_generation` exposes the existing
stored generation. The generic port pins `control_port_id: UUID`, acquires with execution ID and generation,
and provides `assert_owned(ownership)`; expected/execute/reconcile receive that exact token. The controller
checks token and fresh durable state, guards awaited action/finalization boundaries and returns already
completed fresh readback without replay. This implements only the generic ownership contract; native
held-session submission, historical settlement, secured cutover and original acceptance remain unfinished.

2026-10-08 native primitive update: Infrastructure now provides a synchronous
thread-affine `WindowsControlLock` using a derived Global named mutex. Its exact
in-process token, nonrecursive same-thread registry, atomic one-shot acquisition,
abandoned rejection and interrupt cleanup are tested independently. It exposes
no command execution and is not composed into `CutoverControlPort`; Task4's
submission/journal/history/full route/preservation contract remains unfinished.
See [ADR primitive boundary](../../decisions/0033-rag-access-epoch.md#2026-10-08-windows-잠금-보유-구현-범위).

2026-10-08 recording update: `access_epoch_submission.py` provides a protected
recording journal and opaque one-use ticket bound into the expected action payload.
It records intent/local child observations with exact action/scope/identity checks;
old or missing journal data does not authorize resubmission. No launcher/command
or daemon settlement is implemented by this slice. Native namespace durability,
authoritative DB reservation/held-session submission and historical completeness
are still required before composition. [Recording boundary](../../decisions/0033-rag-access-epoch.md#2026-10-08-제출-이력-기록-경계).

2026-10-08 native connection in progress: infrastructure `control_process_windows.py`
creates a hidden suspended child atomically in a private Job. RAG
`access_epoch_process.py` connects a fresh committed reservation readback, protected
intent/child records, one resume, private output capture and local completion for
fixed original STOP/RETIRE only. This is not the complete control port or daemon
settlement; historical terminal tool receipts are being investigated privately.
No original commands, secured transition, receipt/release or queued ingestion
are authorized by this paragraph or claimed complete.

- [ ] **Step 1: Write failing controller tests**, including fixed command grammar, singular physical mount/image identity, historical capability unknown, guest transport without cert, HTTP/direct-IP/remote/relay omission, TLS mismatch, lost key issue response, prior-v1 START/restore/Compose barrier and crashed executor/delegated daemon action.
```python
async def test_unknown_stop_never_reissues_or_invents_retirement_time():
    c = case()
    c.control.stop_reply = "unknown"
    await c.controller.advance(c.claim)
    c.control.old_container_visible = False
    await c.controller.advance(c.claim)
    assert c.control.stop_submissions == 1 and c.control.retire_submissions == 0
    r = await c.repo.readback(c.claim)
    assert r.operation_state == "open" and r.gate_state == "frozen"
    assert r.old_server_stopped_at is None
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_access_epoch_local.py tests/unit/labs/rag/indexing/test_access_epoch_native.py tests/unit/labs/rag/indexing/test_access_epoch_observations.py -q` → missing controller or failed conservative transition.
- [ ] **Step 3: Implement fixed original controller.** Windows named mutex keyed by verified daemon/project serializes control; mutex alone never transfers durable ownership. Every action has DB reservation commit, hidden fixed argv/no shell, private output capture, executor PID+creation generation and child/job/daemon submission/result record. Resume requires same exact request/execution, explicit definitively settled previous executor/children/daemon jobs, exact external readback and mutex reacquisition. Missing Docker inspect or abandoned mutex alone cannot settle pending action; unresolved old v1 collector/restore/Compose up blocks before mutation.
  Preflight derives exact daemon/context/project=`ai-workshop`, container/service/network/original physical volume/image digest from original live deployment and protected historical nonsecret manifests, validates singleton node and no second active mount. No arbitrary external evidence path/allowlisted process list/JSON attestation. Snapshot original stable-node/cluster/index UUID+count/settings/provenance and original asset SHA summaries without private text or secret config hashes.
  Sequence: settle previous controls → stop registered API/worker/beat → durably STOP_OLD observed finished time/JVM → RETIRE_OLD exact stopped ID metadata (`docker rm` with no `-v`, no force running deletion) → TLS preparation → isolated bootstrap → historical capability audit/approved revocation+role issuance → durably stop/retire bootstrap accepting JVM → final secured start → route/preservation verification → start only fresh registered applications. All intermediate bootstrap actions/JVM IDs belong to settlement/deployment history manifests; final proof's new ID is final JVM/container.
  Base Compose becomes secure-only with required `${...:?}` endpoint/CA/epoch/original volume references; image exactly `docker.elastic.co/elasticsearch/elasticsearch:9.5.2`, verified original image digest, external named `elasticsearch-data` with `name: ${AI_WORKSHOP_ES_ORIGINAL_VOLUME:?}` (do not infer name/create it), fixed project. No original live recreation during code work. Read-only TLS/config mounts, loopback9200, no published9300; health checks use explicit CA and controller/health-specific least privilege credential via private runtime input, not command-line secrets. Topology remains safe and omits private paths/secret sources.
  Distinct fresh HTTP/transport project CA/cert bundles; cert SANs include verified loopback/service DNS/direct IP admitted set; transport verification full and `client_authentication=required`, anonymous auth disabled. Manifest enumerates host loopback, internal service DNS/direct IP, HTTP profiles, transport, remote cluster and relay routes; each excluded route has concrete config/network evidence, each admitted route verifies TLS+auth; unknown ingress blocks.
  Bootstrap uses same project/service/volume/image and `network_mode: none`, no published ports; controller accesses TLS loopback via fixed `docker exec` private helper, no general proxy. Observe hidden `.security*` metadata before shutdown; absent evidence is explicit, existing state requires exact approved principal/key audit. Fixed `elasticsearch-reset-password --auto --batch --silent --username elastic --url https://localhost:9200` only under later explicit bootstrap approval; require enabled file realm, private-capture generated password, verify tool temporary file-realm user cleanup. Never blanket reset/delete security index/users/keys.
  Bootstrap admin calls classify every historical write-capable user/key/realm role and invalidate/disable only approved exact targets; unknown scope blocks proof. Always stop/retire bootstrap JVM after revocation to end any accepted old-key work. New API keys carry metadata exact epoch/role/issuance UUID; lost issuance response queries same metadata once, invalidates only inaccessible exact issuance after definitive lookup, then replaces; unknown response/lookup freezes rather than repeats issuance.
- [ ] **Step 4: GREEN:** same command plus `Invoke-EpochPytest -c pyproject.toml tests/unit/platform/runtime_topology/test_compose_contract.py -q` → pass. Deterministic barriers cover concurrent recover, old START/up race, delegation loss, controller crash and late anonymous keepalive/reconnect/retry: mutation0 after final epoch, fresh scoped key success; fake tests remain offline evidence.
- [ ] **Step 5: Review checkpoint:** infrastructure/security reviewers inspect fixed argv, complete route matrix, original-volume singleton and historic/bootstrap settlements; root decides `feat: control original RAG server access cutover`.

### Task 5: Service/CLI exact request integration and stale queued invocation fencing

**Files:** Modify `backend/src/ai_workshop/labs/rag/indexing/alias_recovery.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_repository.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_recovery_cli.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_journal.py`, `backend/src/ai_workshop/labs/rag/indexing/alias_service.py`, `backend/src/ai_workshop/labs/rag/indexing/recovery.py`, `backend/src/ai_workshop/worker.py`, `backend/tests/unit/labs/rag/indexing/test_alias_recovery.py`, `backend/tests/unit/labs/rag/indexing/test_alias_recovery_cli.py`, `backend/tests/unit/labs/rag/indexing/test_alias_service.py`; create `backend/src/ai_workshop/labs/rag/indexing/access_epoch_parity_cli.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_recovery.py`, `backend/tests/unit/labs/rag/indexing/test_access_epoch_queue_audit.py`.
**Consumes:** Task4 collector and Task2 exact durable readback/close; Task3 protected child-role startup settings. Existing `recover_not_dispatched`, preview/freeze/status/release and fresh parity interfaces persist.
**Produces:** `AliasRecoveryService.recover_access_epoch(claim: FrozenAliasClaim) -> AliasRecoveryReceipt` async; CLI additional fixed `recover-access-epoch` subcommand with only existing operation/actor/request UUID options. `load_original_settings(root: Path) -> Settings` remains original protected source; `load_secured_child_settings(root: Path, capability: VerifiedLaunchCapability) -> Settings` admits only verified fixed launch envelope, never arbitrary AI_WORKSHOP_ overrides; `VerifiedLaunchCapability` is created by Task3 protected launch adapter, not deserialized caller JSON.
`VerifiedLaunchCapability` fields: launch UUID, registered role/module, current PID+creation time, epoch UUID/ordinal, key ID and protected admission digest. Launcher writes a DPAPI-protected admission record at fixed `.local-data/access-epoch/private/launches/<launch UUID>.dpapi`, then records actual child PID+creation before signaling its startup barrier. Child only reads its exact startup record once, validates DACL/owner/PID/module/floor and `_security/_authenticate` key ID; inherited launch UUID/env alone is insufficient. Parent cleanup removes the ephemeral admission record after startup ACK; no subsequent credential reload/broker. Secret itself travels only in that child's initial env.

- [ ] **Step 1: Write failing CLI/service and stale-payload tests**, plus altered namespace/actor/claim/floor/manifest, forged v2 object, confirmed operation race, receipt replay after release, lost final commit and parent environment override cases.
```python
async def test_same_v2_receipt_replay_does_not_cutover_release_or_parity():
    c = case()
    first = await c.service.recover_access_epoch(c.claim)
    c.control.fail_if_called = True
    assert await c.service.recover_access_epoch(c.claim) == first
    assert (await c.repo.readback(c.claim)).gate_state == "frozen" and c.runtime.parity_runs == 0
    assert c.runtime.queue_contents == c.runtime.original_queue_contents
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_access_epoch_recovery.py tests/unit/labs/rag/indexing/test_access_epoch_queue_audit.py tests/unit/labs/rag/indexing/test_alias_recovery_cli.py -q` → missing subcommand/service/fencing contract.
- [ ] **Step 3: Implement exact orchestration.** Fresh recovery obtains Task2 durable execution before any Task4 mutation; reentry returns same execution status/receipt only. Collector validates original authorization/snapshot/claim and final floor/live identities outside locks; final repository transaction rechecks owner/current exact claim/operation/verified epoch and immutable proof equality. Caller-created proof objects cannot substitute for collected linked immutable evidence. Unknown commit uses same request status; no automatic external retry, key issuance, release or parity.
  CLI accepts no proof JSON/file/output-proof path, success boolean, route/process allowlist, endpoint/DB/project overrides or secret attestations. Existing preflight diagnostic remains safe; v1 recover/reserved behavior unchanged. Protected original DB endpoint/account/data remain original source; secure launch permits only allowlisted launcher-owned ES credential/epoch fields with explicit role/current-floor verification, never general env override relaxation.
  Audit deployed alias entrypoints/captured clients/serialized Celery payloads and registry producers: queue contains durable job/profile references, not replayable raw alias operations. Reject already dispatching/closed operation IDs at new worker; never serialize clients/keys/raw `_aliases` requests. Normal redelivery retains permission/idempotency and fresh reserve→dispatch CAS. New callback captures startup client before dispatch; old in-process callback/config reload cannot acquire fresh key. Do not purge queue or convert old operation to reserved.
  Require admission before index writes/alias reserve+dispatch and parity; API startup/task entry/readiness verify current floor. Adapter direct write entrypoints `backend/src/ai_workshop/labs/rag/indexing/elasticsearch.py`, `backend/src/ai_workshop/labs/rag/indexing/tracked_elasticsearch.py` are audited and composed only with verified epoch client, without creating a Platform→Labs dependency.
- [ ] **Step 4: GREEN:** same command plus `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_alias_recovery.py tests/unit/labs/rag/indexing/test_alias_service.py tests/unit/labs/rag/indexing/test_tracked_elasticsearch.py -q` → pass. Exact release remains separate and fresh scoped `SqlAlchemyRagAliasParityReconciler.run_once(profile_id=...)` creates a new operation from DB truth; never calls old target replay.
- [ ] **Step 5: Review checkpoint:** independent reviewer checks complete call graph and old v1/reserved API compatibility; root decides `feat: integrate exact access epoch alias recovery`.

### Task 6: Whole-feature offline verification and concrete original deployment approval handoff

**Files:** Modify `docs/runbooks/local-development.md`, `docs/labs/rag/design.md`, `docs/decisions/0033-rag-access-epoch.md` and `WORKBOARD.md` (root only); create `docs/worklogs/2026-10-01-rag-access-epoch-implementation.md` and `backend/tests/integration/labs/rag/indexing/test_access_epoch_live.py` explicit opt-in/fixed-original tests. ISSUE-00013's canonical history is administrator DB, not a guessed Markdown issue file or edits to preserved `issues.json`.
**Consumes:** Tasks1–5 contracts, audit matrices and evidence; no new subsystem or standalone provisioned test deployment.
**Produces:** root-owned offline verification record, exact reviewed deployment package and approval request. Keep implementation status distinct from migration/actual cutover/v2 receipt/release/parity/functionality completion.

- [ ] **Step 1: Write remaining failing acceptance tests** for permission matrix, late old callback/config reload, stale queue/new reserve and route/full transport protection. Live tests do not generate resources or mutate original environment unless separately approved; distinguish read-only live assertions, rollback-only DB checks, and actual controller actions.
```python
def test_permission_manifest_excludes_security_and_other_namespaces():
    manifest = case().permissions
    assert manifest.reader.cluster == ("monitor",)
    assert manifest.reader.index == ("read", "view_index_metadata")
    assert manifest.writer.index == ("read", "write", "manage")
    assert manifest.collector.index == ("read", "view_index_metadata")
    assert manifest.beat is None and manifest.frontend is None
    assert manifest.writer.allow_restricted_indices is False
```
- [ ] **Step 2: RED:** `Invoke-EpochPytest -c pyproject.toml tests/unit/labs/rag/indexing/test_access_epoch_observations.py tests/unit/labs/rag/indexing/test_access_epoch_queue_audit.py -q` → new acceptance assertions fail until missing call audit/permission enforcement is implemented; demonstrate meaningful denial, not dictionary formatting only.
- [ ] **Step 3: Complete manifests/runbook and permission tests** with exact `IndexDescriptor` grammar: active alias `{prefix}-{indexing UUID}-active` or `{prefix}-{processing UUID}-{indexing UUID}-active`; physical name replaces `-active` with `-{build UUID}`. Use exact existing names and narrowly validated descriptor namespace patterns for future fresh builds; no global `*`/other namespace/security-index access. New profile namespaces require explicit scope approval/key rotation, not silent broader roles.

| Role | Cluster privileges | Index privileges / actual API calls | Residual scope |
| --- | --- | --- | --- |
| API reader | `monitor` | `read,view_index_metadata`: info, resolve/get index/mapping/alias, search/count, open/close PIT | read namespace metadata/docs; no mutations |
| worker writer | `monitor` | `read,write,manage`: above reads, index create, bulk index, refresh, update_aliases | `manage` also permits delete/settings within exact namespace; record this breadth |
| fixed parity writer | `monitor` | `read,write,manage`: resolve/observe/count/get metadata, update_aliases for scoped parity | writer role; no new key issuing broker or stale request replay |
| fixed collector/health | `monitor` | `read,view_index_metadata`: info, nodes/cluster health/state, settings/mapping/alias/count observations | no application/security mutation; split controller bootstrap credential |
| beat/frontend | none | no ES calls/keys | beat only schedules existing IDs |
| bootstrap controller | private built-in admin, not app key | exact security audit, approved principal/key invalidation, API-key issuance/query | controller-only; no exposure via API/worker settings |

  Compare actual deployed method list in retrieval/indexing/tracked adapters to permission manifest and execute fake allowed/denied API requests (deny outside namespace/security/user/key-generation/node-join/remote-cluster). Current `evaluation/authoring_api.py` composes read-only `ElasticsearchFrozenIndexInspector`, so authoring does not justify API writer privileges; any discovered mutation requires source evidence/role review. Hidden security metadata audit uses bootstrap admin only. Pin privileges against [Elastic privileges](https://www.elastic.co/docs/reference/elasticsearch/security-privileges); no claim that index manage is alias-only. API key role descriptors have cluster rights above, `allow_restricted_indices:false`, empty application/global/run_as privileges.
  Cite [reset-password](https://www.elastic.co/docs/reference/elasticsearch/command-line-tools/reset-password) temporary-file-realm cleanup/private stdout requirements and [Windows DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) CurrentUser/noninteractive behavior. No generic CA install/trust-store change.
- [ ] **Step 4: GREEN/full offline gate:** from `backend` cwd `Invoke-EpochPytest -c pyproject.toml tests/unit -q`; from `backend` run `& .\.venv\Scripts\python.exe -m ruff check .` and `& .\.venv\Scripts\python.exe -m mypy src --cache-dir=nul`; inspect actual exit codes and summarize unrelated baseline failures without weakening requirements. Static YAML/document-link/0061→0062 graph checks do not connect `.env`/DB/ES. Do not run unrestricted full pytest against original `.env`.
- [ ] **Step 5: Review checkpoint and final handoff:** independent code/security/DB/infrastructure/integration review; root updates WORKBOARD/ISSUE evidence and decides scoped commits. Existing owner issue-history document linking waits for original admin login; do not create account. Preserve uncompleted functional acceptance items; no production safety or whole-RAG completion claim from offline tests.

## Later approval package and live order (not executable during planning/offline implementation)

Give the user concrete nonsecret values from a separately permitted read-only original inventory: exact old container ID/daemon/context/project/network/pinned image digest/physical named volume; current operation/actor/request/revision/snapshot; registered API/worker/beat lifetimes; all routes; data/index/asset/config/queue preservation summaries; private store ACL/DPAPI strategy and certificate SANs; exact historical revocation targets; downtime/forward-repair boundaries and commands reviewed through fixed controller kinds. Do not publish raw env/private paths/secret output.
Request explicit approval for original migration0062, original rollback verification, two CA/cert generations, exact built-in bootstrap password/key issuance and approved historical targets, original service stops, exact old/bootstrap container-metadata retirement and secured original-volume starts. No minute downtime promise. Until approval leave auth-off original live environment unchanged.
Approved sequence: stop/drain original registered application writers/supervisors → apply0062 using existing official Python/Alembic Windows selector-policy entrypoint → original rollback-only constraints → settle old controls → durable exact recover-access-epoch actions → final floor/protected runtime/readiness → immutable v2 receipt status → exact release → one fresh scoped parity from current DB truth → authenticated original search/source viewer/generation connection and failure/monitoring checks → preserve counts/SHA/config/queue and record measured outage.
The `Invoke-OriginalEpochPytest` helper sets `AI_WORKSHOP_VERIFY_ORIGINAL_ACCESS_EPOCH=1` only in a temporary verification child and executes the Task2 pytest command; it never obtains new credentials or commits. Committed two-connection ownership/lost-commit evidence needs separately approved existing-original bounded journal exercise; SAVEPOINT tests and in-memory deterministic barriers remain labelled accordingly. Do not provision a replacement DB/account or assert committed-race proof from rollback mode.
At any unknown external/DB outcome, retain frozen and exact request/execution; status/readback and definitive previous-generation settlement precede resume. After original retirement, repair only with the same volume/pinned image/secured config/floor; no START old ID, insecure Compose or migration downgrade. Do not delete alternate artifacts before original reflection/verification is complete.
Map: purpose/alternatives/preservation/TLS/historical bootstrap→Tasks3–4; credentials/callback/queue→Tasks3/5/6; DB/external ownership/floor→Tasks2–4; exact v2/atomic close→Tasks1–2/5; failure/compatibility→all tasks; module boundaries/validation→Tasks3–6; next approval/functionality reporting→Task6.

## Plan review and execution method

Root self-review covers every spec section: Tasks1–2/5 exact proof and atomic recovery; Tasks3–4 original preservation, TLS/bootstrap and credential isolation; Tasks2–4 control ownership/floor and restore; Tasks3/5–6 callback/queue/permission enforcement; Task6 original acceptance and reporting. Fixed the event append/transition distinction, ChildLifetime test field, original Windows selector-loop flags, floor anchor/DB crash order, backend-cwd/child-only test settings isolation, real SUT/external fake separation, and public Settings versus ES capability validation before publishing. Independent security/contract review is additional evidence and does not replace this self-review. Recommend **Native inline main implementation plus separate independent verifier/reviewer** because these six tasks share tightly coupled proof/schema/controller/client interfaces; root controls integration and all Git decisions. Choosing code execution does not authorize the later original security cutover.

Coverage check is complete against every spec section; actual volume/container/network/daemon/image-digest/SAN/historical-principal values intentionally come from the later exact original inventory, not invented fixtures or user proof input. The existing pinned image tag/current0061 chain and command syntax were checked from repository sources, but no tests/live commands were run for this planning proposal.
