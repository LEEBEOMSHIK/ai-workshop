# RAG Generative Evaluation Alignment Implementation Plan

진행 상태(2026-09-28): 사용자 승인 후 메인 직접 구현·독립 최종 리뷰 방식으로 Tasks 1–4를 구현하고 본래 환경에 반영했다. Task 5의 실모델 평가·브라우저·문제 이력 DB 연결은 기존 로그인 대기다. 세부 실행과 검증의 정본은 [완료/미검증 구분 기록](../../worklogs/2026-09-28-rag-generative-evaluation-verification.md)이다. 기존 v1 보존을 위해 `generative_*` 모듈로 나누었으며 DB 보완은0057–0059 추가 migration으로 반영했다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평가가 실제 대화와 같은 근거 선택·생성·인용 검증을 실행하고 그 결과로 품질 개선과 승격을 검증한다.

**Architecture:** live/frozen 입력 어댑터가 하나의 RAG 실행 코어를 사용한다. 기존 추출형 지표 v1은 보존하고 생성형 원시 관측·정답 판정·승격 검증을 별도 버전으로 추가한다.

**Tech Stack:** Python/FastAPI, Celery, PostgreSQL, SQLAlchemy/Alembic, Next.js/React, pytest/Vitest.

**Spec:** [승인 설계](../specs/2026-09-27-rag-execution-monitoring-and-evaluation-design.md)

## Global Constraints

- [실행 모니터링 계획](2026-09-27-rag-execution-monitoring.md)의 실행 ID·observer·권한 조회 계약을 선행한다.
- 기존 환경·계정·자료를 보존한다. 별도 환경·DB·계정·worktree를 생성하지 않는다.
- 실제 대화와 평가의 알고리즘은 같고 입력 scope 해석만 다르다. frozen snapshot을 외부 전송 승인으로 사용하지 않는다.
- 기존 BM25/추출형 지표를 변경하거나 그 통과를 생성형 통과로 복사하지 않는다.
- 공급자 오류를 숨기거나 다른 모델로 전환하지 않는다. 정답 판정 근거가 없으면 미검증이다.
- 모델·임계값·문항별 예외를 업무 코드에 고정하지 않는다. 후보 구성은 검증 전 활성화하지 않는다.
- 검증은 원본 환경과 합성 자료로 수행한다. DB 생성 fixture를 사용하지 않고 DB 쓰기 테스트는 주입된 연결의 rollback으로 끝낸다.

## Review Focus

- 스냅샷 이후 정확한 revision 승인이 철회됨: 생성 직전 거부하고 외부 호출이 없어야 한다(Task 1, 2).
- 동일 입력인데 실제 대화와 평가의 근거 선택이 다름: 공유 코어와 parity 테스트로 차이를 검출한다(Task 1).
- 올바른 인용 ID지만 틀린 내용/음성 질문에 답변: 생성 성공·인용 통과와 정답/거절 판정을 분리한다(Task 2, 3).
- 중복 worker/재시도/오래된 claim: 같은 attempt 중복 완료를 거부하고 과거 실패를 보존한다(Task 2).
- 조작된 scalar metrics·다른 구성 버전·불완전 사례: DB 승격 게이트가 거부한다(Task 3).

---

## Task 1: 실제 검색과 생성 평가의 공통 코어

**Files:** Create `backend/src/ai_workshop/labs/rag/search/pipeline.py`; `backend/src/ai_workshop/labs/rag/evaluation/generative_adapter.py`; `backend/tests/unit/labs/rag/evaluation/test_pipeline_parity.py`. Modify `backend/src/ai_workshop/labs/rag/search/service.py`, `backend/src/ai_workshop/labs/rag/evaluation/tasks.py`, `backend/src/ai_workshop/labs/rag/search/configuration_port.py`, `docs/labs/rag/design.md`; create `docs/decisions/0030-rag-generative-evaluation.md`.

