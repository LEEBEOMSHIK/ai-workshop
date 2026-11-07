# 디자인 시스템 화면별 적용 현황

로그인 화면(2026-11-07)은 별도 LoginLayout에서 기존 로고만 상단에 표시한다. 후속 요청에 따라 로그인 화면의 ThemeChoice는 제거했으며 다른 화면의 모드 설정은 유지한다. 사이드바 없이 로그인 폼을 중앙에 배치하고 Button·색상·여백·초점 토큰을 재사용한다. 공개 페이지와 작업소 탐색 메뉴는 유지한다. [구현·검증 기록](../worklogs/2026-11-07-login-layout.md)

학습 업무 분야 선택(2026-11-06)은 공통 CheckboxField·TextField·Button을 사용하며 기존 분류값을 유지한다. 학습 연결은 인접 카드 장식선 대신 명시된 출발 차수에서 후속 카드로 향하는 연결선을 사용하며 사용자 승인 타임라인 시안에 따라 작은 원형 순번1·2를 자기 카드와 가로선으로 묶고 실제 계승만 원 사이 화살표로 연결한다. 카드 제목은 옅은 표면으로 강조한다. [시안 적용](../worklogs/2026-11-06-learning-timeline.md)을 참고한다. 연결 표시 후속 검증은 [목록 순번과 연결선](../worklogs/2026-11-06-learning-number-connections.md)에 남긴다. 상세 범위와 검증은 [작업 기록](../worklogs/2026-11-06-learning-categories-lineage.md)에 남긴다.

화면 모드와 계정 설정은 공통 탐색 메뉴 하단에서 연다. 로그인한 사용자는 같은 패널에서 계정 이름·역할 확인과 로그아웃을 할 수 있다. 펼친 메뉴의 기본 너비는 288px이고 작업소에서는 256~400px로 조절한다. 대화 중에는 64px 아이콘 메뉴를 쓴다. 갤러리의 색상 견본에는 선택한 모드의 실제 값이 표시된다.

## 2026-11-05 실제 화면 점검

라이트 모드에서도 아래 31개 경로를 확인했다. 공개 화면은 일반·큰 글자 각각 4.5:1·3:1을 기준으로 그림 위의 실제 배경 픽셀까지 검사했다. 공정 번호·안내·담당자 역할과 SVG 작업대 표지를 수정한 뒤 데스크톱 21개 상태와 375px 모바일 16개 상태의 배경 표본 7,086개가 통과했다. [공개 화면 대비 검사](../../frontend/tests/ui-style/light-public-contrast.mjs)

작업소에서는 실제 저장 대화의 선택 표식, 답변·근거와 원문 PDF, 문서함, 학습 편집, 흐름도를 확인했다. 원문 보조 문구의 그라디언트 최저 대비는 4.33:1에서 5.40:1로 올랐다. 갤러리에서 기본·선택·비활성 버튼, 입력 안내, 열린 드롭다운과 계정 설정을 확인했다. 관리자의 기존 실행·비교·이전 기록 상세, 모델·구성 탭과 폼에서 측정한 활성 글자의 최저 대비는 4.54:1이었다. 공개 화면의 배경 픽셀 검사와 인증 화면의 계산 색상 검사는 서로 다른 측정이다.

본래 앱의 페이지 파일 31개를 기존 공개 자료와 작업소 계정으로 확인했다. 경로 수는 아래 표의 기본 화면 기준이며, 사용자별 데이터나 모든 오류 상태를 의미하지 않는다.

| 영역 | 확인한 경로와 상태 | 확인 방법 |
|---|---|---|
| 공개 7개 | 로비, 연구실 목록·RAG 소개, 공개 연구 목록·기존 상세, 로그인, 초기화가 끝난 환경의 최초 설정 → 로그인 이동 | 공개 reader를 기존 저장소로 기동한 뒤 서로 다른 6개 기본 화면에서 조작 75개의 hover, 키보드 초점, 크기를 측정했다. 카테고리, 모바일 메뉴, RAG 소개 팝업 7개도 열었다. |
| 작업소 11개 | 지식공간과 문서함, 도메인 선택·대화·파일함과 PDF 원문, 학습 목록·상세, 흐름 목록·상세, 디자인 시스템 | 기존 Chrome에서 저장된 대화와 인용을 따라갔다. 데스크톱과 375px 폭에서 조작 영역과 가로 넘침을 확인했다. |
| 관리자 13개 | RAG 설정·도메인·모델·구성, 비교 목록·상세, 실행 목록·상세·이전 형식 상세, 권한·런타임·문제 이력·발행 관리 | 기존 Chrome에서 실제 요소와 로드된 hover 규칙을 대조했다. 모델 4탭과 구성 3탭을 열었다. 답변 품질 비교의 결과 내부 3탭은 저장된 평가 이력이 없어 실화면 확인이 남았다. |

공개 화면의 기본 상태는 프론트엔드에서 `node tests/ui-style/live-control-audit.mjs`로, 펼친 상태는 `node tests/ui-style/public-control-states.mjs`로 다시 확인할 수 있다. 로그인된 Chrome은 조작 장치를 터치로 보고했다. 공통 버튼·버튼형 링크의 마우스와 터치 동작은 별도의 브라우저 회귀로 비교했다.

버튼 상태 점검(2026-11-05, ISSUE-00040): 공통 Button뿐 아니라 네이티브 버튼에도 기본 hover를 연결했다. 별도 표면을 쓰는 RAG·탐색, 파일함, 공개 연구실·오피스, 로그인, 흐름도, 문제·공개 기록 및 지식공간의 조작은 기능 CSS에서 보완했다. 선택 표식 보존·포인터 이탈·비활성은 브라우저 회귀로 확인한다. 이 범위는 모든 화면을 공통 React 컴포넌트로 이관했거나 모든 권한·데이터 조합을 수동 검수했다는 의미가 아니다.

## 2026-11-04 공통 컴포넌트 찾아보기

