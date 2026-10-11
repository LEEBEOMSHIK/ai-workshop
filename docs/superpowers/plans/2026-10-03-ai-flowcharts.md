# AI 기술별 흐름도 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 작업소의 흐름도 메뉴에서 RAG 처리·세션·멀티턴과 개발 에이전트 관리 과정을 기술별로 확인한다.

**Architecture:** 콘텐츠 소유 모듈이 정적 FlowDefinition을 제공하고 app 구성 계층에서 합친다. 공통 뷰어는 주어진 정의만 렌더링하며 기존 작업소 인증과 canonical 메뉴를 재사용한다. 백엔드 API·DB·모델 실행 동작은 변경하지 않는다.

**Tech Stack:** 기존 Next.js App Router, React, TypeScript, CSS Modules, Vitest/Testing Library. 새로운 의존성 없음.

**Spec:** [승인 설계](../specs/2026-10-03-ai-flowcharts-design.md)

## Global Constraints

- canonical 주소: `/workshop/flows`, 상세 주소: `/workshop/flows/{category}/{flow}`.
- 상위는 기술 또는 공통 영역, 하위는 구체적인 흐름이다.
- 한 번에 흐름 하나를 표시한다. 모든 흐름의 상세 설명을 한 페이지에 펼치지 않는다.
- 콘텐츠가 없는 미래 기술의 메뉴나 빈 화면은 만들지 않는다.
- 별도 목록 스크롤·본문 스크롤·설명 스크롤을 중첩하지 않는다.
- 공통 뷰어가 Labs/RAG 구현을 직접 import하거나 백엔드 업무 규칙을 복제하지 않는다.
- 서버에서 저장소 Markdown을 읽거나 임의 경로·HTML·Mermaid 스크립트를 실행하지 않는다.
- 카탈로그는 Git에서 코드와 함께 검토·버전 관리한다. DB 편집·문서 DB 연결은 이번 범위에 추가하지 않는다.
- 기존 서버·계정·DB·문서·RAG 연결을 유지하고 새 테스트 환경을 만들지 않는다.
- `.git` 보호와 기존 미커밋 변경을 보존한다. 커밋은 root만 해당 작업 파일을 검증한 뒤 허용된 권한으로 결정한다.

## Review Focus

- 없는 분류·다른 분류의 flow로 직접 진입: 임의 fallback 대신404와 목록 복귀(작업1·3).
- 여러 종료 분기·되돌아가는 재검토 연결: 방향·조건을 유지하고 유효한 loop를 고립 노드로 오판하지 않음(작업1·2).
- 일반 작업소 사용자의 deep route: 설명은 보이지만 관리자 링크는 전달되지 않음(작업3).
- 긴 단계명·조건문과 좁은 화면: 단어 줄바꿈·세로 흐름으로 본문 가로 넘침 방지(작업2·4).
- 다른 흐름 이동 뒤 이전 단계 선택: 새 흐름 시작 단계로 초기화되고 브라우저 뒤로 가기에서도 선택 흐름 유지(작업2·3).

## 파일과 계약

| 파일 | 책임 |
| --- | --- |
| `frontend/src/features/flowcharts/types.ts` | 공통 콘텐츠 타입 |
| `frontend/src/features/flowcharts/catalog.ts` | 정의 검증·목록 조회 |
| `frontend/src/features/flowcharts/FlowchartsPage.tsx` | 분류·단계 선택과 단일 흐름 화면 |
| `frontend/src/features/flowcharts/FlowDiagram.tsx` | 방향과 조건을 가진 단계 그래프 |
| `frontend/src/features/flowcharts/Flowcharts.module.css` | 기존 토큰 기반 화면·모바일 배치 |
| `frontend/src/features/rag/flows/{ingestion,answer,sessions,multiturn}.ts` | RAG 흐름별 설명과 분기 |
| `frontend/src/features/rag/flows/catalog.ts` | RAG 카탈로그 export |
| `frontend/src/features/project-agents/flows.ts` | 개발 에이전트 운영 흐름(실행 관리 기능 아님) |
| `frontend/src/app/(workspace)/workshop/flows/catalog.ts` | 콘텐츠 합성·서버 권한별 링크 선별 |
| `frontend/src/app/(workspace)/workshop/flows/page.tsx` | 첫 흐름 진입 |
| `frontend/src/app/(workspace)/workshop/flows/[category]/[flow]/page.tsx` | 보호된 상세 화면 |
| `frontend/src/app/(workspace)/workshop/flows/not-found.tsx` |404와 목록 복귀 |

