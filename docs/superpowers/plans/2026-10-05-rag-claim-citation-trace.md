# RAG 주장별 인용 기록 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 모델 답변의 정확한 주장 텍스트를 근거 ID와 함께 보존하여 평가 검토 화면에서 경계를 추정하지 않고 확인한다.

**Architecture:** 기존 RAG 생성 결과·비공개 평가 JSON에 선택적 `claim_text`를 추가한다. 기존 권한과 결과 digest 경계를 유지하고 과거 결과를 보충하지 않는다.

**Tech Stack:** Python/FastAPI/Pydantic 2.13.5, 기존 PostgreSQL JSON, Next.js/React/TypeScript.

**Spec:** [ADR-0034](../../decisions/0034-rag-claim-citation-trace.md)

## Global Constraints

- 기존 환경·계정·자료·모델·지침·정책·별칭 동결 조건을 보존한다. 새 환경·DB·계정·worktree를 만들지 않는다.
- 기존 비공개 결과에 새 키가 없으면 직렬화와 SHA-256 digest가 정확히 같아야 한다.
- 주장별 본문을 문장 분할로 재구성하거나 과거 결과에 써넣지 않는다.
- 조회는 현재 소유자와 원문 권한을 그대로 확인하며 모델 호출을 만들지 않는다.
- 다른 작업의 변경·초기 이력 JSON은 수정하지 않는다. staging/commit/push는 이 작업에서 하지 않는다.

## Review Focus

- 여러 문장을 가진 주장과 문장 중간의 연결 구문: 입력 `claim.text` 그대로 보존하는 테스트.
- 과거 JSON의 필드 누락: 원문 dict/canonical bytes/digest 동일성 테스트.
- 같은 답변이지만 주장 경계가 다른 결과: 새로운 digest가 달라지는 테스트.
- 실제 거절·실패 결과: 주장 텍스트를 만들어 넣지 않는 테스트.
- 기존 원문 권한 철회: 현행 소유권/원문 재검증 유지, UI에서 새 호출 없이 표시.

## Task 1: 백엔드 기록과 호환 계약 — main Codex

**Files:** `generation/domain.py`, `generation/citation_validation.py`, `search/schemas.py`, `evaluation/generative.py`, `evaluation/generative_workflow.py`, `evaluation/generative_schemas.py`, `evaluation/generative_read.py`; 관련 단위 테스트.

**Interfaces:** `GeneratedCitation.claim_text: str | None = None`; `ClaimCitation.claim_text`는 값이 없으면 JSON에서 제외; `GenerativeAttemptView.claim_citations: list[ClaimCitation] = []`.

- [x] 기존 경계를 잃는 사례·legacy digest를 재현하는 실패 테스트를 작성하고 실행한다.
- [x] 검증된 `claim.text`를 추가 필드로 복사하고 workflow/API까지 전달한다.
- [x] 새 text 변경의 digest 결속과 과거 JSON 동일성을 확인한다.
- [x] `backend/.venv/Scripts/python.exe -m pytest`로 생성 인용·검색 schema·생성형 평가 관련 파일을 검증하고 Ruff/Mypy를 실행한다. backend cwd의 오프라인 단위 검사에는 실행서의 합성 `AI_WORKSHOP_SECRET_KEY=('offline-test-' * 4)`만 사용했다.

## Task 2: 비교 화면의 정확한 주장·원문 확인 — 기존 프론트 담당

**Files:** `frontend/src/features/rag/configurations/GenerativeEvaluationPanel.tsx`, 필요한 작은 표시 컴포넌트와 관련 테스트. API 생성 타입은 main Codex가 갱신한다.

**Consumes:** Task 1의 선택적 `claim_citations`와 기존 `attempt.sources`. **Produces:** 검토 영역의 기본 접힌 `주장별 인용 근거`, legacy 경계 미기록 설명.

- [x] 정확한 다중 문장 주장·대응 원문 링크·legacy 미기록과 접힘 상태의 회귀를 먼저 실행한다.
- [x] 고정 높이 내부 스크롤을 추가하지 않고 기존 스타일·현재 선택한 시도만 표시한다.
- [x] 관련 Vitest·TypeScript·ESLint를 실행하고 구현 책임과 다른 담당의 리뷰를 받는다.

## Task 3: 본래 환경과 기록 — main Codex + 독립 담당

- [x] 원래 v5 평가의 성공70/실패5와 수정 후 정상 재시도5를 구분해 유지한다. 전체 수정 런타임75건 새 실행·후보 승격으로 보고하지 않는다.
- [x] 과거 실제 결과/판정의 canonical/digest를 읽기 전용으로 대조한다.
- [x] API 타입을 `node frontend/openapi-ts.config.mjs`로 재생성하고 확인한다.
- [x] 새 런타임 반영은 현재 프로세스·모델 슬롯과 실행 주체를 확인한 뒤 API만 필요 범위에서 수행한다.
- [x] 본래 DB outer rollback/savepoint 통합 테스트로 새 주장 텍스트의 JSON/bytes/digest·권한 조회와 시험 run/attempt0건을 확인한다. 기존 global stale 복구 테스트는 진행 중 평가 보존을 위해 실행하지 않는다.
- [x] 본래 UI에서 새 주장 데이터·과거 미기록·원문 접근을 확인하고 DB ISSUE-00021 verified 및 새 보고서의 정확한v1을 관련4문제에 추가 연결한다.
- [x] WORKBOARD를 갱신해 본래 사용자 대화/멀티턴·실패/timeout, 수정 런타임 전체75건 새 평가·후보 승격, 별칭 증거·과거 미종료 복구의 남은 조건을 기록한다.
