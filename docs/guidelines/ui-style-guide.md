# AI Workshop 프론트엔드 스타일 기준

- 기준일: 2026-10-19
- 적용: 기존 작업소·관리 화면을 수정하거나 새 UI를 추가할 때 사용한다. 전체 화면을 일괄 전환했다는 의미는 아니다.
- 목적: 현재의 어두운 배경과 청록 강조색을 유지하면서 화면별 크기·정렬·상태 표현 차이를 줄인다.

## 근거와 코드 정본

기존 스타일의 근거는 [앱 스타일](../../frontend/src/app/styles.css), [구성 비교](../../frontend/src/features/rag/configurations/ConfigurationStudioComparison.module.css), [평가 화면](../../frontend/src/features/rag/configurations/GenerativeEvaluation.module.css), [검색 범위 선택](../../frontend/src/features/rag/conversation/ScopeSelector.tsx)이다. 로그인과 Publishing은 자체 이름의 토큰이 있지만 프로젝트 전체 공통 정본은 없었다.

- 공통 값: [tokens.css](../../frontend/src/shared/ui/tokens.css). 앱 스타일에서 한 번 불러온다.
- 단일 선택: [ChoiceGroup](../../frontend/src/shared/ui/ChoiceGroup.tsx)과 [스타일](../../frontend/src/shared/ui/ChoiceGroup.module.css).
- 첫 적용: 평가 준비 방식의 `저장 자료 재사용 / 새 자료 작성`.
- 검증: [합성 브라우저 검사](../../frontend/tests/ui-style/preparation-browser.mjs). 실제 제품 컴포넌트와 앱 CSS를 사용하며 네트워크 경계는 합성 응답으로 제한한다.

## 색상과 타이포그래피

| 용도 | 기존 값·공통 토큰 | 사용 기준 |
|---|---|---|
| 바탕 | `--color-background`: `#0a0e13` | 작업 화면의 기본 배경 |
| 표면 | `--color-surface`: `#111921` | 컨트롤·카드의 구분이 필요한 표면 |
| 본문 | `--color-text`: `#e9edf3` | 주요 제목·본문·입력 |
| 보조 문구 | `--color-text-muted`: `#b3bec7` | 설명·메타데이터; 필수 정보를 과도하게 흐리게 표시하지 않는다 |
| 강조 | `--color-accent`: `#8ee6dc` | 선택·링크·포커스; `--color-accent-text` 호환 이름 유지 |
| 구조 경계 | `--color-border`: `#26313b` | 카드·구역 분리; `--color-border-subtle` 호환 이름 유지 |
| 입력 경계 | `--color-border-control`: `#33414e` | 입력 요소의 윤곽 |

기본 폰트는 기존 Inter → Pretendard → Noto Sans KR → 시스템 글꼴 스택을 `--font-family-ui`로 재사용한다. 원격 폰트 다운로드를 추가하지 않는다. 작업용 본문·컨트롤은 `1rem`, 짧은 보조 문구는 기존 `.85rem`, 줄 높이는 본문 `1.65`, 제목 `1.4`를 기준으로 한다. 문서 읽기 전용 화면의 큰 본문·넓은 줄 간격은 별도 용도로 유지한다.

기존 경고·오류 색은 해당 기능의 의미를 보존한다. 청록색만으로 성공/실패·선택 여부를 전달하지 않는다. 기본 radio는 네이티브 선택 표시, segmented는 선택 문구의 밑줄·굵기와 native checked 상태를 함께 제공한다. 색을 변경할 때 일반 텍스트 대비 4.5:1, 큰 텍스트·필수 컨트롤 상태 3:1을 검증한다. 기존 모든 화면이 이 기준을 통과했다고 간주하지 않는다.

## 간격·크기·레이아웃

