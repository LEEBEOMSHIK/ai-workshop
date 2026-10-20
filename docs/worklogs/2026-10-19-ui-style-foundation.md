# 프로젝트 스타일 기준과 평가 준비 선택 UI

- 날짜: 2026-10-19
- 상태: 승인 범위 구현·관련 회귀·실제 CSS 합성 브라우저·독립 리뷰·현재 제공본 확인 완료.
- 승인: 기존 프로젝트 느낌에 맞는 스타일 기준 정의, 공통 코드 연결, 평가 준비 radio/label 충돌 우선 수정.
- 범위: frontend 공통 토큰·선택 그룹·평가 준비 통합, 스타일 정본·진입 링크, 실제 CSS 합성 브라우저 및 관련 회귀·독립 리뷰·현재 제공본 확인.
- 제외: 전체 화면 일괄 변경, 설치, 사용자 인증 화면 캡처·인증 우회, DB/backend/모델 설정, 실제 제출·모델 호출, commit/push.
- 원인: `.page label`의 grid와 checkbox만 제외한 텍스트 input 스타일이 새 radio에도 적용됐다. 이전 기능 테스트와 제공본 비교는 실제 배치를 검증하지 않았다.
- 브라우저 RED: 설치된 Edge·Playwright로 실제 제품 컴포넌트와 CSS를 합성 렌더링했다. 1280px에서 input 1140×44px, label 81.39px/grid/다른 줄, 그룹 높이278.17px. 375/320px에서 그룹326.14px. 작은 glyph·같은 행 assertion 실패(exit1). 모든 API는 합성 응답이며 실제 로그인·모델 호출0.
- 역할: 메인 요구·기준 문서·통합/브라우저 검증, frontend 담당 구현·단위 테스트, 별도 담당 독립 리뷰. DB/backend/AI/보안 계약 변경 없음.
- 보존: 시작 시1,984파일 SHA-256과 기존 대상 파일 원본을 `.local-data/project-agent-work/ui-style-foundation-20261019/`에 보존했다.
- 문제 이력 DB: 이번 DB 변경 금지 범위에 따라 갱신하지 않았다. 사용자 보고 결함과 재현·수정·검증 근거는 이 기록에 보존한다.

## 구현과 적용 범위

- [스타일 정본](../guidelines/ui-style-guide.md)에 기존 근거, 색상·폰트·간격·레이아웃·입력·버튼·선택·포커스·반응형·접근성 기준과 검증 명령을 연결했다. AGENTS와 Codex 문서 진입점에는 링크만 추가했다.
- `frontend/src/shared/ui/tokens.css`에 기존 값 기반26개 토큰을 정의했다. `app/styles.css`는 기존 root 색·배경·폰트값을 그대로 변수로 연결하고 두 기존 호환 이름을 보존한다.
- `ChoiceGroup.tsx`/`.module.css`/`.test.tsx`를 추가했다. 도메인 중립 controlled 선택, native fieldset/legend/radio, 그룹 name 격리, 설명 연결, 전체·옵션 disabled를 지원한다.
- `GenerativeEvaluationPanel.tsx`와 `.module.css`에서 공통 그룹을 사용하고 텍스트 입력 스타일이 radio를 제외하도록 수정했다. 기존 모드별 입력·제출 계약은 유지한다.
- `frontend/tests/ui-style/`의 fixture·링크 경계·브라우저 검사3파일을 추가했다. 실제 컴포넌트와 앱 CSS를 사용하며 Next 링크 경계만 일반 링크로 바꾼다. 빈 브라우저 context와 임시 loopback 서버는 검사 후 종료한다. 모든 API 요청은 합성 GET 응답으로 제한하고 다른 요청은 차단한다.
- 이번 변경은 기존6파일+신규9파일이다. 기존1,984파일 기준에서 승인 범위 밖 변경·삭제는 없다.

## 실행 검증