비공개 작업소 메뉴의 **디자인 시스템 → 공통 컴포넌트**에서 실제 제품과 같은 구현을 확인한다. 버튼과 선택, 입력과 폼, 상태와 안내, 탐색과 펼침으로 구분한다. 각 카드의 **사용 코드**를 열면 import 경로와 JSX 예시가 표시된다. 컴포넌트는 `@/shared/ui/`에서 가져오고, 데이터 조회·저장과 상태 전이는 사용하는 화면에서 처리한다.

| 필요한 동작 | 구현 위치 | 실제 사용 예 |
|---|---|---|
| 저장·취소·삭제와 비활성 상태 | [Button](../../frontend/src/shared/ui/Button.tsx) | 로그인, 학습 기록 편집 |
| 다른 화면으로 이동하는 버튼형 링크 | [ButtonLink](../../frontend/src/shared/ui/Button.tsx) | 모델 관리·구성 스튜디오에서 간편 설정으로 이동 |
| 관련된 선택지 중 하나 고르기 | [ChoiceGroup](../../frontend/src/shared/ui/ChoiceGroup.tsx) | 모델 설정, 비교 회차 선택 |
| 독립 항목 켜기·끄기 및 복수 선택 | [CheckboxField](../../frontend/src/shared/ui/CheckboxField.tsx) | 학습 작성기 기술 주제·실험 항목·문제 해결·학습 흐름; native checkbox·라벨 클릭·선택/포커스/disabled |
| 한 줄 입력 · 목록 선택 · 여러 줄 입력 | [TextField · SelectField · TextAreaField](../../frontend/src/shared/ui/Fields.tsx) | 공간 만들기, 학습 기록 편집 |
| 항목 상태 · 안내 · 빈 목록 · 상세 펼침 | [StatusBadge · Notice · EmptyState · Disclosure](../../frontend/src/shared/ui/Feedback.tsx) | 문제 이력, 실행 모니터링 |
| 이전·다음 페이지 이동 | [Pagination](../../frontend/src/shared/ui/Pagination.tsx) | PDF 미리보기, 공개 연구 관리 |
| 줄바꿈이 있는 기록 읽기 | [RecordBody](../../frontend/src/features/learning/RecordBody.tsx) | 학습 기록과 미리보기 |
| 영역 이동과 현재 메뉴 표시 | [ApplicationShell](../../frontend/src/features/navigation/ApplicationShell.tsx) | 공개 전시실, 작업소, 관리자 |
| 페이지 오류에서 다시 시도 | [RouteError](../../frontend/src/shared/ui/RouteError.tsx), [ServerRouteFailure](../../frontend/src/shared/ui/ServerRouteFailure.tsx) | 경로 오류 경계, 서버 조회 실패 |

공통 필드는 네이티브 입력 속성과 레이블을 제공한다. 상세 설명은 네이티브 `details`를 사용하는 Disclosure로 표시하며, 안내가 즉시 읽혀야 하는 경우 호출부가 Notice에 `role="alert"`를 지정한다. 역할별 색과 대비 기준은 [스타일 가이드](ui-style-guide.md), 실제 값은 [공통 토큰](../../frontend/src/shared/ui/tokens.css)을 따른다.

## 2026-10-30 인증 카드의 보조 이동 링크

`/login`의 공개 AI Lab 이동 링크(로그인 전·후)에 기능 소유 `secondaryLink` 스타일을 적용했다. 본문용 전역 장식 대신 raised 표면·경계·가운데 정렬·44px 이상·hover/focus를 사용한다. native 링크·URL과 인증 동작은 유지한다. 본래 Chrome desktop·320/375px에서 실제 높이47px·가로 넘침 없음·키보드 이동과 `/labs` 도달을 확인했다. 로그인 후 상태는 실제 인증 제출과 구분해 기존 합성 회귀로 검증한다. [수정·검증 기록](../worklogs/2026-10-30-login-secondary-link.md).

## 기존 적용 범위

- 기준일: 2026-10-29(최초 전수 감사 2026-10-26). 규칙의 정본은 [프론트엔드 스타일 기준](ui-style-guide.md)이다.
- 승인 범위: [디자인](../superpowers/specs/2026-10-26-design-system-adoption-design.md), [실행 계획](../superpowers/plans/2026-10-26-design-system-adoption.md).
- 최초 전수 감사의 기준은 page route 27개, 기능 CSS 27개다. 당시 공용 Button CSS 추가 후 CSS 총수는 32개(기능27·app2·shared3)였으며, 이후 추가 화면은 날짜별 후속 항목으로 구분한다.
- 아래 **적용**은 소스에서 공통 토큰·조작 규격을 연결했다는 뜻이다. 27개 화면 전체의 브라우저 수용 완료를 의미하지 않는다.
- 최초 전수 감사는 표현 변경 범위이며 API·모델 입력·원문 근거·인용·권한·대화 백그라운드 실행 동작은 변경하지 않는다. 이후 새 기능의 계약과 권한 경계는 해당 설계에 따른다.
- 이후 본래 업무 화면의 후속 확인에서 도메인 폼·파일함 링크·문서 선택 포커스·대화 펼침 조작을 보완했다. 아래 후속 표와 [실제 점검 기록](../worklogs/2026-10-26-design-system-followup.md)을 함께 본다.

## 공통 구현 경계

| 경계 | 반영 내용 | 보존·제한 |
|---|---|---|
| [tokens.css](../../frontend/src/shared/ui/tokens.css) | 표면·본문·강조·성공/주의/오류/정보, 글자·간격·반경·그림자·44px·포커스 정본 | 기존 호환 alias 유지; 장면의 모든 색을 청록으로 바꾸지 않음 |
| [app/styles.css](../../frontend/src/app/styles.css) | 업무 `h1` 산세리프·최대2.25rem, 공통 필드/버튼·focus, 도메인·대화·구성·모델·원문·runtime·setup 연결 | 공개 `.hero h1`의 큰 serif 표현은 한정; 원문 표시·하이라이트 좌표 보존 |
| [Button](../../frontend/src/shared/ui/Button.tsx) / [CSS](../../frontend/src/shared/ui/Button.module.css) | primary/secondary/quiet/danger, 기본 type=button, 44px·줄바꿈·focus·disabled | native props/ref/aria 전달; 로그인·지식공간 생성·문제 이력 관리와 저장된 모델 비교에 실제 사용 |
| [ChoiceGroup](../../frontend/src/shared/ui/ChoiceGroup.tsx) / [CSS](../../frontend/src/shared/ui/ChoiceGroup.module.css) | 원형/segmented 단일 선택, 44px label·16px 기호·키보드·상태 표현 | native radio와 fieldset/legend 유지; 실제 콘텐츠 탭과 구분 |
| 탐색 셸·공개 탐색 | 의미별 표면·선택·focus·44px 메뉴 연결 | 기존 sidebar/drawer 전환·container 이름·현재 페이지 의미 보존 |

