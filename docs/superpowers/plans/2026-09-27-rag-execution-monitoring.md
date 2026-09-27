# RAG Execution Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 환경에서 관리자가 본인의 RAG 질문 결과와 실패 단계·근거·시간을 조회한다.

**Architecture:** 기존 turn을 본문 정본으로 유지하고 RAG 전용 실행 메타데이터를 추가한다. 실행 기록과 읽기 권한 서비스를 분리하며 현재 권한을 적용한 동일한 모집단에서 목록과 집계를 계산한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL/Alembic, Next.js, React, pytest, Vitest.

**Spec:** [승인 설계](../specs/2026-09-27-rag-execution-monitoring-and-evaluation-design.md)

## Global Constraints

- 기존 `.env`·DB·계정·PDF·대화를 보존한다. 별도 DB·계정·환경·worktree를 생성하지 않는다.
- Platform은 RAG 구현에 의존하지 않는다. 관리자 권한으로 다른 사용자의 대화를 열지 않는다.
- 본문·프롬프트·공급자 원문 오류·내부 추론을 실행 메타데이터에 복사하지 않는다.
- 모델 호출 중 DB 잠금을 유지하지 않는다. 모니터링 조회로 모델을 호출하지 않는다.
- 실행/답변/품질 상태를 분리하며 누락 시간은 null이다. 과거 기록을 재실행하거나 가짜 실행으로 backfill하지 않는다.
- 아래 명령은 저장소 루트에서 실행한다. DB를 생성하는 기존 integration fixture는 호출하지 않는다.
- 각 작업의 지정 파일만 메인 Codex가 검토·staging·commit한다. `references/`는 제외한다.

## Review Focus

- 삭제 또는 권한 회수와 동시에 조회: 질문·제목·후보 식별자와 집계에서도 배제한다(Task 3).
- 취소/삭제 직후 늦은 모델 완료 및 멱등 재전송: 성공으로 역전하거나 중복 호출하지 않는다(Task 2).
- 진단 비활성화·관측 저장 장애: 원래 결과를 유지하고 기록의 불완전성을 표시한다(Task 2).
- 같은 client correlation ID를 가진 다른 실행: 서버 실행 ID로만 연결한다(Task 1).
- 과거 기록·시간 누락·동일 시각의 여러 행: 허위 단계/0초를 만들지 않고 안정적으로 페이지를 이동한다(Task 3, 4).

---

## Task 1: 실행 메타데이터와 종료 계약

**Files:** Create `backend/src/ai_workshop/labs/rag/executions/domain.py`, `models.py`, `repository.py` in that same directory; `backend/alembic/versions/0054_rag_executions.py`; `backend/tests/unit/labs/rag/executions/test_lifecycle.py`; `backend/tests/integration/labs/rag/executions/test_repository_existing_db.py`; `docs/decisions/0029-rag-execution-monitoring.md`. Modify `backend/alembic/env.py`, `backend/src/ai_workshop/labs/rag/generation/audit_models.py`, `backend/src/ai_workshop/labs/rag/generation/audit.py`, `docs/labs/rag/design.md`, `docs/superpowers/specs/2026-09-21-contextual-rag-evidence-design.md`.

**Interfaces:** `ExecutionIdentity(execution_id: UUID, actor_id: UUID, turn_id: UUID | None, evaluation_attempt_id: UUID | None)` requires exactly one parent. `StageName` contains request, history, contextualization, retrieval, selection, generation, citation_validation, persistence. `StageState` contains pending, running, completed, failed, skipped, unrecorded. `ExecutionState` contains running, completed, failed, cancelled, interrupted. `ExecutionRecorder.start(identity: ExecutionIdentity) -> None`, `record(execution_id: UUID, observation: StageObservation) -> None`, `finish(execution_id: UUID, outcome: ExecutionOutcome) -> None` are async. `StageObservation` carries stage/state/start/end/duration_ms/safe reason plus typed bounded source, score, budget and version observations; `ExecutionOutcome` carries state/answer status/error code/completeness. No free-form body field.

