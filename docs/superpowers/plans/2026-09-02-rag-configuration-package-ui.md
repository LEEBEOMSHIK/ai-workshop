# RAG Configuration Package UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장된 RAG 구성을 파서부터 답변까지 이어지는 하나의 패키지로 이해할 수 있게 표시하고 내부 UUID는 기본 UI에서 감춘다.

**Architecture:** 기존 `ProfileResponse`와 `ModelResponse`를 해석하는 프론트엔드 전용 요약 함수를 두고, 구성 편집기와 저장 카드가 같은 용어를 사용한다. ID는 React identity와 API 요청에 그대로 유지하며 닫힌 기술 상세에서만 표시한다. 현재 백엔드가 고정하지 않는 Parser와 V1에서 지원하지 않는 Reranker·LLM은 실제 상태를 명시하고 값을 추측하지 않는다.

**Tech Stack:** Next.js 16, React, TypeScript, Testing Library, Vitest

**Spec:** `docs/labs/rag/designs/2026-08-30-ai-search-detailed-design.md`의 13~14절

## Global Constraints

- BM25는 검색 방식이고 bi-encoder는 Dense Retriever가 사용하는 임베딩 모델이다.
- Reranker와 LLM은 V1에서 사용하지 않는다.
- 모델명, 버전과 설정값을 업무 코드에 하드코딩하지 않는다.
- UUID는 재현성과 API 계약에 유지하되 기본 사용자 표시에는 노출하지 않는다.
- 파서가 구성에 고정되지 않은 현재 계약을 `형식별 자동 선택 · 현재 구성에 고정되지 않음`으로 표시하고 임의 값으로 대체하지 않는다.

---

### Task 1: 공통 패키지 요약 계약

**Files:**
- Create: `frontend/src/features/rag/configurations/packageSummary.ts`
- Test: `frontend/src/features/rag/configurations/packageSummary.test.ts`

**Interfaces:**
- Consumes: `Profile`, `ModelDefinition`, 선택적 `generationProfile`
- Produces: `summarizeRagPackage(...)`와 Parser·Chunker·Embedding·Retriever·Reranker·LLM 표시 문자열

- [x] **Step 1: 실패 테스트 작성** — parser 키 비신뢰, hybrid, exact disabled·legacy·active reranker와 generation 부재를 fixture로 고정한다.
- [x] **Step 2: RED 확인** — 패키지 구성요소 누락과 UUID 기본 노출로 대상 테스트가 실패하는지 확인한다.
- [x] **Step 3: 최소 구현** — 프로파일 config와 binding을 해석하되 ID 또는 추측한 모델명을 반환하지 않는다.
- [x] **Step 4: GREEN 확인** — 위 테스트가 모두 통과하는지 확인한다.

### Task 2: 구성 편집기와 저장 카드의 패키지 표현

**Files:**
- Modify: `frontend/src/features/rag/configurations/ConfigurationBuilder.tsx`
- Modify: `frontend/src/features/rag/configurations/SavedConfigurationList.tsx`
- Modify: `frontend/src/features/rag/configurations/ConfigurationStudioPage.test.tsx`
- Modify: `frontend/src/app/styles.css`

**Interfaces:**
- Consumes: Task 1의 `summarizeRagPackage(...)`
- Produces: 동일한 단계명과 상태를 보여주는 편집 미리보기 및 저장 패키지 카드

- [x] **Step 1: 실패 통합 테스트 작성** — 저장 카드에 Parser, Chunker, Embedding, Sparse Retriever, Dense Retriever, Fusion, Reranker, Answer Policy, LLM이 모두 표시되는지 검증한다.
- [x] **Step 2: RED 확인** — 기존 카드에 누락된 단계 때문에 실패하는지 확인한다.
- [x] **Step 3: 최소 UI 구현** — 각 단계의 실제 요약을 렌더링하고 패키지 경계를 제목과 카드 구조로 표현한다.
- [x] **Step 4: GREEN 확인** — 구성 Studio 테스트와 타입 검사를 통과시킨다.

### Task 3: 모델 레지스트리 UUID 기본 노출 제거

**Files:**
- Modify: `frontend/src/features/rag/models/ModelLabPage.tsx`
- Test: `frontend/src/features/rag/models/ModelLabPage.test.tsx`

**Interfaces:**
- Consumes: 기존 모델·프로파일의 ID, 이름, 버전, 공개 설정 요약
- Produces: 이름·버전·설정 요약을 기본 표시하고 ID를 닫힌 기술 상세로 이동한 표

- [x] **Step 1: 기존 RED 테스트 확인** — `기술 식별자 보기` 부재와 inline ID 노출로 실패하는지 확인한다.
- [x] **Step 2: 최소 구현** — 행 key는 ID를 유지하고 모델·프로파일 ID 목록을 닫힌 details로 이동한다.
- [x] **Step 3: GREEN 확인** — ModelLabPage 테스트를 통과시킨다.

### Task 4: 전체 회귀 검증과 문서 인계

**Files:**
- Modify: `docs/labs/rag/designs/2026-08-30-ai-search-detailed-design.md`
- Modify: `WORKBOARD.md`

**Interfaces:**
- Consumes: Tasks 1~3의 사용자 계약
- Produces: Parser 고정 계약의 후속 작업과 검증 결과

- [x] **Step 1: 설계 문서 갱신** — 패키지 단계, 미지원 표시, Parser 구성 고정의 후속 계약을 기록한다.
- [x] **Step 2: 검증 실행** — 전체 frontend 테스트, TypeScript, ESLint, production build와 `git diff --check`를 실행한다.
- [x] **Step 3: 독립 리뷰** — Important 이상 finding을 해결하고 재검증한다.
- [x] **Step 4: 작업 보드 종료 갱신** — 최근 완료는 5개 이하로 유지하고 잠긴 pytest 경로를 차단 요소로 남긴다.
