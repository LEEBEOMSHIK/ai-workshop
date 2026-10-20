# 평가 준비 모드 연결형 선택 버튼

- 날짜: 2026-10-19
- 범위: 사용자 요청에 따라 평가 준비의 저장 자료 재사용/새 자료 작성을 연결된 segmented 버튼으로 전환했다. 일반 ChoiceGroup은 기본 원형 radio를 유지한다.
- 작업 등급·위험: 한정 UI 변경, 중간 접근성/회귀 위험. frontend 구현과 main 통합·합성 브라우저 검증, 독립 리뷰를 분리했다. backend/DB/모델/보안 역할은 영향이 없어 제외했다.
- 기준선: 기존1,993개 파일 해시와 최초 Git 상태를 보존했다. 기존8파일 수정·신규 기록1개이며 승인 범위 밖 변경·삭제는 없다.
- 우선순위: 기존 RAG P0 안정화 및 운영 마감 순서를 유지한다. 이 UI 작업을 실모델 품질·전체 기능 마감 완료로 확대하지 않는다.

## 구현

- `frontend/src/shared/ui/ChoiceGroup.tsx`/`.module.css`: 선택적 `variant="segmented"`를 추가했다. native fieldset/legend/radio 의미와 controlled value를 유지한다. 원형만1px·clip-path로 숨기고 같은 행에 간격 없는 label과 외곽선·내부 구분선을 제공한다.
- 선택은 기존 청록 토큰·굵기·밑줄, hover는 활성 항목에만 배경 변화, 키보드 focus-visible은 label 전체2px 외곽선으로 표현한다. 최소44px 클릭 영역과 disabled 상태를 유지한다. 한글 어절은 우선 보존하고 무공백 장문은 넘치지 않도록 나눈다.
- `GenerativeEvaluationPanel.tsx`: 평가 준비 선택에만 variant를 지정했다. 모드 상태·초안·API·공통 토큰은 변경하지 않았다. switch나 tab 역할로 바꾸지 않았다.
- `ChoiceGroup.test.tsx`: 기본/segmented 의미·controlled 상태·텍스트 클릭·키보드·그룹 격리·disabled 및 opt-in 표현을 검사한다.
- `frontend/tests/ui-style/preparation-browser.mjs`/`preparation.fixture.tsx`: 실제 앱 CSS와 제품 컴포넌트를 렌더링한다. 기본 원형·좁은 장문·비활성 그룹을 함께 검사하고, 두 모드의 자료 작성/제출은 API를 합성 응답으로 가로채 검증한다. 외부/예상 밖 요청은 차단하며 실제 backend에 도달하지 않는다.
- [스타일 정본](../guidelines/ui-style-guide.md)에 variant 선택 기준, 접근성·상태·줄바꿈과 합성 검증 명령/출력 위치를 기록했다.

## 실행한 검증

| 검증 | 실제 결과 |
|---|---|
| 브라우저 RED | 기존1280·375·320px 원형16px와 모바일 분리 행을 확인, hidden glyph assertion 실패 |
| 단위 RED → GREEN | 표현 opt-in 부재로12통과/1실패 → 공유13개 및 준비 모드9개,22/22 통과 |
| 관련 회귀 | `node node_modules/vitest/vitest.mjs run src/features/rag/configurations src/shared/ui/ChoiceGroup.test.tsx --reporter=dot`: 16파일156개,145.66초,exit0 |
| 독립 검증 | 별도 담당 ChoiceGroup13개,8.50초,exit0; 제품·하네스 코드 차단 결함 없음 |
| 타입 | 전체 `tsc --noEmit --pretty false --incremental false` 통과 |
| 린트 | 제품 TSX 범위·최종 브라우저 하네스/fixture ESLint `--max-warnings 0` 통과 |
| 실제 CSS 최종 | 설치된 Edge1280·375·320px, 실제 CSS·키보드·포커스·상태·기본 variant·240px 장문·입력 보존·모드별 제출 통과, 오류/외부요청0 |
| 현재5173 제공본 | 최종 JS/CSS/소스맵8개 HTTP200·생성 파일 바이트 일치, 핵심 TSX/CSS4개 소스 일치, 기존 토큰26개 확인 |
| 보존 | 기준1,993파일에서 범위 밖 변경/삭제0, 변경 파일 `git diff --check` 통과 |

브라우저 최종 측정: 세 폭 모두 숨긴 radio1×1px, 연결된 두 버튼은 같은 행이며 가로 넘침0이다. 1280/375px label 높이는44px,320px는 긴 문구 줄바꿈으로68.78px다. 전체 그룹 높이는135.81/158.23/205.44px다. 일반 variant의 원형16px와 native 방향키 선택은 그대로다.

Tab 진입·방향키·Space·전체 라벨 클릭·disabled 건너뛰기·그룹 격리, 선택 밑줄과 hover/disabled 차이를 확인했다. 모드 왕복 후 초안·규칙·문맥이 보존되고 저장/작성 각각 해당 스냅샷·규칙·문맥만 제출했다. 세 폭에서 가로채 처리한 합성 평가 제출은6회이며 실제 평가 제출은0회다. 합성 모바일/포커스/장문 캡처를 직접 확인했다.

검사 개발 중 label의 밑줄을 span에서 읽은 측정 오류, textarea와 legend 중복 텍스트 선택, 재렌더 뒤 질문 label의 정확 문자열 탐색을 각각 label 스타일·legend·접근성 이름 기반 textbox로 수정했다. 제품 결함 RED와 하네스 교정을 구분한다. 마지막 어절 줄바꿈 변경은 CSS 전용으로, 기능 회귀 후 실제 CSS와 현재 제공본을 다시 확인했다.

증거는 `.local-data/project-agent-work/segmented-preparation-20261019/`의 `baseline-hashes.json`, `status-before.txt`, `preservation-report.json`, `frontend-verification.json`, `related-tests.txt`, `browser/before-report.json`, `browser/after-report.json`, 합성 PNG와 `served-styles-verification.json`에 보존했다. 기본 출력은 `.local-data/browser-verification/preparation/`이며 이번 실행은 `UI_STYLE_OUTPUT_DIR`로 증거를 분리했다.

## 남은 한계와 다음 후보

- 실제 사용자 브라우저·로그인 업무 E2E·실제 평가 제출·화면 읽기 프로그램·모든 브라우저는 미검증이다. 5173 업무 경로는 정상 로그인 이동을 확인했고 공개 자산만 비교했다. 인증된 화면을 봤다고 주장하지 않는다.
- 전체 frontend 회귀는 이번에 실행하지 않았다. 이전 작업의 전체1,064개 통과를 이번 결과로 재사용하지 않는다.
- 기존 baseline 열거에서 접근이 거부되는 `backend/.test-tmp-original-independent-coordinator-20260920a/`는 건드리지 않았다. 위1,993개 해시 보존은 열거 가능한 기존 파일 범위다.
- 문제 이력 DB는 이번 DB 변경 금지 범위에 따라 갱신하지 않았다. 이번 UI 요청·실행 증거는 이 기록에 보존한다.
- 본래 서버 재시작·DB/ES/Docker 상태·backend/모델 설정·패키지 설치·모델 호출·commit/push·학습 문서/진도·알림 예약 변경은 하지 않았다.
- 다음 후보는 기존 RAG P0의 본래 로그인 화면 입력/취소/재제출 검증이다. 실제 제출/모델 실행은 이 작업의 mock 검증만으로 승인 또는 완료로 간주하지 않는다. 스타일 확대는 해당 화면을 수정할 때 정본에 따라 단계적으로 적용한다.