**Interfaces:** Move `SearchResult` and the existing `SearchSourceResolverPort` to `pipeline.py` with compatibility imports. `PipelineInput` contains actor ID, original/resolved query, existing `ResolvedSearchScope`, `ResolvedSearchConfiguration`, typed conversation history and source resolver. `RagExecutionPipeline.execute(request: PipelineInput, *, observer: ExecutionObserver | None = None) -> SearchResult` is async. `FrozenGenerativeAdapter.prepare(actor_id: UUID, candidate: CandidateExecutionInput, case: EvaluationCase) -> PipelineInput` is async; `EvaluationCase` is the existing type from evaluation/domain.py. Frozen input includes physical index UUID/builds, immutable source snapshot and exact generation profile version; live resolution stays in the existing application service.

- [ ] Write `test_live_and_frozen_select_same_units_and_citations`, `test_budget_and_threshold_apply_in_both_paths`, `test_revoked_revision_approval_blocks_generation`, `test_extractive_v1_unchanged`. With deterministic fake retrieval/embedding/runtime, assert selected IDs, ordering, insufficiency and citation validation are identical; denied external approval means provider call count zero.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/evaluation/test_pipeline_parity.py -q`; expect missing shared core failures.
- [ ] Update ADR/design, then extract the existing retrieval→source resolution→selection→context budget→generation→citation path without algorithm changes. Inject live/frozen adapters and current external-approval validation. Keep the request embedding cache. Freeze history as part of an evaluation input when provided; never reuse a mutable live conversation implicitly. Do not repoint frozen evaluation at the current active alias or silently ignore incompatible snapshots.
- [ ] Run the new test and `backend/tests/unit/labs/rag/search/test_context_generation.py`, `backend/tests/unit/labs/rag/search/test_generation_policy_gate.py`, `backend/tests/unit/labs/rag/evaluation/test_evaluation_evidence_top_k.py` with pytest; expect PASS.
- [ ] Commit only Task 1 files: `refactor(rag): share live and evaluated generation pipeline`.

## Task 2: 버전된 생성형 평가와 시도별 실행

**Files:** Create `backend/src/ai_workshop/labs/rag/evaluation/generative.py`; `backend/alembic/versions/0055_generative_evaluation.py`; `backend/tests/unit/labs/rag/evaluation/test_generative_workflow.py`. Modify `backend/src/ai_workshop/labs/rag/evaluation/domain.py`, `models.py`, `repository.py`, `service.py`, `tasks.py`, `schemas.py`, `api.py` in that directory; `backend/src/ai_workshop/labs/rag/executions/models.py` and `service.py`.

**Interfaces:** New explicit kind `generative` and metric version `generative-v1`; leave existing v1 identifier unchanged. `GenerativeObservation` holds execution_id, retrieved/selected/cited evidence IDs, generation status, citation validity, failure stage, durations, requested/observed model and environment snapshot. Body lives only in a private evaluation result, never execution metadata. `ExpectedAnswerRule` holds version, required evidence groups, expected answer status and optional deterministic required/forbidden propositions. `CorrectnessJudgment` holds status passed/failed/unreviewed, provenance rule/reviewer, rule version or reviewer ID, reason and result digest. `evaluate_generative(observation: GenerativeObservation, rule: ExpectedAnswerRule, judgment: CorrectnessJudgment | None) -> GenerativeMetrics` returns separate retrieval/context coverage, generation, citation, correctness, abstention and latency fields; unknown values remain null.

- [ ] Write tests: valid citation plus unreviewed content remains unreviewed; negative answered case fails abstention; missing required context fails coverage; repeated delivery cannot call provider twice; retry creates a new attempt retaining the old failure; changed approval blocks call; stale claim cannot complete.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/evaluation/test_generative_workflow.py -q`; expect missing workflow failures.
- [ ] Add additive schema and immutable attempt/input snapshot records, explicit kind/version, generation profile/prompt/runtime binding, approval decision references, linked execution ID and raw observations. A pending evaluation starts only through existing authorized evaluation submission, not monitoring GET. Preserve current repetition counts and claim fences. Server allocates each attempt/execution pair; retry is explicit and separately visible. Attach the now-defined attempt FK to execution records. Keep source references verifiable against frozen snapshots and current read rights.
- [ ] Add generated-answer private result storage under existing evaluation access/deletion rules; protect judgment provenance and exact result digest from scalar worker overrides. Do not persist prompt/provider error bodies. Record measured token counts only when reported; serialized bytes are labeled bytes. Implement the shared-core adapter call and separate metrics. Rule-based matches report their rule scope, not general semantic correctness.
- [ ] Run workflow/parity tests plus `backend/tests/unit/labs/rag/evaluation/test_evaluation_service.py` using pytest; expect PASS. Inspect migration SQL before applying through the original runbook.
- [ ] Commit only Task 2 files: `feat(rag): record generative evaluation attempts and judgments`.

