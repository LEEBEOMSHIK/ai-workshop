# Agent Step Retention Implementation Plan

> **For agentic workers:** Use the repository project-agent roles, implementation boundaries and independent verification. Preserve the existing working changes; no commit/push is requested.

**Goal:** 실제 SDK 단계의 지침·입력·결과를 비공개 DB에 보관하고 권한 확인 후 다시 조회한다.

**Architecture:** 기존 execution trace JSON을 단일 본문 저장소로 사용한다. 메타데이터 projection과 본문 보관 projection을 분리하고 기존 대화/평가 결과와 ACL을 재사용한다.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/PostgreSQL, Python Agents SDK, Next.js/React, pytest, Vitest.

**Spec:** [ADR-0040](../../decisions/0040-private-agent-step-content.md)

## Global Constraints

- 기존143개 dirty 파일 기준을 `.local-data/project-agent-work/agent-trace-retention-20261023/baseline-sha256.json`에 보존한다. 현재 작업 의존 변경이 이 checkout에 있어 별도 복제·설치·worktree를 만들지 않는다.
- 새 LLM/임베딩 호출, 일반 worker 시작, 모델 다운로드, 재색인, 임의 DB 보정, 커밋·푸시는 없다.
- 본문 최대32,768자, 실행 총131,072자, 최대64단계를 유지한다. 인증·예외 원문·내부 추론과 실제 사용자 본문을 로그·테스트 fixture·Git에 기록하지 않는다.
- 본문은 execution에만 보관한다. 대화/평가 중복 JSON은 metadata only, 기존 데이터는 무변경이다.
- 기존 현재 대화의 검증 실패 초안 가림은 유지하고, 관리자 실행 상세의 관측 반환값은 검증된 최종 답변과 구분한다.

## Review Focus

- include_diagnostics=false인 실행/평가도 본문을 보관하며 현재 응답 노출은 요청 옵션을 따른다.
- 레거시 complete 필드나 손상된 크기/해시는 새 보관 기록으로 간주하지 않는다.
- 사용량 await 중 권한 회수·actor/turn 연결 변경 후에는 상세 본문을 반환하지 않는다.
- 관측 원문은 요청 경계의 실제 값이고 모델 내부 추론이나 예외/인증 필드를 포함하지 않는다.
- 단계의 해당 없음·빈 문자열·한도 초과·실패를 숨기지 않으며 새로고침/ID 변경에도 오래된 본문이 남지 않는다.

## Task 1: 백엔드 수집·저장·조회

**Owner:** backend/database/test design 역할 (`sdk_runtime`).

**Files:** `executions/agent_trace.py`, `observer.py`, `repository.py`, `service.py`; `search/pipeline.py`; `orchestration/domain.py`, `openai_agents.py`, `sdk_hooks.py`; 필요한 conversation/evaluation 저장 경계 및 관련 unit/integration tests. 최종 정확한 변경 목록은 작업 기록에 남긴다.

**Interfaces:** `AgentTrace.content_retention` (`metadata_only` 기본, 신규 `retained`), `AgentContent.content_status`에 `not_applicable` 추가. private 저장과 metadata projection을 분리하고 기존 상세 API의 `agent_trace`에 권한 확인된 저장 본문을 반환한다.

- [x] 수집/저장/재조회, 비진단 실행, 레거시/중복/손상/권한 회수 실패 테스트 RED 확인.
- [x] 실제 agent 입력을 연결하고 observer/repository의 private 보관을 구현한다.
- [x] conversation/evaluation JSON 메타데이터 보존, 상세 최종 ACL/연결 재검증을 연결한다.
- [x] 관련 pytest, Ruff, Mypy 및 기존 DB rollback 통합 검증을 통과시킨다.

## Task 2: 화면 본문 조회

**Owner:** frontend/test design 역할 (`agent_monitor_ui`).

**Files:** `AgentTracePanel.tsx` 및 관련 panel/execution/diagnostics 테스트와 `agent-trace.fixture.tsx`. 필요 없는 그림/CSS 수정은 하지 않는다.

**Interfaces:** 새 API 계약의 retained body를 history에서 표시한다. metadata_only/미수집은 당시 상태로 설명한다. 최종답변과 관측 반환값의 의미를 명시한다.

- [x] 새로고침 상세 본문, legacy, 빈 문자열, 미해당, 한도/실패, HTML 비실행, 권한/ID 전환 테스트 RED 확인.
- [x] 기존 선택·키보드·반응형 구조를 보존하며 본문 표시와 안내를 수정한다.
- [x] 관련 Vitest, 전체 typecheck, 변경 ESLint 검증.

## Task 3: 통합과 독립 검증

**Owner:** 메인 통합; `sdk_monitor_review` 독립 security/privacy/integration/code review. 검증자는 제품 코드를 수정하지 않는다.

- [x] 메인이 OpenAPI 타입 생성/검사, 설계/runbook 정본 갱신.
- [x] 독립 reviewer가 수집→저장→조회, 현재 ACL/소유권/연결, 단일 본문 저장·한도·과거 호환성을 검사한다.
- [x] 본래 과거 실행 안내와 실제 CSS 합성 retained body의 새로고침/클릭을 확인한다. 새 실모델 검증은 별도 범위로 남긴다.
- [x] 관리자 문제 이력에 원인/구현/실제 검증 범위를 기록하고 WORKBOARD·worklog·보존 SHA 비교를 마감한다.

## 선택한 범위

사용자가 지정한 수집→보관→조회 자체가 승인된 변경 범위다. 단일 비공개 저장, 기존 관측 상한과 현재 ACL을 적용하는 구현 선택은 메인의 판단이다. 기록 당시 결과를 보존하고 현재 지침으로 과거 본문을 만들어 넣지 않는다. 모델 재실행 없이 가능한 검증을 우선 완료한다.