변경 파일은 `shared/routing/routes.ts`, `features/navigation/areaMenus.ts`와 해당 테스트,
`docs/architecture/system-design.md`, `docs/architecture/repository-structure.md`, `WORKBOARD.md`다.
검증 기록은 `docs/worklogs/2026-10-03-ai-flowcharts.md`에 남긴다.

### Task 1: 콘텐츠 계약과 실제 흐름 카탈로그

**Files:** 위 타입·검증·RAG4개 정의·RAG 카탈로그·개발 에이전트 정의.
**Test:** `frontend/src/features/flowcharts/catalog.test.ts`.

**Interfaces:**
- `FlowNode`: `id`, `label`, `kind: start|action|decision|result`, `input`, `process`, `output`, `failures: readonly string[]`.
- `FlowEdge`: `from`, `to`, `condition: string`.
- `FlowLink`: `label`, `href`, `audience: workspace|owner`.
- `FlowDefinition`: `id`, `categoryId`, `categoryLabel`, `title`, `summary`, `version`, `reviewedAt`, `entryNodeId`, `nodes`, `edges`, `links`, `sources: readonly {title:string; reference:string}[]`.
- `validateFlowCatalog(flows: readonly FlowDefinition[]): void`는 잘못된 정의에 명명된 오류를 던진다.
- `findFlow(flows: readonly FlowDefinition[], categoryId: string, flowId: string): FlowDefinition | undefined`.
- `ragFlows`와 `projectAgentFlows`: `readonly FlowDefinition[]`.
- 상위 ID는 `rag`, `common`, 흐름 ID는 `ingestion`, `answer`, `sessions`, `multiturn`, `development-agents`.

- [x] **Step 1:** 유효한 전체 카탈로그, 중복(category,id)/노드, 없는 edge 대상·entry, 도달 불가 노드, 종료 결과에 도달할 수 없는 노드를 검사하는 실패 테스트를 작성한다. 유효한 재검토 loop는 허용한다.

```ts
expect(() => validateFlowCatalog([...ragFlows, ...projectAgentFlows])).not.toThrow();
expect(findFlow(ragFlows, "common", "sessions")).toBeUndefined();
expect(() => validateFlowCatalog([withMissingEdgeTarget])).toThrow();
expect(() => validateFlowCatalog([withReviewLoopAndReachableResult])).not.toThrow();
```

- [x] **Step 2:** `pnpm --dir frontend test --run src/features/flowcharts/catalog.test.ts`를 실행해 정의 부재에 의한 실패를 확인한다.
- [x] **Step 3:** 타입·검증·정확한5개 흐름을 구현한다. 시작점의 forward reachability와 결과 노드의 reverse reachability를 검사한다. 모델·환경·계정 리터럴을 콘텐츠에 넣지 않는다.
- [x] **Step 4:** 승인 설계의 분기와 현재 `conversations/service.py`, `access.py`, 검색 pipeline, ingestion 상태, 개발 에이전트 정본을 대조한다. 제목은 사전검사 후 원자 저장 전에 산출하며 최근10QA는 문맥 후보 상한임을 명시한다.
- [x] **Step 5:** 같은 테스트를 실행해 모두 통과를 확인하고 변경된 파일만 작업 목록에 기록한다. 이 단계에서 Git staging을 실행하지 않는다.

### Task 2: 단일 흐름 뷰어와 접근 가능한 그래프

**Files:** `FlowchartsPage.tsx`, `FlowDiagram.tsx`, `Flowcharts.module.css`.
**Test:** `frontend/src/features/flowcharts/FlowchartsPage.test.tsx`, `FlowDiagram.test.tsx`.

