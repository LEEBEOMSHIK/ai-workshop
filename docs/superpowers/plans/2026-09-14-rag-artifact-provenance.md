# RAG 객체 산출물 추적 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 파싱·청킹·임베딩 파일의 생성 전 소유권과 작성 시도를 등록하고 실제 파일을 대조한다.
**Architecture:** RAG 소유 영속 계약과 추적 객체 저장 어댑터를 만든 뒤 기존 ingestion에 연결한다. 공통 현재 출처 관계를 재사용하고 목록은 별도 읽기 서비스로 제공한다.
**Tech Stack:** 기존 Python, SQLAlchemy, Alembic, PostgreSQL, 로컬 객체 저장소, pytest.
**Spec:** docs/superpowers/specs/2026-09-14-rag-artifact-provenance-design.md

## Global Constraints

- main에서 기존 변경을 보존한다. 새 worktree·패키지·가상환경·실사용 migration/backfill·서버 재시작·실제 purge·commit/push는 하지 않는다.
- 참여자 rag_ingestion_artifacts, 종류 artifact_bundle, 관계 derived_artifact, contract_version 1.
- 고정 revision 1이 아니라 실제 파일 묶음 변경 트랜잭션마다 +1, 멱등 재확인은 유지한다.
- 파일 I/O 중 DB 잠금을 유지하지 않는다. 슬롯별 open 시도 최대1개이며 timeout 자동 인계/정리 금지.
- 기존 backend/.venv, pytest -B -p no:cacheprovider, Ruff --no-cache. DB 테스트는 검증된 isolated_publishing_database의 UUID DB만 사용한다.
- 합성 파일은 pytest 전용 tmp_path만 사용한다. 실제 저장소 marker를 만들지 않는다. 기존 ObjectStore 의미와 legacy 정상 처리는 보존한다.
- ingestion 테스트의 상위 autouse ensure_legacy_document_processing_profile은 앱 DB를 열 수 있으므로 새 테스트 모듈에서 격리 fixture 의존성으로 재정의한다. migration이 seed를 제공하므로 실제 앱 DB seed를 호출하지 않는다.
- 하위 에이전트는 지정 파일만 수정하며 subagent/commit/push/WORKBOARD 마감을 하지 않는다.
- 임시 인계는 .local-data/project-agent-work/rag-artifact-provenance/에만 둔다. 소유권 없는 기존 scratch를 제거하지 않는다.

## Task 1: 영속 계약·등록·시도 repository

**Files**
- Create backend/src/ai_workshop/labs/rag/ingestion/artifact_contracts.py
- Create backend/src/ai_workshop/labs/rag/ingestion/artifact_models.py
- Create backend/src/ai_workshop/labs/rag/ingestion/artifact_repository.py
- Create backend/alembic/versions/0041_rag_artifact_provenance.py
- Modify backend/src/ai_workshop/shared/model_registry.py, backend/alembic/env.py
- Create backend/tests/integration/labs/rag/ingestion/test_artifact_repository.py
- Create backend/tests/integration/labs/rag/ingestion/test_artifact_migration.py

**Interfaces**
Frozen contracts: ArtifactRole(parsed/chunks/embeddings), ArtifactBinding(store_id: str, binding_id: UUID).
ArtifactClaim contains bundle_id, slot_id, attempt_id, job_id, projection_id (UUID), role, binding, canonical_key, temporary_key, proposed_size, proposed_sha256.
VerifiedArtifact contains bundle_id, slot_id, job_id, projection_id, role, binding, canonical_key, size, sha256.
ArtifactPublication contains claim, size, sha256; signifies validated canonical bytes and this writer has ended with temp absent. Never accept this from public input.
SqlAlchemyRagArtifactRepository(session: AsyncSession):
register_bundle(job_id: UUID, binding: ArtifactBinding) -> UUID;
reserve_attempt(job_id: UUID, role: ArtifactRole, binding: ArtifactBinding, *, size: int, sha256: str) -> ArtifactClaim | VerifiedArtifact;
finalize(publication: ArtifactPublication) -> VerifiedArtifact;
close_failed_attempt(claim: ArtifactClaim, *, code: str) -> None.
No method commits. Callers own transaction/current lifecycle locks; methods never acquire existing lifecycle locks after bundle. Validation queries needed for source are before bundle locks. Failures use safe typed ArtifactTrackingError(code). Claim/finalize must refresh locked state, exact-token checks, source/slot/binding consistency, idempotency, one current relation.