최초 공용 Button 적용 파일은 [LoginPage](../../frontend/src/features/identity/LoginPage.tsx), [WorkspaceCreateForm](../../frontend/src/features/workspaces/WorkspaceCreateForm.tsx), [IssueManagement](../../frontend/src/features/issue-history/IssueManagement.tsx)다. 이후 저장된 모델 비교의 목록·상세·가져오기에도 적용했다. 나머지 기능의 native 버튼은 공통 CSS 규격을 사용한다.

## 최초 27개 route 적용 매트릭스

`global`은 `app/styles.css`, CSS 이름은 아래 기능 CSS 표에 연결된다. 모든 일반 화면은 공통 탐색 셸의 영향도 받는다. **예외**는 목적에 따른 표현 보존이며 접근성 검사 면제는 아니다.

| 번호 | 화면 / route | 구현 적용·파일 | 별도 수용 또는 예외 |
|---:|---|---|---|
| 1 | 입구 `/` | 예외: Office + office-tailwind, 공통 탐색 셸 | 픽셀 장면·canvas 유지; HUD/메뉴의 개별 수용은 별도 |
| 2 | 공개 Lab 목록 `/labs` | 적용: LabDirectory 팔레트·카드·focus | 공개 카드 밀도·소개 제목 유지 |
| 3 | RAG 공개 소개 `/labs/rag` | 예외: PublicLabScene, 공통 탐색 셸 | 장면·캐릭터·장비 색 유지; 조작 패널의 개별 수용은 별도 |
| 4 | 공개 연구 목록 `/labs/rag/studies` | 적용+읽기 예외: Publishing 색·필터·페이지 이동·focus | 읽기 폭·타이포 보존 |
| 5 | 공개 연구 상세 `/studies/[publicSlug]` | 적용+읽기 예외: Publishing 색·링크·조작부 | 본문 행간·방문한 링크·문서 내부 스크롤 보존 |
| 6 | 로그인 `/login` | 적용: LoginPage + Button | 인증·오류·폼 제출 동작 유지 |
| 7 | 최초 설정 `/setup` | 적용: global auth 제목·필드·focus·버튼 | 최초 설정 API·계정 흐름 유지 |
| 8 | 지식공간 `/workshop/workspaces` | 적용: WorkspacePage + WorkspaceCreateForm + Button | 긴 이름·빈 상태·생성 폼 |
| 9 | 문서함 `/workshop/workspaces/[workspaceId]/documents` | 적용: DocumentLibrary + MoveDialog + WorkspaceMemberPermissions | 폴더 계층·이동·권한 동작, 모달/좁은 폭 별도 확인 |
| 10 | 도메인 선택 `/workshop/rag/search` | 적용: global DomainPicker 제목·카드·탐색 | 현재 route는 DomainPickerPage; 구형 SearchPage와 구분 |
| 11 | 대화 `/workshop/rag/domains/[slug]/chat` | 적용: global conversation + DocumentSelectionPanel | 접수·이탈/복귀·명시 취소 동작 유지; 내용 영역 스크롤 |
| 12 | 도메인 파일함 `/workshop/rag/domains/[slug]/files` | 적용: DomainFileCabinet + DocumentLibrary | 문서 선택·권한·폴더 동작 유지 |
| 13 | 원문 `/workshop/rag/sources/[assetVersionId]` | 적용+원문 예외: global source/search 도구막대·focus | 문서/PDF 좌표와 정확 일치·문맥·의미 하이라이트 구분 |
| 14 | 학습 목록 `/workshop/learning` | 적용: Learning 필터·필드·목록·focus | 저장·필터·페이지 이동 동작 유지 |
| 15 | 학습 상세 `/workshop/learning/[recordId]` | 적용: Learning 상세·선택·상태 | 저장 충돌·preview 정보 구분 |
| 16 | 흐름 목록 `/workshop/flows` | 적용: Flowcharts 색·선택·조작부 | 흐름 구조와 그림 의미 유지 |
| 17 | 흐름 상세 `/workshop/flows/[category]/[flow]` | 적용+그림 예외: Flowcharts | 다이어그램 내부 스크롤·선택·키보드 유지 |
| 18 | 구성·평가 `/admin/rag/configurations` | 적용: global studio + 구성 CSS 5개 + ChoiceGroup | 본래 화면에서 제목36px 산세리프·관측 컨트롤44px 이상·페이지 가로넘침 없음 확인; 전체 상태 수용은 별도 |
| 19 | 모델 `/admin/rag/models` | 적용: global model + ModelAdmin + ChoiceGroup | checkbox/radio와 텍스트 필드 분리; 모델·배포 설정 동작 유지 |
| 20 | 도메인 관리 `/admin/rag/domains` | 적용: global domain-admin 필드·카드·상태 | 권한·평가·활성화 게이트 유지 |
| 21 | 실행 목록 `/admin/rag/executions` | 적용: ExecutionMonitoring 필터·목록·상태 | 성공/실패/진행/취소 의미 구분 |
| 22 | 실행 상세 `/admin/rag/executions/[executionId]` | 적용: ExecutionMonitoring + AgentTracePanel + AgentSpanModal + MermaidAgentDiagram + ExecutionConversationTurns + ExecutionContextObservation | 턴 목록 내부 스크롤·현재 실행·44px 이동 링크·접힌 문맥/미기록 상태; 모달·툴팁·다이어그램 수용 범위는 아래 기록 |
| 23 | 이전 실행 `/admin/rag/executions/legacy/[turnId]` | 적용: 같은 실행 상세 CSS | legacy 데이터·빈 값 의미 보존 |
| 24 | 접근권한 `/admin/system/access` | 적용: AccessManagement 표면·44px·상태·focus | 권한·역할·활성/비활성 동작 유지 |
| 25 | 문제 이력 `/admin/system/issues` | 적용: IssueHistoryPage + IssueManagement Button | 목록·상세·버전·저장 상태 구분 |
| 26 | 런타임 `/admin/system/runtime` | 적용: global runtime 제목·카드·상태·조작 | 관측 데이터·실행 의미 유지 |
| 27 | 발행 관리 `/admin/publishing` | 적용: Publishing 관리 폼·목록·버튼·focus | 공개 읽기 타이포와 관리 조작 규격 분리 |

