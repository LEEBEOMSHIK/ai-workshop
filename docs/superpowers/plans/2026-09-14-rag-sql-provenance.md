# RAG SQL 출처 연결 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** RAG DB 산출물 변경을 현재 출처 관계·단조 revision과 묶고 일관된 읽기 목록으로 확인한다.

**Architecture:** RAG 소유 aggregate mutation을 공통 provenance 관계 교체와 같은 트랜잭션에 둔다. 별도 읽기 서비스가 REPEATABLE READ READ ONLY snapshot으로 실제 SQL과 대장을 대조한다. Platform은 Labs를 import하지 않는다.

**Tech Stack:** 기존 Python/FastAPI, SQLAlchemy, Alembic, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-rag-sql-provenance-design.md`

## Global Constraints

- 참여자는 `rag_document_sql`, 종류는 `projection_bundle`, 관계는 `derived_artifact`다.
- 새 패키지·가상환경·worktree를 만들지 않고 main의 기존 사용자 변경을 보존한다.
- 실사용 DB 적용·기존 자료 backfill·서버/worker 재시작·외부 모델 호출·실제 삭제는 이번 작업에 포함하지 않는다.
- 테스트는 기존 `backend/.venv`와 `isolated_publishing_database`의 정확한 UUID 합성 DB만 사용한다. 실제 .env DB에 migration/reset을 수행하지 않는다.
- pytest는 `-B -p no:cacheprovider`, Ruff는 `--no-cache`로 실행한다. 테스트 소스는 제품 회귀 자산이며 임시 루트 파일을 만들지 않는다.
- 변경 전 상태를 보존하며 하위 에이전트는 commit/push/WORKBOARD 마감/다른 에이전트 호출을 하지 않는다.
- 공통 participant 하나의 성공을 전체 삭제 완료로 연결하지 않는다.

## Task 1: revision 저장·출처 교체·실제 쓰기 연결

**Files:**
- Modify: `backend/src/ai_workshop/platform/assets/provenance_repository.py`
- Modify: `backend/src/ai_workshop/labs/rag/documents/models.py`, `repository.py`
- Create: `backend/src/ai_workshop/labs/rag/documents/provenance.py`
- Modify: `backend/src/ai_workshop/labs/rag/ingestion/recovery.py`
- Create: `backend/alembic/versions/0040_rag_content_revision.py`
- Create tests: `backend/tests/integration/labs/rag/documents/test_provenance_writes.py`, `test_provenance_migration.py`
- Existing tests affected: document repository and ingestion recovery; change only focused fixture/contracts if necessary and report.

**Interfaces:** `RagProjectionRecord.content_revision: Mapped[int | None]`; existing public repository method signatures preserved.
`ProvenanceRepository.replace_current(expected: SourceRelation, replacement: SourceRelation) -> None` verifies same source/resource identity/kind/relation and exactly next revision; checks unique current ownership across this participant/kind/resource, conditionally updates exactly one row. Generic register unchanged.
RAG module exposes named protocol constants in `documents/provenance.py`; source resolution and mutation helpers remain internal to RAG.

- [x] RED: synthetic DB test newly added projection has revision1 and exact source relation; old code yields absent tracking. Add tests for write/status revisions, no-op, legacyNULL, missing/extra/wrong source/revision conflict and transaction rollback before implementation.

```python
projection = await repository.add_projection(pending)
await repository.mark_status(projection.id, ProjectionStatus.PARSING)
record = await session.get(RagProjectionRecord, projection.id)
assert record.content_revision == 2
relations = await ProvenanceRepository(session).list_for_source(source)
assert [(r.resource.resource_id, r.resource.revision) for r in relations] == [(projection.id, 2)]
```

- [x] GREEN: additive nullable BIGINT + positive CHECK migration; new rows1, legacyNULL untouched. Guard downgrade if tracked row/relation exists. No server default that upgrades old data.
- [x] GREEN: each mutation locks/refetches projection, validates before writes, changes content and conditional revision and current relation in caller transaction. Legacy remainsNULL. Recovery FAILED path uses same repository. ensure existing projection gains no new lock/backfill. Same-status writes do not increment.

```python
# RAG helper algorithm; typed errors contain safe codes only.
if current_revision is not None:
    next_revision = current_revision + 1
    await provenance.replace_current(expected_relation, replacement_relation)
    # UPDATE projection WHERE id=:id AND content_revision=:expected; require one row.
```

- [x] Verify concurrent committed mutations yield consecutive revisions/current relation, stale identity maps refresh, failure after content update rolls back content+revision+relation. Run migration upgrade/emptydowngrade/nonemptyrefusal on owned synthetic DB.
- [x] Run focused tests, mypy production files and Ruff changed files; report RED/GREEN and independent task review. No commit without main scoped decision.

Run from backend: `.venv/Scripts/python.exe -B -m pytest tests/integration/labs/rag/documents/test_provenance_writes.py tests/integration/labs/rag/documents/test_provenance_migration.py -q --tb=short -p no:cacheprovider`.

## Task 2: SQL 소유 범위 목록 수집

**Files:**
- Create: `backend/src/ai_workshop/labs/rag/documents/purge_inventory.py`
- Create: `backend/tests/integration/labs/rag/documents/test_purge_inventory.py`
- Reuse Task1 constants/source mappings; do not modify Task1 contract without main ruling.

**Interfaces:** `RagDocumentSqlInventory` accepts an existing AsyncEngine (caller owns disposal); `async collect(workspace_id: UUID, documents: tuple[DocumentTarget, ...]) -> ParticipantInventory`. It opens its own REPEATABLE READ READ ONLY transaction, never commits caller writes. Source missing/wrong ownership/generation/incomplete all-version targets fail via a safe typed inventory error. Supported but inconsistent source tracking returns `legacy_resolved=False`; unsupported resource kinds return `supported=False`.

- [x] RED: all versions/statuses registered returns opaque current resources; legacy/missing/gone/wrongrevision/extra relation fails closed; nonexistent/wrongworkspace source cannot be empty success.

```python
result = await RagDocumentSqlInventory(engine).collect(workspace_id, targets)
assert result.participant == "rag_document_sql"
assert {r.resource_id for r in result.resources} == {first_projection, failed_projection}
assert result.exhausted and result.supported and result.legacy_resolved
```

- [x] GREEN: single owned repeatable-read read-only transaction; validate target document generation and exact complete versions, join actual projection ownership against current relation both ways, verify child/evidence ownership without selecting text/path/hash. All statuses included. No registered relation or projection for valid source yields empty complete snapshot for this participant only.
- [x] Verify NULLrevision, extra source/oldrevision, malformed kinds, snapshots across concurrent writer commit, no writes, safe errors, output data minimization. Future modules are not auto-registered as complete.
- [x] Run focused tests/mypy/Ruff and independent review; report exact scope and runtime exclusions.

Run from backend: `.venv/Scripts/python.exe -B -m pytest tests/integration/labs/rag/documents/test_purge_inventory.py -q --tb=short -p no:cacheprovider`.

## Final verification and handoff

- [x] Main runs new tests + inspected safe document/ingestion/provenance/migration regression files. Inspect fixture targets before adding legacy integration files to command.
- [x] Run changed production mypy and changed Python Ruff, git diff check; final whole-scope independent review.
- [x] Record exact evidence, no-liveDB/worker/API/delete boundary in worklog and WORKBOARD; recent completed maximum5. Preserve mixed dirty changes, no broad staging/commit/push.