**Interfaces:**
- Task1의 `FlowDefinition`과 `FlowEdge`를 소비한다. 공통 뷰어는 콘텐츠 소유 모듈을 import하지 않는다.
- `FlowchartsPage({flows, selectedFlow, flowHref}: {flows: readonly FlowDefinition[]; selectedFlow: FlowDefinition; flowHref:(categoryId:string,flowId:string)=>string})`.
- `FlowDiagram({flow, selectedNodeId, onSelectNode}: {flow:FlowDefinition; selectedNodeId:string; onSelectNode:(nodeId:string)=>void})`.

- [x] **Step 1:** 한 흐름만 표시, 이름이 보이는2단계 링크, 단계 선택의 입력·처리·출력·실패 설명, 키보드 선택, 흐름 변경 시 선택 초기화, literal text의 HTML 해석 방지를 실패 테스트로 작성한다.

```ts
expect(screen.getByRole("heading", {name: selectedFlow.title})).toBeVisible();
await user.tab(); // 실제 단계 버튼까지 이동하는 helper 사용
await user.keyboard("{Enter}");
expect(screen.getByRole("region", {name: "단계 설명"})).toHaveTextContent(selectedNode.process);
rerenderWithFlow(otherFlow);
expect(screen.getByRole("region", {name: "단계 설명"})).toHaveTextContent(otherEntry.process);
```

- [x] **Step 2:** `pnpm --dir frontend test --run src/features/flowcharts/FlowchartsPage.test.tsx src/features/flowcharts/FlowDiagram.test.tsx`의 red 결과를 확인한다.
- [x] **Step 3:** 세로 단계 노드와 방향이 표시된 연결을 React로 렌더링한다. 연결에는 조건과 도착 단계명을 표시하고 분기/되돌림은 해당 대상 선택으로 이어진다. 결과와 결정 노드는 텍스트·형태로 구분한다. 동일 연결을 따라 읽을 수 있는 텍스트 설명은 접힌 `details`로 제공한다.
- [x] **Step 4:** 선택 단계 설명은 하나의 region에만 표시한다. 분류·그래프·설명에 각각 고정 높이/overflow 스크롤을 만들지 않는다. 기존 색상·간격 토큰을 재사용하고 긴 단어 줄바꿈, `min-width:0`, 모바일 세로 배치 및 focus-visible을 적용한다.
- [x] **Step 5:** 같은 테스트를 통과시킨다. 긴 라벨/조건과 두 종료 분기가 DOM에서 누락되지 않음을 확인한다. layout의 실제 넘침은 작업4 브라우저에서 검사한다.

### Task 3: 보호된 경로와 메뉴 연결

**Files:** 위 flows app 파일과 `shared/routing/routes.ts`, `features/navigation/areaMenus.ts`.
**Test:** `flows/page.test.tsx`, `flows/[category]/[flow]/page.test.tsx`, `flows/catalog.test.ts`, 기존 routes·WorkspaceNavigation 테스트.

**Interfaces:**
- Task1 정의와 Task2 뷰어를 app에서 구성한다.
- `routes.workshopFlows = "/workshop/flows"` 및 `flowchartPath(categoryId:string,flowId:string): string`은 URL segment를 encode한다.
- app `flowCatalogForUser(user:SessionUser): readonly FlowDefinition[]`는 정의를 검증하고 owner 전용 links를 일반 사용자 결과에서 제거한다.
- `/workshop/flows`는 같은 뷰어로 기본 `rag/answer`를 표시한다. 상세 route는 `params:Promise<{category:string;flow:string}>`를 await한다.

- [x] **Step 1:** 메뉴 canonical href, 상세 경로의 current-menu, owner/member link 선별, 잘못된 category/flow의404, 기본/직접 상세 표시를 실패 테스트로 작성한다.

```ts
expect(flowchartPath("a/b", "c/d")).toBe("/workshop/flows/a%2Fb/c%2Fd");
expect(flowCatalogForUser(member).flatMap(flow => flow.links).some(link => link.audience === "owner")).toBe(false);
expect(currentMenuItem("workspace", "/workshop/flows/rag/multiturn")?.label).toBe("흐름도");
```