- 반복 간격은 `--space-1/2/3/4/6` (`.25/.5/.75/1/1.5rem`)에서 고른다. 기존 화면에서 사용하는 값으로 시작하며 예외는 기능 CSS에 목적을 남긴다.
- 컨트롤 반경은 `--radius-control` (`.45rem`), 구역 반경은 `--radius-panel` (`.8rem`)을 사용한다.
- 버튼·선택 라벨의 클릭 영역은 `--control-min-height` (`2.75rem`, 기본 44px) 이상으로 한다. 라디오 원 자체는 `--control-choice-size` (`1rem`)이다. 클릭 영역과 기호 크기를 분리한다.
- 작업 화면의 폭은 기존 컨테이너를 유지한다. 구성 스튜디오는 최대 `82rem`, 평가 상세는 기존 `92rem`이며 두 제한은 각각의 상위 컨테이너 안에서 작동한다. 새 컴포넌트가 페이지 폭을 임의로 키우지 않는다.
- flex/grid 자식에는 필요한 `min-width: 0`을 적용한다. 긴 한글·식별자와 320px 폭에서도 문구가 줄바꿈되도록 하며, 일반 폼에 가로 스크롤을 만들지 않는다.
- 먼저 컨테이너에 따라 줄바꿈하는 레이아웃을 사용한다. 기존 평가 화면의 700px/1000px 전환은 보존한다. CSS 변수는 media query 조건에 직접 사용할 수 없으므로 새 breakpoint가 필요하면 기존 값을 재사용하고 이유를 문서화한다.

## 입력·버튼·선택·포커스

텍스트 입력의 전체 너비·최소 높이·패딩을 radio/checkbox에 적용하지 않는다. 입력 유형을 명시하거나 두 유형을 모두 제외한다. label의 세로 grid 배치는 텍스트 입력에만 사용하고, 일반 radio/checkbox는 컨트롤과 문구가 같은 행에 오도록 한다. segmented variant는 원형 표시만 시각적으로 숨긴다.

단일 선택에는 `ChoiceGroup`을 우선 사용한다. `fieldset/legend`, 네이티브 radio, 고유한 그룹 name, 설명 연결, 라벨 전체 클릭, controlled value 및 disabled를 제공한다. 기능별 데이터·API 호출을 공통 컴포넌트에 넣지 않는다. 선택 그룹을 탭처럼 꾸미더라도 역할을 무분별하게 `tab`으로 바꾸지 않는다. 페이지 콘텐츠 탭은 기존 구성 스튜디오의 `tablist/tab/tabpanel`와 방향키·Home/End 패턴을 따른다.

`variant="segmented"`는 같은 목적의 소수 모드 선택을 연결된 버튼으로 표현할 때 명시적으로 사용한다. 생략하면 기존 원형 radio 표현을 유지한다. 평가 준비의 저장 자료 재사용/새 자료 작성에 적용하며, on/off switch 의미로 바꾸지 않는다. 시각적으로 숨긴 native radio는 접근성 트리·Tab/방향키/Space 조작을 유지해야 한다.

세그먼트 사이 간격은 0, 공통 외곽선과 내부 구분선을 둔다. 각 label은 최소44px이고 긴 한글은 같은 행의 각 세그먼트 안에서 줄바꿈한다. 어절을 우선 보존하되 무공백 장문은 넘치지 않도록 나눈다. 선택은 청록 배경·진한 글씨·밑줄, hover는 활성 항목에만 배경 변화, focus-visible은 label 전체2px 외곽선으로 표시한다. disabled는 native 속성과 기존 흐림 표현을 유지하며 hover 반응을 주지 않는다. 부모 overflow로 포커스를 자르지 않는다.

기존 상태와 이벤트에 연결하는 사용 예시다. `ChoiceGroup`은 선택을 자체 저장하지 않는다.

