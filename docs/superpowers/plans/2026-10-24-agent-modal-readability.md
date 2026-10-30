# 단계 모달 가독성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. 사용자 피드백을 기존 승인된 모달의 후속 개선으로 실행하며 추가 승인 절차를 만들지 않는다.

**Goal:** 역할·요청·결과를 먼저 읽고 원문·기술 기록을 필요할 때 펼치는 모달.
**Architecture:** 기존 AgentSpan/보관 계약을 읽는 프론트엔드 표현 계층만 변경한다. 핵심 필드 선택은 결정론적이며 전체 원문은 기존 컴포넌트로 보존한다.
**Tech Stack:** 기존 React/TypeScript/CSS Modules/Vitest, 새 의존성 없음.
**Spec:** [가독성 설계](../specs/2026-10-24-agent-modal-readability-design.md)

## Global Constraints

- 본문 허용 판정 전 파싱 금지. 미보관·검증 실패 본문 DOM 비노출.
- 저장된 역할/관계/문자열만 사용. 이름·질문·업체에 맞춘 하드코딩과 자동 LLM 요약 금지.
- 출력은 관측 결과이며 품질 통과로 표시하지 않는다. 모델 호출0, commit/push0.
- 기존 Mermaid 이동·선 연결·모달 포커스 계약 유지. 현재174개 변경 보존.

## Review Focus

- JSON 모양이 다른 모델/위임/도구 기록도 요청·반환 의미를 바꾸지 않는다.
- 근거 사용 가능 개수를 실제 전달·인용 개수로 표시하지 않는다.
- 권한 없는 본문은 핵심 추출·접힌 영역·DOM 모두에 없어야 한다.
- 동일 질의 반복, 긴 지침/답변·ID, 구조 미상 데이터가 핵심 내용을 밀어내지 않는다.
- 접힌 상세, 같은 이름의 다른 단계, Escape/Tab 복귀와 320px 표시를 유지한다.

## Task 1 — 모달 구조와 검증

담당: frontend-engineer + test-designer. 기존 AgentSpanModal.tsx/module.css/test.tsx와 필요한 새 핵심 표시 모듈/테스트만 수정한다. AgentStructuredContent는 전체 상세 용도로 유지한다. 부모 AgentTracePanel API와 Mermaid 코드는 변경하지 않는다.

- [x] 핵심 질문·답변 우선, ID/지침 상세 접힘, unknown/denied/0/failed 모델·위임 사례의 실패 테스트를 먼저 확인한다.
- [x] 의미가 분명한 필드 선택과 화면 계층을 구현하고 기존 원문 표시 경로를 보존한다.
- [x] 관련 테스트·TypeScript·변경 ESLint 결과를 인계한다.

## Task 2 — 독립 검증과 본래 화면

담당: independent-code-reviewer + integration-e2e-verifier는 구현과 분리. 메인은 브라우저·통합·문서만 담당한다.

- [x] 독립 리뷰에서 사실성·비노출·크기 제한·키보드 계약을 확인하고 필요한 경계 검사를 추가한다.
- [x] `pnpm exec vitest run src/features/rag/executions src/features/rag/conversation/SearchDiagnostics.test.tsx --reporter=dot`, `pnpm typecheck`, 변경 TS/TSX ESLint를 확인한다.
- [x] 본래 로그인된 기존 실행에서 역할/질문/결과의 첫 화면, 지침/원문 열기, 320/375/1280px, Escape 복귀를 확인한다. 모델을 재실행하지 않는다.
- [x] 기준 해시 비교, ISSUE-00035/WORKBOARD/작업 기록, 최종 캡처로 마감한다.