## 최초 기능 CSS 27개 전수 목록

경로 기준은 `frontend/src/features/`다. 25개 파일은 의미 토큰/공통 조작 규격에 연결했고, Office와 PublicLabScene 두 파일은 장면 예외로 유지했다. 모든 간격·색 literal을 제거했다는 의미는 아니다.

| CSS | 반영 내용 / 예외 |
|---|---|
| [assets/DocumentLibrary.module.css](../../frontend/src/features/assets/DocumentLibrary.module.css) | file alias·표면·상태·폴더 조작·44px·focus |
| [assets/MoveDialog.module.css](../../frontend/src/features/assets/MoveDialog.module.css) | 모달 표면·overlay·컨트롤·focus |
| [flowcharts/Flowcharts.module.css](../../frontend/src/features/flowcharts/Flowcharts.module.css) | 의미 토큰·조작 규격; 그림 배치 보존 |
| [identity/access/AccessManagement.module.css](../../frontend/src/features/identity/access/AccessManagement.module.css) | access alias·상태·44px·입력 유형·focus |
| [identity/LoginPage.module.css](../../frontend/src/features/identity/LoginPage.module.css) | login alias·폼·오류·focus·Button 연계 |
| [issue-history/IssueHistoryPage.module.css](../../frontend/src/features/issue-history/IssueHistoryPage.module.css) | 목록/상세 표면·필터·상태·focus·Button 연계 |
| [learning/Learning.module.css](../../frontend/src/features/learning/Learning.module.css) | 필드·선택 기호·44px·충돌/저장 상태·focus |
| [navigation/ApplicationShell.module.css](../../frontend/src/features/navigation/ApplicationShell.module.css) | 탐색 palette·선택 표면·44px·focus; 기존 container 유지 |
| [office-game/Office.module.css](../../frontend/src/features/office-game/Office.module.css) | 예외: 픽셀 장면·canvas·HUD의 기능 소유 표현 유지 |
| [public-labs/LabDirectory.module.css](../../frontend/src/features/public-labs/LabDirectory.module.css) | directory alias·카드 표면·반경·focus |
| [public-labs/PublicLabScene.module.css](../../frontend/src/features/public-labs/PublicLabScene.module.css) | 예외: 장면·캐릭터·장비·canvas 유지 |
| [publishing/Publishing.module.css](../../frontend/src/features/publishing/Publishing.module.css) | study 색 alias·관리/공개 조작 규격; 읽기 타이포 유지 |
| [rag/configurations/CodexVerificationPanel.module.css](../../frontend/src/features/rag/configurations/CodexVerificationPanel.module.css) | 보존된 이력 패널의 버튼·선택·focus; 지원종료 모델 활성화 없음 |
| [rag/configurations/ConfigurationStudioComparison.module.css](../../frontend/src/features/rag/configurations/ConfigurationStudioComparison.module.css) | 제목·후보 선택 표면·컨트롤 글자·focus |
| [rag/configurations/EvaluationAuthoring.module.css](../../frontend/src/features/rag/configurations/EvaluationAuthoring.module.css) | 텍스트 입력에서 radio/checkbox 제외·44px·label |
| [rag/configurations/EvaluationExecutionDiagnostics.module.css](../../frontend/src/features/rag/configurations/EvaluationExecutionDiagnostics.module.css) | 진단 메타데이터·링크 조작·focus |
| [rag/configurations/GenerativeEvaluation.module.css](../../frontend/src/features/rag/configurations/GenerativeEvaluation.module.css) | 필드·탭·summary·선택·상태·줄바꿈 |
| [rag/conversation/DocumentSelectionPanel.module.css](../../frontend/src/features/rag/conversation/DocumentSelectionPanel.module.css) | 모달 표면·overlay·제목·닫기44px·focus |
| [rag/domains/DomainFileCabinet.module.css](../../frontend/src/features/rag/domains/DomainFileCabinet.module.css) | file alias·탐색·선택·44px·줄바꿈·focus |
| [rag/executions/AgentSpanModal.module.css](../../frontend/src/features/rag/executions/AgentSpanModal.module.css) | 모달·성공/정보/주의/오류 상태·읽기 계층 |
| [rag/executions/AgentTracePanel.module.css](../../frontend/src/features/rag/executions/AgentTracePanel.module.css) | 의미별 실행 상태·표면·메타데이터; 관계 선 보존 |
| [rag/executions/ExecutionMonitoring.module.css](../../frontend/src/features/rag/executions/ExecutionMonitoring.module.css) | monitor alias·제목·필터·링크44px·상태 |
| [rag/executions/MermaidAgentDiagram.module.css](../../frontend/src/features/rag/executions/MermaidAgentDiagram.module.css) | 성공/실패/주의·summary44px; SVG 선택/선 패턴 보존 |
| [rag/models/ModelAdmin.module.css](../../frontend/src/features/rag/models/ModelAdmin.module.css) | 입력 유형·탭·버튼/summary44px·선택·focus |
| [workspaces/WorkspaceCreateForm.module.css](../../frontend/src/features/workspaces/WorkspaceCreateForm.module.css) | 필드·44px·focus·Button 연계 |
| [workspaces/WorkspaceMemberPermissions.module.css](../../frontend/src/features/workspaces/WorkspaceMemberPermissions.module.css) | 권한 행·native 선택 기호·컨트롤·focus |
| [workspaces/WorkspacePage.module.css](../../frontend/src/features/workspaces/WorkspacePage.module.css) | file alias·패널·목록·선택·44px·focus |