- [x] RED: owned DB seed official job/projection/source, register creates exactly3 slots and revision1/relation; absent module fails first.
```python
bundle_id = await repository.register_bundle(job_id, binding)
claim = await repository.reserve_attempt(job_id, ArtifactRole.PARSED, binding, size=2, sha256=synthetic_digest)
assert claim.bundle_id == bundle_id
with pytest.raises(ArtifactTrackingError):
    await repository.reserve_attempt(job_id, ArtifactRole.PARSED, binding, size=2, sha256=synthetic_digest)
```
- [x] Add constraints exactly spec: source/job/projection composite identity; all referenced unique keys introduced in migration, model metadata matches; RESTRICT ownership, partial unique open_slot; safe nonempty downgrade. Legacy untouched.
- [x] GREEN: registration atomic relation+3slots, reservation revision2+open attempt, finalize revision3+verified+closed; duplicate same finalization no bump; failed close permits fresh UUID, open cannot be stolen. Invalid token/source/binding/size/hash and inconsistent current relation fail before mutations.
```python
await repository.finalize(ArtifactPublication(claim=claim, size=2, sha256=synthetic_digest))
again = await repository.reserve_attempt(job_id, ArtifactRole.PARSED, binding, size=2, sha256=synthetic_digest)
assert isinstance(again, VerifiedArtifact)
```
- [x] Cover concurrency, stale ORM, rollback, FK/unique/check, generic provenance contract unchanged.
- [x] Run focused2test files with safe helper, mypy3production, Ruff5+registry/migration; report RED/GREEN + interfaces; independent review before Task2.

## Task 2: 정확한 임시 key·저장소 binding 어댑터

**Files**
- Create backend/src/ai_workshop/infrastructure/object_store/tracked.py
- Create backend/tests/unit/infrastructure/object_store/test_tracked.py
- Modify backend/src/ai_workshop/config.py
- Test backend/tests/unit/test_config.py only if existing; otherwise focused new test under object_store.
**Interfaces**
TrackedLocalArtifactStore(root: Path, binding: ArtifactBinding):
verify_binding() -> None;
async publish(claim: ArtifactClaim, content: bytes) -> tuple[ArtifactPublication, bytes];
async read_verified(artifact: VerifiedArtifact) -> bytes;
async inspect_key(key: str) -> StoredObject | None (body-free metadata, safe error on unavailable).
It only performs I/O, never DB finalize. publication returned only when canonical observed bytes match claim proposed digest/size and temp absent; unexplained existing canonical blocked. Known verified uses read_verified. Failed I/O carries safe error plus writer-finished/temp-absent fact only if actually verified (typed attribute, no invented success).
Settings: optional rag_artifact_store_id: str | None and rag_artifact_store_binding_id: UUID | None with pair validation; not a silent tracking disable switch. Task3 rejects new tracked ingestion when binding missing. Existing legacy is unchanged.

- [x] RED: marker missing/mismatch, invalid/reparse/root/key collision, no overwrite, exact temp filename, own temp cleanup.
```python
publication, content = await store.publish(claim, b"{}")
assert publication.claim == claim
assert content == b"{}"
assert not (root / claim.temporary_key).exists()
```
- [x] GREEN: marker schema {"schema_version":1,"store_id":...,"binding_id":...}; bounded read/validation; no automatic marker initialization. Verify typed expected/marker/claim identity before I/O and at readback. Canonical allowed role+projection key, exact attempt temp sibling, reject Windows aliases/reparse/symlink including root and marker.
- [x] Exclusive tmp creation -> flush/fsync -> atomic hardlink-if-absent -> readback -> own temp cleanup. Never unlink a preexisting temp not created by this invocation. No DB or generic store edits.
- [x] Test simulated interruption and genuine disposable child-process termination leaving only registered exact temp key; no live files touched.
- [x] Focused unit tests, mypy adapter/config, Ruff; independent review.

## Task 3: 공식 ingestion 경로 연결

