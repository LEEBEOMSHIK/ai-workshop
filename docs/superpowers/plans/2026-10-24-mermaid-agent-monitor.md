# Mermaid 실행 모니터링 구현 계획

> **For agentic workers:** 사용자 지정 화면 변경을 현재 작업 공간에서 실행한다. 메인은 통합·흐름도, 화면 담당은 모달, 독립 담당은 검증/리뷰를 맡는다. 커밋·푸시는 하지 않는다.

**Goal:** Mermaid로 연결된 단계를 자유롭게 이동하고 클릭해 정리된 실제 지침·입력·결과 모달을 연다.
**Architecture:** 기존 AgentTrace 계약과 ACL/보관 정책을 유지한 프론트엔드 변경. Mermaid 초기 SVG와 상호작용 어댑터, 독립 단계 상세 모달로 분리한다.
**Tech Stack:** 기존 React/TypeScript/CSS modules/Vitest, 고정 Mermaid 로컬 패키지.
**Spec:** [화면·조작·보관 계약](../specs/2026-10-24-mermaid-agent-monitor-design.md).

## 공통 제약과 리뷰 초점

- 모델/임베딩0, DB·API 계약 변경0. 기존155파일 기준선을 보존한다.
- 동일 이름/다른 ID, 잘못된 parent·순환·미연결,64개 단계와 긴 이름.
- 드래그 종료 클릭 오인·포인터 취소·확대 후 좌표·실행 전환 중 비동기 렌더.
- 보관 금지 상태의 DOM 비노출·악성 Mermaid/HTML 이름·임의 JSON 키.
- Escape/Tab 포커스·호출 노드 복귀·모바일 오버플로·긴 본문.
- 그래프 렌더 실패 시 전체 기록 상세 조회와 오류 표시.

## 1. Mermaid 그래프와 이동 (메인)

Files: `AgentFlowDiagram.tsx`, 새 `mermaid-agent-graph.ts`, `mermaid-graph-interaction.ts`, `MermaidAgentDiagram.module.css`, 해당 테스트, `frontend/package.json`/`pnpm-lock.yaml`.

Interface: `AgentFlowDiagram({flow, selectedId?, detailId, onSelect})`를 유지한다. 모든 span ID는 기존 `flow.byId`에서 읽고 parent 관계는 `flow.children`의 검증된 연결을 따른다. `onSelect(spanId)`가 모달 선택을 전달한다.

- [x] 모든 단계/실제 연결/문법 인코딩/같은 이름/순환 경계와 이동 기하·클릭 분리 테스트를 먼저 작성해 RED 확인.
- [x] 공식 패키지 버전·호환성 확인 후 필요한 Mermaid만 추가. 동적 로딩과 strict 설정으로 초기 SVG 렌더링.
- [x] 노드 이동·연결선 갱신·이동/확대·화면 맞춤/배치 초기화·키보드·비동기 수명주기 처리.
- [x] 해당 테스트 GREEN·타입·린트 확인.

## 2. 읽기 쉬운 단계 모달 (화면 담당)

Files: 새 `AgentSpanModal.tsx`, `AgentSpanModal.module.css`, `AgentStructuredContent.tsx` 및 해당 테스트. 다른 제품 파일 수정은 메인에게 요청한다.

Interface: `AgentSpanModal({span, parent?, flow, showCompleteBody, onClose})`. 기존 `AgentSpan`/`AgentFlow`를 사용한다. 모달을 열기 전 포커스 요소를 보관하고 닫힌 후 복귀한다. 에이전트 관측 설명은 현재 `AgentObservation`을 재사용할 수 있으나 직접 순환 import를 만들지 않는다.

- [x] 지침/입력/결과 표시·알려진 JSON 구조·미보관/검증 실패 DOM 비노출·빈/긴/알 수 없는 본문·Escape/Tab/복귀 테스트 RED.
- [x] 접근 가능한 모달과 구조화된 본문 표시 구현. 원문/해시·원문 링크 유지, 실제 본문만 표시.
- [x] 해당 테스트 GREEN·타입·변경 린트 결과 인계.

## 3. 통합과 검증 (메인 + 독립 검증)

Files: `AgentTracePanel.tsx`, `AgentTracePanel.module.css`, 기존 흐름도/패널/실행 통합 테스트. 필요 시 실행 상세의 답변·요약 배치는 현재 사용자 요청 범위 안에서만 조정한다.

- [x] 그래프/전체 기록 선택 시 모달 열림, 다른 실행 전환 시 닫힘, 데이터 갱신/누락 회귀 RED.
- [x] 기존 하단 상시 상세를 모달로 교체해 기본 화면의 반복 본문을 줄인다. 정책 경고·전체 단계 목록·실행 기록 정보 유지.
- [x] `pnpm test --run src/features/rag/executions` 및 영향 대화 진단 테스트, `pnpm typecheck`, 변경 파일 ESLint.
- [x] CUA로 본래 로그인된 기존 실행의 실제 Mermaid·이동/키보드·모달·본문/원문 정책과320/375/1280px 확인. 실제 호출 없음.
- [x] 독립 테스트/리뷰 결과를 반영하고 기존 변경 SHA·diff·문서 계약 검사.
- [x] ISSUE-00035/작업 기록/WORKBOARD에 구현·실제 검증·남은 경계를 누적한다.

역할 선택기의 최초 잘못된 signal `feature-or-bugfix`는 거부됨을 확인하고 정본 `feature-implementation`으로 수정했다. 최종 필수 역할은 frontend-engineer, requirements-implementation-designer, test-designer, integration-e2e-verifier, independent-code-reviewer다.

완료 근거와 실제 검증 경계: [작업 기록](../../worklogs/2026-10-24-mermaid-agent-monitoring.md).