```tsx
<ChoiceGroup
  variant="segmented"
  legend="평가 자료 준비 방식"
  description="현재 선택한 방식의 자료와 규칙으로 실행합니다."
  value={mode}
  onChange={changeMode}
  disabled={busy}
  options={[
    { value: "saved", label: "저장 자료 재사용" },
    { value: "create", label: "새 자료 작성" },
  ]}
/>
```

버튼은 기존 구분을 유지한다. 중요한 실행은 명시적 텍스트와 확인 가능한 상태를 제공하고, 보조 동작은 중립 표면·경계로 표시한다. hover만으로 사용 가능 여부를 알리지 않는다. disabled는 네이티브 속성을 사용하고, 입력·선택 값을 삭제하지 않는다. 기존 버튼 전체의 색·반경을 이번 작업에서 바꾸지 않는다.

포커스는 `:focus-visible`과 `--focus-width`/`--focus-offset`를 사용해 보이게 한다. outline을 제거하지 않으며 부모 overflow에 잘리지 않도록 확인한다. 네이티브 radio의 Tab·방향키·Space, 라벨 클릭, disabled 이동 제외를 실제 브라우저에서 검사한다. 새 애니메이션은 기본적으로 추가하지 않고 필요하면 reduced-motion을 지원한다.

## 검증과 적용 범위

1. 상태·콜백·접근 가능한 이름은 Vitest/Testing Library로 확인한다.
2. CSS 변경은 실제 CSS를 렌더링한 브라우저에서 데스크톱·375px·320px, 좁은 컨테이너와 긴 문구, 키보드·포커스·선택/disabled 상태를 확인한다. jsdom 통과는 레이아웃 검증이 아니다.
3. 합성 자료만 사용하고 실제 API 제출·인증 우회를 하지 않는다. 캡처는 합성 검증 화면으로 한정한다.
4. 현재 개발 서버의 제공 파일이 소스와 일치하는지 별도로 확인한다. 합성 화면 검증을 인증된 실제 업무 E2E로 보고하지 않는다.

설치된 도구로 합성 브라우저 검사를 실행한다. `frontend`에서 `node tests/ui-style/preparation-browser.mjs`를 실행하며, 기본 브라우저는 기존 Edge다. 도구나 브라우저가 없으면 설치하지 말고 필요한 항목을 먼저 보고한다. 하네스는 임시 loopback 서버와 빈 브라우저 context를 만들고 종료 시 닫는다. 실제 컴포넌트·CSS를 사용하되 Next 링크 경계만 일반 링크로 대체하며, 실제 앱의 로그인·라우팅·API는 검사하지 않는다. 결과와 합성 캡처는 Git 제외된 `.local-data/browser-verification/preparation/`에 저장한다. `UI_STYLE_OUTPUT_DIR`로 작업별 증거 디렉터리를 지정할 수 있다. 저장/작성/평가 제출 요청까지 합성 응답으로 가로채며 실제 backend로 보내지 않는다. 두 모드의 자료·규칙·문맥 제출과 초안 보존, 기본 원형 variant도 함께 검사한다.

현재 적용은 공통 토큰 정의·기존 root 값 연결·평가 준비 선택 그룹이다. 다음 항목은 남은 불일치이며 이번에 일괄 수정하지 않았다.

- 로그인은 `--login-*`, Publishing은 읽기 중심 `--study-*` 토큰을 사용한다. 용도별 차이를 검토한 뒤 공통 값만 단계적으로 연결한다.
- 모델 관리·평가 작성·전역 구성 입력 스타일에도 `input:not(checkbox)` 패턴이 남아 있다. 해당 화면에 radio를 추가할 때 유형 분리와 브라우저 검증이 필요하다.
- 기존 페이지의 경고색·버튼 강조색·간격·focus 색은 아직 다양하다. 새 작업에서 해당 범위를 수정할 때 이 기준과 비교한다.
- 게임 오피스의 픽셀 화면과 Publishing의 읽기 타이포는 목적이 다른 화면이다. 관리 폼의 밀도·글꼴을 그대로 강제하지 않는다.