**Files**
- Create backend/src/ai_workshop/labs/rag/ingestion/artifact_service.py
- Modify backend/src/ai_workshop/labs/rag/ingestion/repository.py, service.py, tasks.py, stages.py, domain.py
- Modify actual production constructor call sites found by rg (only dependency wiring, report exact list before edits).
- Create backend/tests/integration/labs/rag/ingestion/test_artifact_lifecycle.py
- Modify affected existing unit synthetic fixtures only; do not weaken assertions or broadly rewrite tests.
**Interfaces**
Artifact publisher orchestrates short own reservation transaction and Task2 I/O; returns validated payload + ArtifactPublication or VerifiedArtifact. Existing ArtifactReference may add optional tracking DTO defaultNone for legacy. Lifecycle complete_parsing/complete_chunking and embedding stage finalize use the current session; no independent DB commit.

- [x] RED official ensure newly created projection commits bundle+3slots+relation before dispatch; missing binding rejects before new writes, existing job/projection path not auto-backfilled.
- [x] GREEN production composition resolves typed binding; store validates existing marker before admitting new tracking. Add registration only to new projection/job path. Standalone projection API remains unchanged.
- [x] RED/GREEN parsing/chunking/embedding invoke tracked publisher only for registered bundles; legacy continues existing exact behavior. A tracked bundle error never falls back to legacy.
```python
# After a forced lifecycle DB failure:
assert canonical_file_exists
assert stored_attempt.state == "open"
assert stored_slot.state == "reserved"
# A normal retry cannot steal this attempt:
assert next_error.code == "writer_unconfirmed" or next_error.code == "artifact_attempt_busy"
```
- [x] Finalize publication in existing lifecycle transaction with ingestion refs and SQL mutations; token/source/state/revision rechecks precede acceptance. Completed-stage replay reuses verified artifact without opening a new attempt.
- [x] Normal failure closes attempt only after actual writer end/temp absence; unknown crash stays open. Never timeout takeover.
- [x] Run focused ownedDB lifecycle tests and ingestion/document/chunk units; legacy reuse regression in the new owned-UUID module; existing app-DB-dependent integration modules are not executed (validation boundary recorded in worklog). Type/lint and independent review.

## Task 4: 파일 대조 목록·최종 인계

**Files**
- Create backend/src/ai_workshop/labs/rag/ingestion/artifact_inventory.py
- Create backend/tests/integration/labs/rag/ingestion/test_artifact_inventory.py
- Modify docs/runbooks/local-development.md (binding activation prerequisites only).
**Interfaces**
RagArtifactInventory(engine: AsyncEngine, store: TrackedLocalArtifactStore), async collect(workspace_id: UUID, documents: tuple[DocumentTarget,...]) -> ParticipantInventory.
Caller owns engine. Own first readonly repeatable-read snapshot; file inspection outside DB; own final readonly snapshot verifies full target/source/revision/relation/slot/attempt membership continuity.
- [x] RED valid allsource/allversion registration returns only bundle opaqueID/revision; nonexistent/wrongworkspace/generation/incomplete versions typederror.
- [x] GREEN bidirectional actual/registry, exact3roles and binding, ingestion refs, allstates/legacy, metadata minimality. Compare files only at exactkeys, checksum verified file.
```python
result = await inventory.collect(workspace_id, targets)
assert result.participant == "rag_ingestion_artifacts"
assert not result.exhausted  # unresolved open attempt remains observable
```
- [x] Test file absence/corruption, closed temp residual, reserved existing unexplained, unknown kind/store, DB errors and mutations between first/final snapshot. No false wholepurge success.
- [x] Document explicit marker/bootstrap expected binding, no automatic live marker creation, legacy exclusions and unresolved writer prerequisite. No live activation command executed.
- [x] Focused tests/type/lint and task review; main full relevant safe regressions; mostcapable final whole review; update WORKBOARD/worklog recent5 max.

## Plan preflight

Task1 produces typed contracts and model/repository; Task2 consumes contracts only; Task3 consumes both and retains lifecycle transaction ownership; Task4 consumes models+safe file inspection. Task1/3 share no edits except interfaces consumed, Task2/3 share config reads not concurrent edits. Tasks run sequentially.
Binding admission is required for NEW ingestion, not optional silent downgrade. Real environment is not reconfigured by tests.
Spec sections1-5: Task1/3; section6: Task2; section7: Task4; section8: Task1/3/4; section9 exclusions apply all; section10 covered per task and final integration.