## Task 3: PostgreSQL 검증과 승격 계약

**Files:** Create `backend/alembic/versions/0056_generative_evaluation_gate.py`; `backend/tests/unit/labs/rag/evaluation/test_generative_acceptance.py`; `backend/tests/integration/labs/rag/evaluation/test_generative_gate_existing_db.py`. Modify `backend/src/ai_workshop/labs/rag/configurations/repository.py`, `backend/src/ai_workshop/labs/rag/domains/service.py`, `backend/src/ai_workshop/labs/rag/evaluation/repository.py`, `backend/src/ai_workshop/labs/rag/evaluation/generative.py`, `docs/decisions/0030-rag-generative-evaluation.md`.

**Interfaces:** `GenerativeAcceptancePolicy` is immutable/versioned and records minimum context coverage/correctness/abstention plus required no-exposure and valid-citation constraints. Candidate acceptance binds policy version, exact configuration/generation profile, dataset/expected-rule digest and complete attempt set. Extend DB verification/promotion functions through a new migration; do not edit historical migration 0010. Existing live connections remain operational; only a new generative acceptance/promotion requires new proof. Existing extractive badges retain their scope.

- [ ] Write tests `test_rejects_scalar_only_pass`, `test_rejects_extract_only_evidence_for_generative_promotion`, `test_rejects_wrong_profile_or_rule_digest`, `test_rejects_missing_unreviewed_cases`, `test_valid_complete_run_passes`, `test_existing_domain_not_disabled`. Assert database rejects forged observations/provenance, not just Python checks.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/labs/rag/evaluation/test_generative_acceptance.py -q`; expect missing gate failures.
- [ ] Implement DB recomputation from immutable observations and authoritative rules/judgments; validate evidence membership, generation/citation status, dataset completeness, repetitions and version bindings. Validate reviewer provenance through the authorized review operation. A worker-supplied correctness scalar is never qualifying evidence. Reuse existing extraction metrics and exposure checks; all new generative metrics have explicit denominators and missing counts. No fixed pass threshold in the handler: require the saved acceptance policy.
- [ ] Add rollback-only integration cases with existing actor references and synthetic evaluation rows. Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/labs/rag/evaluation/test_generative_gate_existing_db.py -q` after the additive migration. Expect PASS and unchanged existing account/domain/active configuration. Never run existing database-creation fixtures against this environment.
- [ ] Commit only Task 3 files: `feat(rag): verify generative promotion evidence in postgres`.

## Task 4: 평가 화면과 실행 상세의 양방향 연결

**Files:** Modify `frontend/src/features/rag/configurations/ConfigurationStudioPage.tsx`, `ComparisonPanel.tsx`, `EvaluationAuthoringPanel.tsx`, `ConfigurationStudioPage.test.tsx` in that directory; create `frontend/src/features/rag/configurations/GenerativeEvaluation.test.tsx`; modify `frontend/src/features/rag/executions/ExecutionDetailPage.tsx`, `frontend/src/shared/routing/routes.ts`, `frontend/src/shared/api/schema.d.ts` (generated), `backend/src/ai_workshop/labs/rag/evaluation/api.py`, `schemas.py`, `backend/src/ai_workshop/labs/rag/executions/schemas.py`, `service.py`.