- [ ] Write lifecycle tests: `test_terminal_state_cannot_reverse`, `test_duplicate_turn_has_one_execution`, `test_correlation_is_not_identity`, `test_rejects_nonfinite_or_negative_duration`. Assert cancelled stays cancelled, distinct server IDs remain distinct and missing duration remains null.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/executions/test_lifecycle.py -q`; expect missing implementation failure.
- [ ] Update ADR/design before code; implement additive tables, unique turn parent, unique evaluation attempt parent and nullable indexed audit execution FK. Store source IDs/revisions/pages/offsets, ranks/scores/reasons, applied budgets/counts/serialized byte size, exact profile versions and truncation counts. Named `MAX_RECORDED_CANDIDATES = 200`; persist at most min(returned top_k, cap), preserve total count. The cap is a recording limit, never a retrieval/selection limit.
- [ ] Implement short idempotent writes and conditional terminal transitions. Migration does not rewrite existing turns/audits. Add integration tests using an injected connection, outer rollback and existing actor IDs; no user/DB creation or destructive cleanup. Tests insert only synthetic rows within rollback and verify FK/unique/terminal constraints.
- [ ] Run the unit command to PASS; inspect `alembic heads` and offline SQL with the backend environment before applying the additive migration through the local runbook. Run the new integration file with the existing DB and confirm no committed fixture rows. Never downgrade the user's DB as a test.
- [ ] Commit only Task 1 files: `feat(rag): persist bounded execution metadata`.

## Task 2: 실제 대화 단계와 감사 기록 연결

**Files:** Create `backend/src/ai_workshop/labs/rag/executions/observer.py`; `backend/tests/unit/labs/rag/executions/test_observer.py`; `backend/tests/unit/labs/rag/executions/test_conversation_trace.py`. Modify `backend/src/ai_workshop/labs/rag/conversations/service.py`, `backend/src/ai_workshop/labs/rag/conversations/api.py`, `backend/src/ai_workshop/labs/rag/domains/api.py`, `backend/src/ai_workshop/labs/rag/search/service.py`, `backend/src/ai_workshop/labs/rag/search/schemas.py`, `backend/src/ai_workshop/labs/rag/search/diagnostics.py`.

**Interfaces:** `ExecutionObserver(identity: ExecutionIdentity, recorder: ExecutionRecorder)` provides async `begin(stage: StageName) -> None`, `end(observation: StageObservation) -> None`, `finish(outcome: ExecutionOutcome) -> None` and `complete: bool`. Pass it explicitly as an optional keyword `observer` through the domain executor into search; never derive it from client headers. Existing callers without observer remain valid. Conversation turn DTO gains nullable `execution_id` and `observation_complete`.

- [ ] Write tests for all successful stages, provider failure, citation failure, selection insufficiency, generation insufficiency, cancellation, deletion, replay, diagnostics disabled and recorder failure. Assert provider called once for replay, failed stage retained, subsequent stages skipped, original error preserved and diagnostics on/off selected IDs identical.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/executions/test_observer.py backend/tests/unit/labs/rag/executions/test_conversation_trace.py -q`; expect missing observer failures.
- [ ] Allocate identity when a turn is reserved; replay returns its existing identity. Instrument history and search stages with monotonic duration and UTC timestamps. Reuse already computed retrieval/context scores without extra embedding. Split generation/citation timing without altering validation. Explicitly link audit records to identity. Persist final response and matching execution state in the turn finalization transaction; respect existing termination fences. Recorder failures set completeness false and emit only execution ID/stage/safe code.
- [ ] Run the new tests plus `backend/tests/unit/labs/rag/search/test_context_generation.py` and `backend/tests/unit/labs/rag/search/test_generation_policy_gate.py` using pytest; expect PASS and unchanged existing answer behavior.
- [ ] Commit only Task 2 files: `feat(rag): trace conversation execution stages`.