- [x] **Step 2:** `pnpm --dir frontend test --run 'src/app/(workspace)/workshop/flows' src/features/navigation/WorkspaceNavigation.test.tsx src/shared/routing/routes.test.ts`로 red 결과를 확인한다.
- [x] **Step 3:** route composition에서 기존 `requireWorkspaceUser`로 user를 조회하고 카탈로그를 선별한다. 기존 공통 workspace layout 인증을 유지한다. 잘못된 정의 선택은 `notFound()`로 처리하고 flows의 not-found에 목록 복귀 링크를 둔다.
- [x] **Step 4:** 작업소 메뉴에 흐름도를 한 항목 등록한다. public/admin 메뉴에 중복 등록하지 않는다. 모니터링 링크는 owner에게만 전달하며 실제 `/admin` 권한 검사는 변경하지 않는다.
- [x] **Step 5:** 같은 route/menu 테스트와 기존 workspace layout·server-session 테스트를 통과시킨다. 클라이언트 props에 owner 전용 link가 남지 않는지 확인한다.

### Task 4: 본래 환경 검증과 기록

**Files:** 시스템 설계·저장소 구조의 설명과 링크, 승인 spec 상태, `WORKBOARD.md`, 위 worklog.
**Interfaces:** 앞선 Task1–3의 완성 뷰어·경로만 검증한다. 데이터·모델·서버의 다른 상태는 수정하지 않는다.

- [x] **Step 1:** 다음 명령의 실제 통과를 확인한다. 기존 pnpm 실행 경로가 사용할 수 없으면 같은 frontend 스크립트를 기존 Node/pnpm 실행 파일로 호출하고 결과를 기록한다.

```powershell
pnpm --dir frontend test --run src/features/flowcharts src/features/navigation src/shared/routing src/shared/auth 'src/app/(workspace)/workshop/flows' 'src/app/(workspace)/workshop/layout.test.tsx'
pnpm --dir frontend typecheck
pnpm --dir frontend lint
```

- [ ] **Step 2:** 사용자 기존 로그인 세션으로 `/workshop/flows`와5개 상세 화면을 확인한다. 목록 이동·단계 선택·뒤로 가기·새로고침·없는 상세404를 확인한다. 인증 세션이 없으면 인증된 검증은 미완료로 기록하고 비로그인 흐름·정적 검증을 먼저 진행한다. 계정 생성·토큰 추출·DB 직접 수정은 하지 않는다.
- [ ] **Step 3:** 실제 브라우저에서 데스크톱과 좁은 폭으로 분류·메뉴·텍스트/분기·키보드 선택을 확인한다. `scrollWidth <= clientWidth`와 각 영역에 중첩 overflow가 없는지 확인하고 긴 라벨도 읽히는지 시각적으로 검사한다.
- [x] **Step 4:** native health18000/프론트5173 응답을 확인한다. RAG 생성·미종료 별칭 정상화가 검증된 것으로 확대 보고하지 않는다.
- [x] **Step 5:** 구현과 분리된 리뷰어에게 변경 파일·spec·검증 증거를 전달해 코드/노출/실제 흐름 일치를 검토받는다. 결함 수정 뒤 영향 검증만 반복한다.
- [x] **Step 6:** 문서 링크·placeholder·whitespace를 검사하고 `git -c core.excludesFile=C:/projects/ai-workshop/.git/info/exclude diff --check -- <이번 변경 파일>`을 실행한다. worklog에 실제 결과와 로그인 등 미완료 항목을 남긴다. WORKBOARD 최근 완료는 최대5개를 유지하고 본래 별칭 차단 기록을 보존한다.
- [x] **Step 7:** root가 해당 작업의 파일만 커밋 대상으로 검토한다. 보호된 `.git` 승인 없이 staging·commit·push하지 않으며 현재 작업에서 커밋/푸시가 실행되지 않으면 명시한다.

## 실행 인계

권장 방식은 **Native**다. 작은 카탈로그·뷰어·route가 같은 타입에 의존하므로 메인 Codex가 이 세션에서 구현하고, 마지막에 별도 리뷰어가 검증하는 편이 적합하다.
대안은 작업마다 별도 구현자와 검토자를 두는 **Subagent-driven**이다.
사용자가 2026-10-03 작성된 계획과 Native 실행을 승인했다. 작업1–3 구현 및 독립 검토 수정 완료, 작업4의 최종 자동 검사·본래 브라우저 검증을 진행한다.