**Interfaces:** Configuration deep-link uses `?tab=comparison&run=<UUID>&case=<UUID>`. Each evaluation attempt returns nullable execution_id and explicit kind/metric version. Detail returns a link only with actual authorized run/case IDs. Existing evaluated rows without linkage remain unlinked; never infer by question hash.

- [ ] Write tests `deepLinkSelectsExactRunCaseAfterRefresh`, `showsExtractiveAndGenerativeSeparately`, `doesNotLabelCitationValidityAsCorrectness`, `showsAttemptFailuresAndUnreviewed`, `openingEvaluationDoesNotStartRun`.
- [ ] Run `pnpm --dir frontend test --run src/features/rag/configurations/GenerativeEvaluation.test.tsx`; expect missing behavior failures.
- [ ] Implement explicit evaluation kind and acceptance-policy selection with existing authorization/consent flows. Show separate coverage/generation/citation/correctness/abstention/duration metrics and missing denominators. Add reviewer controls only through an authorized judgment API bound to exact result digest; show author/time/provenance. Link execution↔run/case and preserve selected tab/run/case on refresh. Handle stale/deleted/no-access targets without disclosing bodies.
- [ ] Run `pnpm --dir frontend api:generate`, the new Vitest tests and ConfigurationStudioPage tests, `pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`, `pnpm --dir frontend api:check`; expect PASS.
- [ ] Commit only Task 4 files: `feat(rag): expose generative evaluation results and trace links`.

## Task 5: 기존 PDF로 후보 구성 검증과 보고

**Files:** Create `docs/worklogs/2026-09-27-rag-generative-evaluation-verification.md`. Modify `WORKBOARD.md`. Store approved synthetic execution snapshots through existing evaluation APIs; temporary measurement artifacts belong under ignored `.local-data/pdf-corpus-qa/`, never a new DB or raw private Git fixture.

**Interfaces:** Uses the new authorized evaluation API and immutable policy from Tasks 2–3; produces run IDs, per-case execution IDs, ground-truth/rule versions, result judgments and a report. Does not introduce a query-specific retrieval rule.

- [ ] Before candidate evaluation, freeze a held-out set containing paraphrase, cross-document, follow-up, numeric/date, ambiguous and absent-answer cases. Keep the answer key outside ingestion. Use existing 3 synthetic PDFs and original 16 questions as the baseline set. Record which cases are rule-checked versus manually judged.
- [ ] Evaluate saved candidate versions for the previously measured context limits and thresholds without changing the active configuration. Compare same snapshot, runtime, warm/cold state and repetition count. Run actual generation only on exact approved revisions under the existing policy. Capture all stages, selected evidence, answer, citation validity, correctness/abstention and latency separately. Choose using saved acceptance policy and held-out results; do not tune on the held-out set after viewing its answers.
- [ ] Run relevant new backend test files, `backend/.venv/Scripts/python.exe -m mypy backend/src/ai_workshop`, Ruff on all changed Python files and Task 4 frontend checks. Obtain independent review of DB gates, permission boundaries and live/frozen parity. Fix any findings with a reproducing test before claiming PASS.
- [ ] If a candidate qualifies, use normal acceptance/domain connection operations to apply that exact version, preserving previous version for rollback. If none qualifies, leave active configuration unchanged and report the failing stages. Verify actual browser question→answer→execution detail→original citation→evaluation case on existing login, plus mobile and resumed conversation. Missing login means browser verification remains explicitly pending, not API success substituted for it.
- [ ] Record sample counts/median/p95/missing timings and precise errors in the report. Update existing ISSUE-00005 with linked DB document through supported history services; close only if its quality criteria are verified. Update WORKBOARD, commit only relevant files and push after checks. Do not delete original data or temporary alternate environments merely because this plan finishes.

## Self-review and handoff

Spec §7 maps to Tasks 1–4, candidate verification in §8 to Task 5. Direct implementation and independent final review were approved and performed. Important findings were reproduced and fixed in one pass. Implementation and automatic checks are recorded in the linked report; original-login browser and actual candidate quality verification remain pending.