## 2026-10-26 후속 실제 화면 확인

본래 계정·기존 자료를 사용하는1920px Chrome에서 확인했다. 다음은 전체 상태 E2E가 아닌 명시한 관측 범위다. 전체 모바일 수용은 여전히 별도다.

| 화면 묶음 | 후속 확인·수정 | 남은 경계 |
|---|---|---|
| 학습·흐름 | 학습 필터/빈 상태/작성 닫기, 전체 흐름→기술 상세 | 자료 없는 학습 상세·모든 흐름 조합 |
| 모델·도메인 | 모델5탭과 비활성 게이트, 도메인 폼 위쪽 정렬·checkbox16px/label44px | 등록/실행/승인/활성화 없음 |
| 권한·런타임·발행 관리 | 마지막 마스터 보호·상속 권한, 관측/미관측 구분, 기존 공개 편집 폼 | 계정/권한/발행 저장 없음 |
| 지식 공간·문서함 | 공간 검색0결과와 복원, 원본 보기·이동창 Escape/복귀, 작업 링크5개44px 보완 | 실제 파일 이동·업로드·다운로드 없음 |
| 대화·문서 선택·원문 | 저장 답변/인용·PDF 문맥 강조, 모달 Tab순환/Escape/복귀, 대화 펼침·실행 링크44px 보완 | 숨긴 탐색기5조건은 단위 회귀, 실모델 새 질문 없음 |
| 실행 목록·상세 | 목록/다음 페이지, 완료 실행·단계 모달/Escape/복귀 | 목록 초기 지연의 서버 비용은 별도 성능 항목 |
| 공개 연구 | 별도 reader 연결 복구 후15개 목록·카테고리 검색0결과/Escape·공개 상세 | 게시본 변경 없음, 부팅 시 자동 시작 구성 없음 |
| 문제 이력 | ISSUE-00040 후속 수정·검증·제한 저장 | 운영 기록과 저장소 worklog 구분 |

기능 고유119개·대비2개, 전체 TypeScript·변경 TSX lint·CSS 파싱과 독립 리뷰를 통과했다. 이전 적용 검증과 중복 합산하지 않는다. 본래 앱 iframe의 좁은 화면 시도는 문서가 로드되지 않아 통과로 집계하지 않았다.

## 2026-10-27 문맥 관측 화면 보강

같은 대화의 턴 목록과 최종 채택/제외 메시지·문맥화 기록 패널에 기존 다크·청록 의미 토큰·줄바꿈·초점을 적용했다. 실행 목록/기존 대화 링크의 약23.33px 높이를44px로 보완했다. 본래 인증 화면에서 기존 저장 실행·현재 턴·미기록/생략 안내와 실행↔대화 왕복을 확인했다.

실제 컴포넌트/CSS 합성320/375/1000px의 관측 컨트롤33개는44px 이상이고 가로 넘침이 없었다. 긴 턴 목록352px 내부 스크롤, Tab의2px 청록 초점과 자동 스크롤, Enter의7번→8번 실행 이동/이전 질문 제거, 문맥 패널/HTTP 입력/JSON 결과 펼침을 확인했다. 본래 탭 viewport 설정은 측정 폭1920px가 유지돼 실제 모바일 통과로 집계하지 않았고 설정을 복구했다. 실기기·전체 업무 E2E·새 모델 연속 질문은 미검증이다. [구현·검증·제한](../worklogs/2026-10-27-sdk-context-monitoring.md).

## 2026-10-29 저장된 모델 비교 화면

[ADR-0051](../decisions/0051-stored-model-comparisons.md)에 따라 완료된 비교 관측을 비공개 보고서로 조회한다. 왼쪽 `RAG 관리 → 모델 비교 결과`, 평가 화면의 `비교 → 저장된 모델 비교`와 실행 목록의 별도 진입점이 같은 보고서를 연다. 기존 실행 건수·통계·평가 품질 게이트에 합산하지 않으며, 새 모델 실행이나 기본 프로파일 승격을 수행하지 않는다.

| 화면 / 경계 | 구현 적용·파일 | 수용 기준·제한 |
|---|---|---|
| 비교 목록 `/admin/rag/comparisons` | [ComparisonListPage](../../frontend/src/features/rag/comparisons/ComparisonListPage.tsx), [ComparisonListPanel](../../frontend/src/features/rag/comparisons/ComparisonListPanel.tsx) | 제목·질문·모델·요청 수·예상 비용·청구 확인 상태; 로딩·빈 상태·권한/연결 오류 구분 |
| 비교 상세 `/admin/rag/comparisons/[comparisonId]` | [ComparisonDetailPage](../../frontend/src/features/rag/comparisons/ComparisonDetailPage.tsx), [ComparisonReportView](../../frontend/src/features/rag/comparisons/ComparisonReportView.tsx) | 대상별 시간·사용량·비용 비교 구역, 실제 답변·인용·의미 검토·형식 검사·분석·한계를 구분; 배치 후속은 아래 기록 |
| 기존 화면 진입점 | [ConfigurationStudioPage](../../frontend/src/features/rag/configurations/ConfigurationStudioPage.tsx), [ExecutionListPage](../../frontend/src/features/rag/executions/ExecutionListPage.tsx) | 평가의 `?tab=comparison&view=stored` 선택 복원; 실행 목록은 별도 링크로 연결하고 기존 조회·통계 유지 |
| 관리자 결과 파일 가져오기 | [ComparisonImportForm](../../frontend/src/features/rag/comparisons/ComparisonImportForm.tsx) | native JSON 파일 선택·제목/모델/요청 수 확인 후 명시 저장; 2MiB 상한·오류 시 선택 내용 제거·중복 제출 방지 |
| 표현·조작 | [Comparisons.module.css](../../frontend/src/features/rag/comparisons/Comparisons.module.css), 공용 Button·ChoiceGroup | 다크·청록 의미 토큰·44px 조작 영역·가시적 초점·긴 본문 줄바꿈; 회차 선택은 native radio 키보드 동작 유지 |