## Task 3: 권한을 적용한 목록·상세·집계 API

**Files:** Create `backend/src/ai_workshop/labs/rag/executions/access.py`, `service.py`, `schemas.py`, `api.py` in the same directory; `backend/tests/unit/labs/rag/executions/test_read_service.py`; `backend/tests/integration/labs/rag/executions/test_monitoring_api.py`. Modify `backend/src/ai_workshop/labs/rag/executions/repository.py`, `backend/src/ai_workshop/main.py`.

**Interfaces:** `ExecutionReadService.search(actor_id: UUID, request: ExecutionSearchRequest) -> ExecutionSearchResponse`, `detail(actor_id: UUID, execution_id: UUID) -> ExecutionDetailResponse`, `legacy(actor_id: UUID, turn_id: UUID) -> ExecutionDetailResponse` are async. Request holds optional date/domain/kind/execution status/answer status/failed stage/configuration version/query filters and opaque cursor, limit default 25, range 1–100. Response holds items/next_cursor/filtered totals/timing denominator/missing count/median/p95. Dedicated detail DTO has safe answer/citations/stages/candidates/configuration/usage, optional evaluation link and completeness; excludes validation_token.

- [ ] Write tests `test_owner_and_current_dependencies_before_paging`, `test_hidden_query_does_not_change_aggregate`, `test_deleted_turn_unavailable`, `test_legacy_has_no_invented_stage`, `test_equal_timestamps_cursor_no_duplicates`, `test_detail_excludes_validation_token`, `test_nonadmin_denied`. Check response body and aggregate, not just status codes.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/executions/test_read_service.py backend/tests/integration/labs/rag/executions/test_monitoring_api.py -q`; expect missing API/service failures. API tests use injected repositories and ASGI client, no new environment.
- [ ] Implement POST `/api/v1/admin/rag/executions/search`, GET `/api/v1/admin/rag/executions/{execution_id}`, GET `/api/v1/admin/rag/executions/legacy/{turn_id}` with existing administrator authorization and no-store. Restrict owner in SQL first. Evaluate current source rights and history dependency closure on the filtered owner rows in bounded batches before accumulating authorized totals and cursor pages. Query text matching occurs only for authorized bodies. Sort by created_at, kind, ID descending; cursor binds filter digest and actor. Exclude deleted/unreadable records rather than exposing redacted identifiers. Recheck source access while assembling detail.
- [ ] Merge legacy turns without an execution row; use response evidence only where present, mark unavailable fields unrecorded. Resolve bodies from their original stores. Legacy audit joins by correlation/time are forbidden. Candidate location links use current source APIs. p95 uses the authorized non-null duration population and reports its denominator.
- [ ] Run both test files to PASS and Task 1 DB tests for repository queries. Confirm pagination and aggregate use the same authorized population.
- [ ] Commit only Task 3 files: `feat(rag): expose authorized execution monitoring API`.

## Task 4: 관리자 메뉴와 모바일 상세

**Files:** Create `frontend/src/app/(administration)/admin/rag/executions/page.tsx`, `frontend/src/app/(administration)/admin/rag/executions/[executionId]/page.tsx`, `frontend/src/app/(administration)/admin/rag/executions/legacy/[turnId]/page.tsx`; `frontend/src/features/rag/executions/api.ts`, `ExecutionListPage.tsx`, `ExecutionDetailPage.tsx`, `ExecutionStages.tsx`, `ExecutionMonitoring.module.css`, `ExecutionMonitoring.test.tsx` in that feature directory. Modify `frontend/src/features/navigation/areaMenus.ts`, `frontend/src/shared/routing/routes.ts`, `frontend/src/features/rag/conversation/ConversationAnswer.tsx`, `frontend/src/features/rag/conversation/SearchDiagnostics.tsx`, `frontend/src/features/rag/conversation/EvidencePanel.tsx`, `frontend/src/shared/api/schema.d.ts` (generated).

**Interfaces:** `searchExecutions(request: ExecutionSearchRequest): Promise<ExecutionSearchResponse>` and `getExecutionDetail(id: string, kind: 'execution' | 'legacy'): Promise<ExecutionDetailResponse>` use generated DTOs. Route builders accept IDs only. Existing source viewer receives only authorized source references. Separate read-only answer rendering from conversation submit/consent behavior where necessary.

- [ ] Write Vitest cases: `showsSeparateExecutionAnswerAndQualityStates`, `showsMissingDurationWithoutZero`, `filtersThroughPostBody`, `opensLegacyWithoutGeneration`, `rendersMobileCardsAndVerticalStages`, `restoresFocusAfterSourceDialog`, `hidesAdminLinkForNonadmin`.
- [ ] Run `pnpm --dir frontend test --run src/features/rag/executions/ExecutionMonitoring.test.tsx`; expect missing component failures.
- [ ] Generate API types with `pnpm --dir frontend api:generate`. Add **관리자 → RAG 관리 → 실행 모니터링**. Implement list filters, global filtered statistics, cursor navigation, request cancellation/stale response protection, loading/empty/error/retry states. Detail shows question/answer first, separate statuses, stages and expandable source/score/budget/configuration tabs. Scores are raw labeled values, not fabricated confidence percentages. Display **이전 기록 · 상세 단계 미기록** for legacy. Preserve non-sensitive filters across refresh; never put question search text in URLs or storage. Use cards and vertical stages on mobile, focus trap/Escape/restore in source dialog. Add admin-only turn link.
- [ ] Run the Vitest file, `pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`, `pnpm --dir frontend api:check`; expect PASS. Browser-check desktop/mobile, refresh, source dialog and denied source using the existing login.
- [ ] Commit only Task 4 files: `feat(rag): add execution monitoring screens`.

## Task 5: 기존 환경 통합 검증과 기록

**Files:** Create `docs/worklogs/2026-09-27-rag-execution-monitoring-verification.md`. Modify `WORKBOARD.md`, `docs/runbooks/local-development.md` only if deployment commands change.

**Interfaces:** Uses Tasks 1–4 contracts unchanged; produces a verification report distinguishing implemented, tested and unavailable observations.

- [ ] Add a regression assertion for any uncovered failure from independent review to its owning test file; run it failing before fixing. Do not manufacture tests if review finds no gap.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/executions backend/tests/integration/labs/rag/executions -q`, `backend/.venv/Scripts/python.exe -m ruff check backend/src/ai_workshop/labs/rag/executions backend/tests/unit/labs/rag/executions backend/tests/integration/labs/rag/executions`, `backend/.venv/Scripts/python.exe -m mypy backend/src/ai_workshop`, and Task 4 checks. Also lint changed existing Python files. All must PASS.
- [ ] Apply additive migration/start updated API using the original runbook. Verify existing account/documents/active configuration remain unchanged. Use the existing synthetic PDFs for actual success/insufficiency paths and controlled test doubles for destructive races/provider failures; do not disable a live provider to force an error. Measure stage-recording latency and row bytes versus the previous trace-disabled run, without comparing model variability as deterministic overhead.
- [ ] Obtain independent security/code review and independent original-environment verification. Report login or external-provider blockers exactly; do not claim browser success from API-only tests. Keep ISSUE-00005 open until generative quality is verified in the next plan.
- [ ] Update WORKBOARD (recent completions at most five), link report to existing issue/document history via its supported service, review diff and commit only relevant files: `docs(rag): record execution monitoring verification`. Push after required checks. No fixture/cache deletion without policy authorization.

## Self-review and handoff

Coverage: spec §§4–6 and monitoring parts of §8 map to Tasks 1–5; evaluation detail remains explicitly unverified/unlinked until the second plan supplies real run/case IDs. Review Focus items each have owning tests. No legacy reconstruction, body duplication, new environment or automatic configuration promotion is planned. Execution method and plan review remain pending.