| 검증 | 실제 결과 |
|---|---|
| CSS 브라우저 RED | 기존 입력 크기·별도 줄 배치를 재현하고 작은 glyph assertion 실패 |
| 신규 의미·상태 테스트 RED | ChoiceGroup6개 실패 확인 후 구현 |
| 최종 관련 회귀 | `node node_modules/vitest/vitest.mjs run src/features/rag/configurations src/shared/ui/ChoiceGroup.test.tsx --reporter=dot`: 16파일149개 통과,146.14초,exit0 |
| 독립 검증 | 별도 담당 ChoiceGroup6개 통과(7.03초), 코드·하네스·문서·합성 이미지 리뷰 차단 없음 |
| 실제 CSS 브라우저 GREEN | `node tests/ui-style/preparation-browser.mjs`: Edge1280/375/320px 통과, 실제 API/로그인0 |
| 타입·린트 | 전체 `tsc --noEmit --pretty false --incremental false`, 변경 소스 및 하네스 scoped ESLint 통과 |
| 현재5173 제공본 | JS/CSS/소스맵8개 HTTP200·생성 파일 바이트 일치, 핵심 TSX/CSS4개 소스 일치, 공통 토큰26개 제공 확인 |
| 문서·보존 | 정본 링크 유효성·AGENTS128줄·변경 파일 diff-check·baseline 해시 확인 |

브라우저 측정은 세 폭 모두 glyph16×16px, label44.39px, 같은 행 정렬·넘침0이다. 전체 선택 그룹은1280px에서278.17→134.20px,375px에서326.14→209.02px,320px에서326.14→231.44px로 줄었다. 모바일에서 긴 설명과 두 옵션이 필요한 만큼 줄바꿈된다.

Tab 진입, 방향키·Space 선택, 라벨 클릭, 비활성 옵션 건너뛰기, 그룹 선택 독립성, 모드 왕복 후 입력 보존을 실제 DOM에서 확인했다. focus-visible은 청록2px solid이며, 240px 좁은 컨테이너의 긴 한글 문구도 넘치지 않는다. 합성 캡처를 직접 확인했다.

증거는 `.local-data/project-agent-work/ui-style-foundation-20261019/`의 `browser/before-report.json`, `browser/after-report.json`, 합성 PNG, `frontend-verification.txt`, `served-styles-verification.json`에 보존한다. 초기 하네스 도구 로딩·Next 런타임 경계 오류는 하네스에서 수정했으며 제품 결함 RED와 구분한다. 글로벌 CSS 소스맵은 PostCSS 변환 결과이므로 원본 전체 동일로 주장하지 않고 제공 CSS의 토큰 선언을 별도 확인했다.

## 한계와 다음 적용 후보

- 합성 화면과 현재 제공 자산을 확인했다. 실제 로그인 업무 화면, 사용자 브라우저 캐시·세션, 화면 읽기 프로그램, 모든 브라우저 및 전체 사이트 접근성 적합성은 검증하지 않았다.
- 이번 최종 회귀는 관련16파일이다. 이전 모드 분리 작업의 전체1,064개 통과를 이번 변경의 전체 회귀 결과로 재사용하지 않는다.
- 로그인 `--login-*`, Publishing `--study-*`, 모델 관리·평가 작성의 checkbox만 제외한 입력 선택자, 화면별 버튼·경고·포커스 차이는 남는다. 해당 화면을 수정할 때 공통 값과 선택 그룹을 단계적으로 적용한다.
- 게임 오피스의 픽셀 표현과 Publishing의 읽기 타이포는 용도 차이를 보존한다. 전체 화면 일괄 재작성은 하지 않았다.
- 설치·본래 서버 재시작·DB/backend/모델 설정 변경·실제 평가 제출·모델 호출·인증 우회·사용자 인증 화면 캡처·commit/push는 수행하지 않았다. 기존 RAG P0 순서는 유지한다.