완료 시간과 첫 토큰 시간은 서로 다른 항목이다. 미측정 시간은 `미측정`, 수집되지 않은 토큰은 `미보고`, 청구 대조가 없는 비용은 `미확인`으로 표시한다. 예상 비용은 작은 USD 소수도 보존하고, 로컬 모델의 `API 청구 해당 없음`을 운영 비용 0으로 표현하지 않는다. 형식·인용 검사 통과, 질문에 대한 의미 검토, 기준선과의 동일 여부도 각각 표시한다. 원문 이동은 기존 뷰어와 정확한 근거 위치를 재사용하며 현재 권한을 적용한다.

최초 연결 시 단위 회귀·전체 TypeScript·변경 파일 lint를 통과했다. 당시 공개 동결 자료와 실제 컴포넌트/CSS를 렌더한 합성 320/375/1280px 화면에서 페이지 가로 넘침 없음, 회차 label 44px·펼침 summary 50.4px, 4개 요청의 완료 시간 카드 노출과 ArrowRight 회차 전환을 확인했다. 375px에서는 인용 펼침과 정확한 버전·Projection·2페이지·bbox를 담은 원문 링크도 확인했다. 후속으로 본래 계정의 실제 JSON 저장·중복 재수입1건·회차 전환·평가/실행 양쪽 진입·PDF2페이지 문맥 강조/복귀·전체 새로고침을 확인했다. 이 최초 배치의 검증을 아래 변경 배치의 검증으로 대신하지 않는다. 실제 데스크톱 수용과 합성 반응형 폭 검증을 구분하며 실기기 모바일 전체 수용으로 확대하지 않는다. 개발빌드 모듈 오류와 재기동 후 실제화면 복구 범위는 [작업 기록](../worklogs/2026-10-29-stored-model-comparisons.md) 및 [WORKBOARD](../../WORKBOARD.md)를 확인한다.

## 2026-10-29 비교 대상별 구역 정리

사용자는 비교 자료를 빠르게 인지할 수 있도록 나눠 달라고 요청했고, 후속으로 **API 모델은 왼쪽, 로컬 모델은 오른쪽**에 모아야 한다고 명확히 했다. 앞선 첫 요청/반복별 구역은 담당자가 요청을 잘못 해석한 결과로, 한 구역에 두 모델을 다시 섞어 사용자가 원하는 대상별 구분을 충족하지 못했다.

[비교 결과 배치 기준](ui-style-guide.md#비교-결과의-정보-배치)을 대상 → 조건 → 지표로 바로잡고 [ComparisonMetricGroups](../../frontend/src/features/rag/comparisons/ComparisonMetricGroups.tsx)와 [Comparisons.module.css](../../frontend/src/features/rag/comparisons/Comparisons.module.css)를 대상별 구역으로 수정했다. 현재 보고서는 왼쪽 OpenAI API, 오른쪽 Ollama 로컬 모델이며, 각 구역 안에서 첫 요청/동일 입력 반복을 열로, 같은 지표를 행으로 맞춘다. 대상 순서는 기록의 최초 등장 순서를 사용하고 모든 시간·사용량·비용 및 답변 구역에서 유지한다. 답변 카드도 공급자·모델의 같은 식별 기준으로 정렬해 반복 실행의 원래 순서가 달라도 좌우가 뒤바뀌지 않게 했다. 구역 제목에 공급자·모델, 열 제목에 조건·요청 번호를 표시하고 미관측 조합의 값을 만들지 않는다.

넓은 화면은 두 대상 구역을 나란히, 좁은 화면은 API 위·로컬 아래로 쌓는다. 완료 응답 첫 행 강조, native 표 제목·행/열 머리글, 기존 토큰·미관측 상태 표시와 실제 답변·인용·품질 판정을 유지한다. 본래 로그인 화면에서 시간·사용량·비용 모두 API가 왼쪽, 로컬이 오른쪽에 같은 높이로 정렬됨을 확인했다. API 시간표에는3.781/3.347초, 로컬 시간표에는159.723/11.123초가 표시되고 비용·사용량의 모든 행도 원본 값과 일치했다.

대상별 수정본의 실제 컴포넌트/CSS와 공개 동결 자료를 사용하는 합성 iframe320/375/1280px에서 페이지 client/scroll 폭은 각각305/305,360/360,1265/1265px로 같고 각 표 내부에도 가로 넘침이 없었다.1280px에서는 API·로컬 구역이 시간과 사용량·비용 모두 같은 높이에 나란히 배치됐고,320/375px에서는 API 위·로컬 아래 순서를 유지했다. 새 증거는 `.local-data/project-agent-work/comparison-lanes-20261029/responsive-verification.json` 및 `comparison-lanes-live.png`에 보존한다. 최종 수정본의 독립 검증은8파일31개 테스트(독립6개 포함), 전체 TypeScript·변경 ESLint·diff 검사를 통과했으며 같은 폴더의 `independent-review.json`에 기록했다.

이전 조건별 배치는 비교8파일30개 테스트·TypeScript·ESLint, 본래 화면과 합성320/375/1280px 검사를 통과했지만 사용자 의도를 충족한 검증이 아니다. 당시 증거는 `.local-data/project-agent-work/comparison-groups-20261029/responsive-verification.json` 및 `comparison-groups-live.png`에 보존했으며 대상별 수정본의 수용 근거로 재사용하지 않는다. 합성 반응형 검사를 실제 모바일 장치 확인으로 확대하지 않는다.

## 2026-10-29 전역 밑줄 스타일 정리

사용자는 상단 링크 외에도 비교 회차 선택에 밑줄이 남아 있다고 지적하며 전역 조사를 요청했다. 앞선 수정은 비교 목록·상세의 상단 탐색에만 한정돼 공통 ChoiceGroup·모델 탭·평가 탭과 다른 UI 링크를 다루지 못했다. 이번 정본은 상단뿐 아니라 일반 UI 링크·선택 컨트롤에 적용하며, 밑줄을 제거할 때 표면·경계·체크 또는 도형 표식을 함께 제공한다. [링크 기준](ui-style-guide.md#화면-이동-링크)과 [선택·탭 기준](ui-style-guide.md#choicegroup탭포커스)을 따른다.

원문 검색의 정확 일치·문맥·의미 하이라이트는 각각의 근거 종류를 전달하므로 기존 실선·점선을 보존한다. 일반 UI의 명시적인 `underline`은 제거했고, 키워드 `mark`의 기능적 밑줄 한 곳은 유지했다. 카드·메뉴 전체 링크, 본문 인라인 링크, 선택 컨트롤과 원문 강조를 구분하며, 전역 조사 결과를 모든 화면의 모든 상태 브라우저 수용으로 확대하지 않는다.

| 적용 경계 | 변경 내용 |
|---|---|
| [links.css](../../frontend/src/shared/ui/links.css), [앱 스타일](../../frontend/src/app/styles.css) | 전역 링크 밑줄 제거, 일반 인라인 링크의 은은한 표면·경계와 독립 링크의 조작 영역, 공통 focus |
| [ChoiceGroup](../../frontend/src/shared/ui/ChoiceGroup.module.css), [모델 탭](../../frontend/src/features/rag/models/ModelAdmin.module.css) | 글자 밑줄 대신 선택 배경·굵기·체크 도형, native radio/tab 상태와 키보드 유지 |
| [평가 상위 탭](../../frontend/src/features/rag/configurations/ConfigurationStudioComparison.module.css), [평가 상세 탭](../../frontend/src/features/rag/configurations/GenerativeEvaluation.module.css) | 아래쪽 선택선 대신 둥근 표면·경계·체크 도형 |
| [도메인 파일함](../../frontend/src/features/rag/domains/DomainFileCabinet.module.css), [에이전트 관측](../../frontend/src/features/rag/executions/AgentTracePanel.module.css), [실행 관측](../../frontend/src/features/rag/executions/ExecutionMonitoring.module.css) | 선택·현재 상태의 밑줄을 표면·경계로 교체하고 세부 이동 링크 정돈 |
| [저장 비교](../../frontend/src/features/rag/comparisons/Comparisons.module.css) | 상단뿐 아니라 원문·저장 결과 등의 탐색 링크에도 일관된 표면 적용 |
| 기존 사이드바·흐름·페이지 탐색 | 컨테이너가 이미 표현하는 링크에는 인라인 장식을 중복 적용하지 않도록 표면 reset |

본래 인증 화면에서 비교 회차의 방향키 첫 요청→반복 전환, 체크의 선택/비선택 표시, 밑줄 없음·44px 높이·키보드 초점을 확인했다.320/375px Chrome viewport에서 document client/scroll은305/305·360/360px, 밑줄이 남은 조작 요소는0개였다. 모델5개 탭은46.39px 높이와 방향키·체크를 유지하고, 비선택 사이드바는 투명 배경·추가 그림자 없음으로 확인했다. 평가 상위3개/내부3개 탭은44px·반경10px·체크·선택 아래선 없음이며, 근거 진단 이동 후 기존 저장 답변과 인용2개·실행 상세 이동 링크의 표면도 확인했다. 실행 상세의 기존 답변·인용·단계와 밑줄 조작 요소0개·페이지 넘침 없음, 학습 화면의 빈 상태도 확인했다. 본래 화면 수용은 비교·모델·평가·실행·학습5종의 관측 범위이며 실기기 모바일 또는 전체 업무 상태 수용은 아니다.

독립 전체34개 CSS 파싱과 적용 범위 리뷰를 통과했다. 선택 컨트롤 관련64개와 실행·비교·탐색·문제 이력·학습·공개의 확장 회귀53파일395개를 별도 범위로 검증했으며, 전체 TypeScript·검증 하네스의 node 문법 검사·ESLint·ChoiceGroup TSX lint도 통과했다. 공개 연구 목록은 기존 `공개 연구 서비스를 불러올 수 없습니다` 상태여서 실제 콘텐츠 수용은 미확인이고, 공개 회귀 결과는 mock·코드 검증으로 구분한다. 해당 서비스를 새로 기동하거나 공개 데이터를 변경하지 않았다. 제품 TSX·모델 설정·비교 데이터 변경이나 새 모델 호출은 없다. 실제 화면 증거는 `.local-data/project-agent-work/global-link-style-20261029/selection-live.png`에 보존한다.

## 2026-10-31 Claude와 고급 관리 화면

[고급 관리 작업 선택 기준](ui-style-guide.md#고급-관리의-작업-선택)에 따라 기존 두 고급 메뉴의 URL과 저장 기능을 유지하면서 필요한 작업만 먼저 표시한다. 일반 연결/변경은 상단 통합 설정으로 안내하고 세부 업무의 접근을 제거하지 않는다.

| 화면 | 적용 |
| --- | --- |
| 모델 연결·RAG 설정 | Claude 공급자·공개일 최신순 모델 선택, 빈 초기값·ID/출처·계정 접근과 품질 수용 구분. 공급자 변경 시 오래된 선택/동의 제거, 별도 보관 조건과 참조 미설정 안내 |
| RAG 모델·고급 | 등록 현황/모델 연결/처리 설정/데이터 정책 4개 탭, 목적별 안내 카드, 등록/배포/프로파일의 작업 선택과 상세 접기. ModelAdminWorkspace/Tabs와 ModelAdmin.module.css |
| RAG 구성·고급 | 저장 구성 확인/새 구성 만들기 분리, 이름·버전·모델·준비 상태 우선, 내부 ID/파이프라인 상세 접기. ConfigurationStudioPage/Builder/SavedConfigurationList와 ConfigurationAdmin.module.css |

공용 ChoiceGroup·Button과 기존 의미 토큰, 44px 조작·2px 초점을 사용한다. 초안은 작업/탭 이동 후 보존하며 탐색은 저장·모델 호출·적용을 유발하지 않는다. 탭은 방향키/Home/End와 안내 카드에서의 초점 이동을 제공한다.

본래 로그인 Chrome에서 구성·모델 초안 왕복 보존과 지우기, 실제 Claude 목록/미설정 등록 차단을 확인했다. 320/375px viewport에서 관측 범위 가로 넘침0, 구성 입력45.39px·모델 탭46.39px와 방향키/2px 초점을 확인하고 viewport를 복원했다. 독립 프론트 통합139개·구조/후보52개, 전체 TypeScript·변경 ESLint를 통과했다(중복 합산 안 함). 실제 모바일 기기·모든 업무 상태·Claude 실모델 답변 품질 수용은 별도다. 기존 DB·설정 보존과 API 반영은 [작업 기록](../worklogs/2026-10-31-claude-admin-workflows.md)에 있다.

## 의도된 예외와 남은 수용 경계

### 2026-10-29 비교 화면 상단 탐색

이 항목은 전역 개선 전의 제한된 수정 이력이다. 당시 사용자 피드백에 따라 비교 목록·상세의 상시 밑줄 이동 링크를 옅은 표면·둥근 경계의 링크로 정돈했다. [Comparisons.module.css](../../frontend/src/features/rag/comparisons/Comparisons.module.css)의 `.page nav .navigationLink`에 한정하고 같은 class를 쓰는 목록 제목·저장 성공·원문 인용 링크의 밑줄을 남겼다. 이후 사용자의 전역 수정 요청으로 이 제한을 해제했으며 현재 기준과 수용 범위는 위 전역 정리 항목을 따른다. native anchor/URL과 기능은 보존한다.

본래 인증 화면에서 상세 3개·목록 2개 링크의 밑줄 없음·높이 44px, 상세→목록→상세 복귀, Tab 초점 2px outline, 목록 제목의 기존 밑줄을 확인했다. Chrome viewport 320/375px에서 상세의 document client/scroll 폭은 각각305/305·360/360px이며, 링크 높이44px와 줄바꿈을 유지했다. viewport를 복원했고 실기기 검증으로 확대하지 않는다. 기존 비교 회귀31개, 전체 TypeScript와 비교 ESLint, 독립 CSS 범위 검토를 수행했다. 사진은 `.local-data/project-agent-work/comparison-navigation-style-20261029/navigation-live.png`, 상세는 [작업 기록](../worklogs/2026-10-29-stored-model-comparisons.md#후속-상단-탐색-링크-스타일)이다.

2026-10-26 모바일 후속: 실제 컴포넌트/CSS의 합성 iframe에서 실행 목록320/375px·추가필터/로딩/오류/빈 상태, 모델5탭/도메인320px, 문서선택과 단계 흐름/상세320×640·375×812px를 확인했다. 검사한 화면 가로 넘침 없음·조작요소44px 이상, 메뉴/모달의 키보드 순환·Escape·초점 복귀와 합성 문서 선택 적용을 확인했다. 추가 UI 결함은 재현되지 않아 제품 UI 수정은 없다. 인증된 실기기 모바일·전체27route 수용과 구분한다. [실제 범위와 한계](../worklogs/2026-10-26-execution-list-mobile.md).

- 게임 `/`와 공개 RAG 장면 `/labs/rag`: 픽셀 색·캐릭터·장비·canvas 배치는 유지한다. 게임 밖 공통 탐색 셸 적용을 장면 내부 전체 적용으로 보고하지 않는다. HUD·메뉴·dialog의 키보드와 조작 영역은 해당 화면 변경 시 별도 확인한다.
- Publishing 공개 읽기: `--study-*` 읽기 폭50rem·본문1.0625rem·행간1.85와 방문한 링크 의미를 보존한다. 관리 입력·버튼까지 읽기 타이포의 예외로 취급하지 않는다.
- 원문·PDF: 종이 배경·위치 좌표·정확 일치/문맥/의미 하이라이트와 선 패턴을 보존한다. 원문 내부 가로 스크롤과 페이지 전체 넘침을 구분한다.
- 흐름도·Mermaid: 노드 종류·점선·선택/포커스의 SVG 선과 내용 영역 스크롤을 유지한다. native outline을 대체하는 표시도 키보드에서 확인해야 한다.
- 공개 소개 제목·hero와 일부 좁은 대화 헤더는 일반 업무 제목과 다른 크기를 유지한다. 전역 `h1`을 통해 관리 화면에 큰 serif 제목을 퍼뜨리지 않는다.
- loading·오류·권한 거부·빈 결과·긴 식별자·모달/툴팁 포커스 잘림과 모든 반응형 조합은 소스 적용만으로 수용 완료가 되지 않는다.

## 확인된 검증과 보고 규칙

| 범위 | 현재 확인 사실 | 이 결과가 보장하지 않는 것 |
|---|---|---|
| 최초 정적 inventory | route27개·기능 CSS27개, 공통 값/컴포넌트와 예외 연결; 추가 화면은 날짜별 후속 항목 참조 | 현재 전체 route/CSS 수 또는 실제 화면의 색 대비·클릭 영역·넘침 합격 |
| RAG CSS 회귀 | CSS12개 파싱·변수 참조 확인, 관련 기존 Vitest12파일136개 통과 | 브라우저 layout·모든 화면의 E2E |
| 본래 구성 화면 읽기 전용 확인 | 제목36px 산세리프, 관측한 컨트롤44px 이상, 페이지 가로넘침 없음 | 구성 화면의 모든 탭·모달·상태 또는 나머지26개 route 수용 |
| 공통 합성 화면 | 320px·375px에서 검사 대상 컨트롤44px, 페이지 가로넘침 없음 | 인증된 실제 업무 흐름·모든 기능별 좁은 컨테이너 |

최종 브라우저 수용·대비·독립 회귀·본래 적용 확인은 [2026-10-26 작업 기록](../worklogs/2026-10-26-design-system-adoption.md)에 있다. 대표 화면 확인을 전체 화면·모든 상태 합격으로 확대하지 않는다. 새 route/CSS를 추가하거나 의도된 예외를 바꿀 때 이 목록과 [새 화면 체크리스트](ui-style-guide.md#새-화면-체크리스트)를 함께 갱신한다.
